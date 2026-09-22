"""Isolated microbenchmark; never loads a model or modifies a serving spool.

python -m sft.tests.benchmark_capture_overhead --baseline-dir /path/to/old/modules \
  --work-dir /path/to/isolated/scratch --device cpu --output /tmp/result.json
"""
import argparse
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import tempfile
import time


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline-dir', type=Path, required=True)
    p.add_argument('--work-dir', type=Path, required=True)
    p.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--capture-jsonl', type=Path, help='Optional existing server record; read-only replay of three real rows')
    args = p.parse_args()
    import torch
    from sft.analysis import attention_store as store, vllm_capture as capture
    torch.set_num_threads(1)
    torch.manual_seed(17)
    old_store = load('old_store', args.baseline_dir/'attention_store.py')
    old_capture = load('sft.analysis.old_capture', args.baseline_dir/'vllm_capture.py')
    args.work_dir.mkdir(parents=True, exist_ok=True)
    result = dict(device=args.device, torch=torch.__version__, scope='microbenchmark, not model throughput',
                  storage=[], entropy={}, event_loop={})
    def measure(fn, count=20):
        if args.device == 'cuda': torch.cuda.synchronize()
        started = time.perf_counter()
        for _ in range(count): fn()
        if args.device == 'cuda': torch.cuda.synchronize()
        return (time.perf_counter()-started)*1000/count
    with tempfile.TemporaryDirectory(dir=args.work_dir) as tmp:
        root = Path(tmp)
        for size in (20400, 64000):
            weights = torch.softmax(torch.randn(size, device=args.device), dim=-1)
            timings = {'old': [], 'new': []}
            old_path, new_path = root/'old.attn', root/'new.attn'
            functions = {'old': lambda: old_store.append_row(old_path, weights.tolist()),
                         'new': lambda: store.append_row(new_path, weights.detach().cpu().numpy())}
            for fn in functions.values(): fn()  # warmup
            for repeat in range(5):
                for mode in (('old','new') if repeat%2 == 0 else ('new','old')):
                    timings[mode].append(measure(functions[mode]))
            equal = store.file_hash(old_path) == store.file_hash(new_path)
            assert equal, 'binary output changed'
            result['storage'].append(dict(keys=size, old_ms=statistics.median(timings['old']),
                new_ms=statistics.median(timings['new']), byte_identical=equal, repeats=timings))
            old_path.unlink();new_path.unlink()
        # Qwen3.5 vocabulary-sized synthetic logits; includes the unchanged top-k work.
        logits = torch.randn(248320, device=args.device)
        def token_diag(reuse):
            lp = torch.log_softmax(logits.float(), dim=-1)
            values, ids = torch.topk(lp, 5)
            ent = capture.entropy(logits, logp=lp) if reuse else old_capture.entropy(logits)
            return ent.item(), values.tolist(), ids.tolist()
        assert token_diag(False) == token_diag(True), 'entropy/top-k changed'
        times = {'old': [], 'new': []}
        for repeat in range(5):
            for mode in (('old','new') if repeat%2 == 0 else ('new','old')):
                times[mode].append(measure(lambda: token_diag(mode == 'new')))
        result['entropy'] = dict(old_ms=statistics.median(times['old']), new_ms=statistics.median(times['new']),
                                 exact_equal=True, repeats=times)
        # Actual collect()/file_hash() on an isolated spool, with a 2 ms loop ticker.
        spool = root/'spool';spool.mkdir()
        capture._write(spool,'bench',0,dict(type='metadata',prompt_token_ids=[1],images=[]))
        weights = torch.softmax(torch.randn(64000),dim=-1).numpy()
        for index in range(256):
            capture._write(spool,'bench',0,dict(type='attention',query=63999,output_index=index,
                          weights=weights,binary_storage=True))
        async def collect_trial(background):
            gaps=[];running=True
            async def ticker():
                last=time.perf_counter()
                while running:
                    await asyncio.sleep(.002)
                    now=time.perf_counter();gaps.append((now-last)*1000);last=now
            timer=asyncio.create_task(ticker());await asyncio.sleep(.01)
            start=time.perf_counter()
            value=await asyncio.to_thread(capture.collect,spool,'bench') if background else capture.collect(spool,'bench')
            elapsed=(time.perf_counter()-start)*1000
            await asyncio.sleep(.01);running=False;await timer
            return dict(collect_ms=elapsed,max_loop_gap_ms=max(gaps)),value
        expected = capture.collect(spool, 'bench')  # Warm filesystem cache for both paths.
        trials = {'old': [], 'new': []}
        for repeat in range(5):
            for mode in (('old','new') if repeat%2 == 0 else ('new','old')):
                timing, payload = asyncio.run(collect_trial(mode == 'new'))
                assert payload == expected, 'collect payload changed'
                trials[mode].append(timing)
        result['event_loop'] = dict(payload_equal=True, repeats=trials,
            blob_bytes=sum(v['bytes'] for v in expected['attention_blobs'].values()),
            **{mode: {k:statistics.median(t[k] for t in trials[mode]) for k in trials[mode][0]}
               for mode in trials})
        if args.capture_jsonl:
            records = [json.loads(line) for line in args.capture_jsonl.read_text().splitlines() if line.strip()]
            rows = [r for r in records if 'weights_ref' in r]
            result['real_rows'] = []
            for index in sorted({0, len(rows)//2, len(rows)-1}):
                row = rows[index]
                row['weights_ref']['path'] = row['weights_ref']['blob']
                values = store.read_row(row, args.capture_jsonl.parent)
                old_path, new_path = root/f'real-old-{index}.attn', root/f'real-new-{index}.attn'
                old_ref = old_store.append_row(old_path, list(values))
                new_ref = store.append_row(new_path, values)
                assert old_ref == new_ref
                assert new_ref['chunk_sha256'] == row['weights_ref']['chunk_sha256']
                result['real_rows'].append(dict(output_index=row['output_index'], keys=row['key_count'],
                    source_chunk_sha256=new_ref['chunk_sha256'], byte_identical_to_original=True))
    result['source_sha256']={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in
                           (Path(capture.__file__),Path(store.__file__))}
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':main()
