"""Verify the frozen corpus at launch without redoing media decoding."""
import hashlib
import json
from pathlib import Path

BASE = Path('/gpfs/scrubbed/jy050706/sft')
DS = BASE / 'data/r5-v16save143-tf'
manifest = json.loads((DS / 'manifest.json').read_text())
assert manifest['status'] == 'data_integrity_verified'
assert manifest['trajectories'] == manifest['explicit_terminal_success'] == 505
assert manifest['samples'] == 10142
h = hashlib.sha256()
images = set()
rows = 0
for line in (DS / 'train_swift_abs.jsonl').open('rb'):
    h.update(line)
    if line.strip():
        rows += 1
        images.update(json.loads(line)['images'])
assert rows == 10142 and h.hexdigest() == manifest['train_sha256']
assert all(Path(p).is_absolute() and Path(p).is_file() and Path(p).stat().st_size > 0 for p in images)
model = BASE / 'models/Qwen3.5-9B'
assert model.resolve().name == 'Qwen3.5-9B'
assert json.loads((model / 'config.json').read_text())['model_type'] == 'qwen3_5'
index = json.loads((model / 'model.safetensors.index.json').read_text())
assert all((model / p).is_file() for p in set(index['weight_map'].values()))
print(f'PREFLIGHT PASS rows={rows} tasks=505 terminal_success=505 images={len(images)} base={model}', flush=True)
