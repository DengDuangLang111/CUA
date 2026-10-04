"""Count the actual chat tokens plus image expansion; verify against Swift."""
import copy
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

os.environ['IMAGE_MAX_TOKEN_NUM'] = '2048'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
os.environ['HF_HUB_OFFLINE'] = '1'

import torch
from PIL import Image
from swift.model import get_model_processor
from swift.template import get_template
from qwen_vl_utils import vision_process

ROOT = Path('/gscratch/cse/jy050706/sft')
OUT = ROOT / 'experiments/a100-length-probe-20260917'
DATA = Path('/gpfs/scrubbed/jy050706/sft/data/r5-v16save143-tf')
MODEL = ROOT / 'models/Qwen3.5-9B'
CAPS = [16384, 24576, 32768, 49152, 65536, 81920]


def main():
    torch.set_num_threads(8)
    _, processor = get_model_processor(str(MODEL), load_model=False, model_type='qwen3_5')
    tokenizer = processor.tokenizer
    template = get_template(processor, template_type='qwen3_5', max_length=262144,
                            loss_scale='last_round', preserve_thinking=True)
    template.set_mode('train')
    sizes = json.loads((OUT / 'image_sizes.json').read_text())
    grid_tokens = {}
    for path, (w, h) in sizes.items():
        factor = processor.image_processor.patch_size * processor.image_processor.merge_size
        rh, rw = vision_process.smart_resize(h, w, factor=factor,
            min_pixels=vision_process.IMAGE_MIN_TOKEN_NUM * factor ** 2,
            max_pixels=2048 * factor ** 2)
        grid_tokens[path] = (rh // factor) * (rw // factor)
    rows = [json.loads(s) for s in (DATA / 'train_swift_abs.jsonl').open()]
    provenance = [json.loads(s) for s in (DATA / 'row_provenance.jsonl').open()]
    assert len(rows) == len(provenance) == 10142
    lengths = []
    image_id = tokenizer.convert_tokens_to_ids('<|image_pad|>')
    for i, row in enumerate(rows):
        messages = copy.deepcopy(row['messages'])
        for m in messages:
            m['content'] = m['content'].replace('<image>', '<|vision_start|><|image_pad|><|vision_end|>')
        ids = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False,
                                            enable_thinking=True, preserve_thinking=True, return_dict=False)
        if hasattr(ids, 'keys'):
            ids = ids['input_ids']
        if ids and isinstance(ids[0], list):
            assert len(ids) == 1
            ids = ids[0]
        assert ids.count(image_id) == len(row['images']), i
        lengths.append(len(ids) + sum(grid_tokens[p] - 1 for p in row['images']))
        if (i + 1) % 2000 == 0:
            print(f'COUNTED {i+1}/{len(rows)} max={max(lengths)}', flush=True)
    candidates = list(dict.fromkeys([0, 1357, 1358, 6473, 6474, 10141] +
                        sorted(range(len(rows)), key=lambda i: lengths[i], reverse=True)[:32] +
                        list(range(6474, len(rows), 100))))
    checks = [i for i in candidates if all(Path(p).exists() for p in rows[i]['images'])][:16]
    assert len(checks) >= 8, 'Need at least 8 complete examples for Swift validation'
    verified = []
    for i in checks:
        exact = template.encode(copy.deepcopy(rows[i]))
        n = len(exact['input_ids'])
        assert n == lengths[i], (i, n, lengths[i])
        verified.append({'row': i, 'tokens': n, 'label_tokens': sum(v != -100 for v in exact['labels'])})
        print(f'CHECK Swift row={i} tokens={n} matches', flush=True)
    last = {}
    for i, p in enumerate(provenance):
        last[(p['run'], p['task_id'])] = i
    assert len(last) == 505
    ordered = sorted(lengths)
    summary = {'samples': len(rows), 'tasks': len(last), 'image_token_counts': dict(Counter(grid_tokens.values())),
        'quantiles': {str(q): ordered[round((len(ordered)-1)*q)] for q in [0, .5, .9, .95, .99, 1]},
        'swift_checks': verified, 'thresholds': {},
        'dataset_sha256': hashlib.sha256((DATA/'train_swift_abs.jsonl').read_bytes()).hexdigest()}
    with (OUT / 'row_lengths.jsonl').open('w') as f:
        for i, n in enumerate(lengths):
            f.write(json.dumps({'row': i, 'tokens': n, **provenance[i],
                               'terminal': i == last[(provenance[i]['run'], provenance[i]['task_id'])]}) + '\n')
    for cap in CAPS:
        dropped = [i for i, n in enumerate(lengths) if n > cap]
        lost_terminal = [i for i in last.values() if lengths[i] > cap]
        eligible = sorted((i for i, n in enumerate(lengths) if n <= cap), key=lambda i: lengths[i], reverse=True)[:64]
        with (OUT / f'top64-{cap}.jsonl').open('w') as f:
            for i in eligible:
                f.write(json.dumps(rows[i], ensure_ascii=False) + '\n')
        summary['thresholds'][cap] = {'dropped_rows': len(dropped), 'dropped_pct': 100*len(dropped)/len(rows),
            'lost_terminal_tasks': len(lost_terminal),
            'affected_tasks': len({(provenance[i]['run'], provenance[i]['task_id']) for i in dropped}),
            'test_min_tokens': min(lengths[i] for i in eligible), 'test_max_tokens': max(lengths[i] for i in eligible)}
    (OUT / 'length_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
