"""Check a two-step smoke checkpoint and sample its language-weight updates."""
import json
import sys
from pathlib import Path

import torch
from safetensors import safe_open

case = Path(sys.argv[1])
base = Path('/tmp/jy050706-a100-length-20260917/Qwen3.5-9B')
checkpoints = list((case / 'train').glob('*/checkpoint-2'))
assert len(checkpoints) == 1, checkpoints
ckpt = checkpoints[0]
state = json.loads((ckpt / 'trainer_state.json').read_text())
assert state['global_step'] == 2
assert (ckpt / 'scheduler.pt').is_file()
assert all((ckpt / f'rng_state_{rank}.pth').is_file() for rank in range(4))
tag = (ckpt / 'latest').read_text().strip()
assert tag == 'global_step2', tag
optimizers = list((ckpt / tag).glob('*optim_states.pt'))
assert len(optimizers) == 4 and all(p.stat().st_size > 0 for p in optimizers)
indices = [json.loads((p / 'model.safetensors.index.json').read_text())['weight_map'] for p in [base, ckpt]]
unused_mtp = sorted(set(indices[0]) - set(indices[1]))
assert not (set(indices[1]) - set(indices[0]))
assert all(k.startswith('mtp.') for k in unused_mtp), unused_mtp
assert all((ckpt / f).is_file() for f in set(indices[1].values()))
keys = sorted(k for k in indices[0] if 'language_model.layers.' in k and 'proj' in k and k.endswith('.weight'))
selected = [keys[0], keys[len(keys)//2], keys[-1]]
results = []
for key in selected:
    tensors = []
    for root, index in zip([base, ckpt], indices):
        with safe_open(str(root / index[key]), framework='pt', device='cpu') as f:
            s = f.get_slice(key)
            shape = s.get_shape()
            assert len(shape) == 2
            tensors.append(s[:min(128, shape[0]), :min(128, shape[1])].float())
    a, b = tensors
    results.append({'tensor': key, 'sampled_values': a.numel(), 'changed_values': int((a != b).sum()),
                    'max_abs_delta': float((a-b).abs().max())})
assert sum(r['changed_values'] for r in results) > 0, 'No language-weight update observed'
summary = {'checkpoint': str(ckpt), 'global_step': 2, 'optimizer_shards': len(optimizers),
           'model_shards': len(set(indices[1].values())), 'weight_checks': results,
           'uninstantiated_base_mtp_keys': unused_mtp,
           'checkpoint_bytes': sum(p.stat().st_size for p in ckpt.rglob('*') if p.is_file()),
           'scope': 'Checkpoint files and sampled weight updates verified; resume and full-epoch run not tested.'}
(case / 'checkpoint_verification.json').write_text(json.dumps(summary, indent=2)+'\n')
print(json.dumps(summary, indent=2))
