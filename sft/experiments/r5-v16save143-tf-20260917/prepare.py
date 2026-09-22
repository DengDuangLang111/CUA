"""Freeze the user-selected 505 trajectories without rewriting training rows."""
import collections
import hashlib
import json
import os
import re
from pathlib import Path

from PIL import Image

BASE = Path('/gpfs/scrubbed/jy050706/sft')
HERE = Path(__file__).resolve().parent
DEST = BASE / 'data/r5-v16save143-tf'
EXPECTED_SOURCE_ROWS = {
    'q38-Bhqs2t-r5nocapimg10-v11100': 1358,
    'q38-Bhqs2t-r5nocapimg10-v11500': 5116,
    'mixbtf-v16-main': 11670,
    'mixbtf-v16-pilot': 1694,
}


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    selection_path = HERE / 'selection.json'
    selection = json.loads(selection_path.read_text())
    tasks = selection['tasks']
    assert len(tasks) == 505 and sum(t['samples'] for t in tasks) == 10142
    wanted = {(t['source'], t['task_id'][:8]): t for t in tasks}
    assert len(wanted) == 505, 'Ambiguous task prefix'
    assert not DEST.exists(), f'Refusing to overwrite {DEST}'
    stage = DEST.with_name(DEST.name + f'.stage-{os.getpid()}')
    stage.mkdir()
    counts = collections.Counter()
    unique_images = set()
    image_refs = 0
    source_hashes = {}
    channels = collections.Counter()
    last_response = {}
    out = stage / 'train_swift_abs.jsonl'
    with out.open('wb') as output, (stage / 'row_provenance.jsonl').open('w') as provenance:
        for source, expected in EXPECTED_SOURCE_ROWS.items():
            path = BASE / 'data' / source / 'train_swift_abs.jsonl'
            h = hashlib.sha256()
            source_count = 0
            for line_no, line in enumerate(path.open('rb'), 1):
                h.update(line)
                if not line.strip():
                    continue
                source_count += 1
                row = json.loads(line)
                images = row.get('images') or []
                assert images, (source, line_no, 'no images')
                id8 = Path(images[0]).parent.name.rsplit('-', 1)[-1]
                key = (source, id8)
                if key not in wanted:
                    continue
                t = wanted[key]
                assert 1 <= len(images) <= 10, (source, line_no, len(images))
                assert all(Path(p).is_absolute() for p in images)
                assert all(Path(p).parent.name.rsplit('-', 1)[-1] == id8 for p in images)
                messages = row['messages']
                assert messages[0]['role'] == 'system'
                assert messages[-1]['role'] == 'assistant' and messages[-1]['content'].strip()
                assert all(isinstance(m['content'], str) for m in messages)
                assert sum(m['content'].count('<image>') for m in messages) == len(images)
                assert set(row) == {'messages', 'images', 'channel'}, set(row)
                output.write(line if line.endswith(b'\n') else line + b'\n')
                provenance.write(json.dumps({'source': source, 'source_line': line_no,
                    'run': t['run'], 'domain': t['domain'], 'task_id': t['task_id'],
                    'sha256': hashlib.sha256(line).hexdigest()}) + '\n')
                counts[key] += 1
                last_response[key] = messages[-1]['content']
                channels[row['channel']] += 1
                unique_images.update(images)
                image_refs += len(images)
            assert source_count == expected, (source, source_count, expected)
            source_hashes[str(path)] = h.hexdigest()
            print(f'{source}: source={source_count}, selected={sum(n for (s, _), n in counts.items() if s == source)}', flush=True)
    assert counts == {key: t['samples'] for key, t in wanted.items()}, 'Per-task row count mismatch'
    assert sum(counts.values()) == 10142
    for key, response in last_response.items():
        actions = re.findall(r'<parameter=action>\s*([a-z_]+)\s*</parameter>', response)
        assert actions and actions[-1] == 'terminate', (key, 'missing terminate')
        assert re.search(r'<parameter=status>\s*success\s*</parameter>', response), (key, 'not success')
        assert not re.search(r'<parameter=status>\s*(fail|failure|infeasible)', response, re.I)
    for i, path in enumerate(sorted(unique_images), 1):
        with Image.open(path) as img:
            img.verify()
        if i % 2000 == 0:
            print(f'Validated {i}/{len(unique_images)} images', flush=True)
    manifest = {
        'status': 'data_integrity_verified',
        'admission_status': 'fixed user-selected candidates, not new independent task certification',
        'trajectories': 505, 'samples': 10142, 'r5_trajectories': 362, 'r5_samples': 6474,
        'v16_trajectories': 143, 'v16_samples': 3668,
        'v16_multi_trajectories': 37, 'v16_multi_samples': 1128,
        'selection_sha256': sha256(selection_path), 'prepare_sha256': sha256(Path(__file__)),
        'train_sha256': sha256(out), 'row_provenance_sha256': sha256(stage / 'row_provenance.jsonl'),
        'sources': source_hashes, 'channels': dict(channels),
        'image_references': image_refs, 'unique_images': len(unique_images),
        'images_verified': len(unique_images), 'row_changes': 'none relative to original r5 + existing mixbtf v16 sources',
        'explicit_terminal_success': len(last_response),
        'v16_terminalfix': dict(collections.Counter(t['terminalfix']['mode'] for t in tasks if 'terminalfix' in t)),
        'v16_tail_rows_removed': sum(t.get('original_samples', t['samples']) - t['samples'] for t in tasks),
        'epochs': 3, 'global_batch': 64, 'steps_per_epoch': 159, 'total_steps': 477,
    }
    (stage / 'selection.json').write_bytes(selection_path.read_bytes())
    (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    stage.rename(DEST)
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == '__main__':
    main()
