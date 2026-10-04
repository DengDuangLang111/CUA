import hashlib
import json
import os
from pathlib import Path

base = Path('/gscratch/cse/jy050706/sft')
assert os.environ.get('NNODES') is None and os.environ.get('NPROC_PER_NODE') is None, 'Swift would launch a nested torchrun'
data = base / 'data/r5-v16save143-tf'
manifest = json.loads((data / 'manifest.json').read_text())
dataset = data / 'train_swift_abs.jsonl'
assert hashlib.sha256(dataset.read_bytes()).hexdigest() == manifest['train_sha256']
assert manifest['trajectories'] == manifest['explicit_terminal_success'] == 505
assert manifest['samples'] == 10142
summary = json.loads((base / 'experiments/a100-length-probe-20260917/length_summary.json').read_text())
assert summary['dataset_sha256'] == manifest['train_sha256']
assert summary['thresholds']['65536']['dropped_rows'] == 0
images = set()
rows = 0
for line in dataset.open():
    rows += 1
    row = json.loads(line)
    assert row['messages'][-1]['role'] == 'assistant'
    images.update(row['images'])
assert rows == 10142
assert all(Path(p).is_file() and Path(p).stat().st_size > 0 for p in images)
model = Path('/tmp/jy050706-a100-length-20260917/Qwen3.5-9B')
assert json.loads((model / 'config.json').read_text())['model_type'] == 'qwen3_5'
index = json.loads((model / 'model.safetensors.index.json').read_text())
assert all((model / p).is_file() for p in set(index['weight_map'].values()))
print(f'PREFLIGHT PASS samples={rows} tasks=505 images={len(images)} max_actual_tokens=58441 base=Qwen3.5-9B', flush=True)
