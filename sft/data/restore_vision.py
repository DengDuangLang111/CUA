"""Attach original Qwen vision/MTP tensors to a text-only trained checkpoint.

The language shards are copied or hard-linked verbatim. A separate shard holds
only the missing, explicitly allowed tensors. No model is randomly initialized.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import tempfile


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def layout(directory):
    directory = Path(directory).resolve()
    index = directory / 'model.safetensors.index.json'
    declared = json.loads(index.read_text())['weight_map'] if index.exists() else None
    names = sorted(set(declared.values())) if declared else [p.name for p in sorted(directory.glob('*.safetensors'))]
    if not names:
        raise ValueError(f'No safetensors in {directory}')
    tensors = {}
    for name in names:
        path = (directory / name).resolve()
        if not path.is_relative_to(directory):
            raise ValueError('Shard path escapes model directory')
        with path.open('rb') as stream:
            length = struct.unpack('<Q', stream.read(8))[0]
            if not 0 < length < 100_000_000:
                raise ValueError('Invalid safetensors header length')
            header = json.loads(stream.read(length))
        for key, value in header.items():
            if key == '__metadata__':
                continue
            if key in tensors:
                raise ValueError(f'Duplicate tensor: {key}')
            tensors[key] = dict(value, file=name)
    if declared is not None and declared != {k: v['file'] for k, v in tensors.items()}:
        raise ValueError('Index does not exactly describe the shard contents')
    return tensors


def tokenizer_compatibility(base, language):
    a = json.loads((base / 'tokenizer.json').read_text())
    b = json.loads((language / 'tokenizer.json').read_text())
    normalize = lambda items: [tuple(x.split(' ')) if isinstance(x, str) else tuple(x) for x in items]
    if a['model']['vocab'] != b['model']['vocab'] or normalize(a['model']['merges']) != normalize(b['model']['merges']):
        raise ValueError('Language tokenizer vocabulary/merges differ from base')
    for key in ('normalizer', 'pre_tokenizer', 'post_processor', 'decoder'):
        if a.get(key) != b.get(key):
            raise ValueError(f'Tokenizer {key} differs')
    original = {x['id']: x for x in a.get('added_tokens', [])}
    trained = {x['id']: x for x in b.get('added_tokens', [])}
    if any(trained.get(key) != value for key, value in original.items()):
        raise ValueError('An existing added token changed identity or behavior')
    return dict(source='base', extra_language_tokens=[trained[k] for k in sorted(trained.keys() - original.keys())])


def restore(base_model, language_model, output, revision=None):
    from safetensors import safe_open
    from safetensors.torch import save_file

    base, language, output = map(lambda p: Path(p).resolve(), (base_model, language_model, output))
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite {output}')
    original, trained = layout(base), layout(language)
    expected = {k for k in original if not k.startswith(('model.visual.', 'mtp.'))}
    if set(trained) != expected:
        raise ValueError(f'Language key mismatch: missing={sorted(expected-set(trained))}, extra={sorted(set(trained)-expected)}')
    if any(original[k]['shape'] != trained[k]['shape'] for k in trained):
        raise ValueError('Language tensor shapes differ')
    missing = sorted(set(original) - set(trained))
    if not any(k.startswith('model.visual.') for k in missing):
        raise ValueError('No original visual tensors to restore')
    base_config = json.loads((base / 'config.json').read_text())
    language_config = json.loads((language / 'config.json').read_text())
    for key in ('model_type', 'text_config', 'vision_config', 'image_token_id', 'video_token_id',
                'vision_start_token_id', 'vision_end_token_id', 'tie_word_embeddings'):
        if base_config.get(key) != language_config.get(key):
            raise ValueError(f'Model configuration differs: {key}')
    tokenizer = tokenizer_compatibility(base, language)
    download = language / 'DOWNLOAD_MANIFEST.json'
    source = json.loads(download.read_text()) if download.exists() else {}
    if revision and source.get('revision') != revision:
        raise ValueError('Downloaded revision does not match the requested revision')
    required = ['config.json', 'tokenizer.json', 'tokenizer_config.json', 'preprocessor_config.json', 'chat_template.jinja']
    if any(not (base / name).is_file() for name in required):
        raise ValueError('Base model is missing required tokenizer/processor metadata')

    language_files = sorted({v['file'] for v in trained.values()})
    language_hashes = {name: sha256(language / name) for name in language_files}
    recorded = {v['file']: v for v in source.get('files', [])}
    for name, digest in language_hashes.items():
        if revision and (name not in recorded or recorded[name]['sha256'] != digest):
            raise ValueError(f'Language source checksum differs: {name}')
    base_files = sorted({original[k]['file'] for k in missing})
    base_hashes = {name: sha256(base / name) for name in base_files}

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=output.name + '.staging-', dir=output.parent))
    try:
        weight_map, outputs = {}, []
        count = len(language_files) + 1
        for number, name in enumerate(language_files, 1):
            target = f'model-{number:05d}-of-{count:05d}.safetensors'
            try:
                os.link(language / name, staging / target)
            except OSError:
                shutil.copyfile(language / name, staging / target)
            if sha256(staging / target) != language_hashes[name]:
                raise ValueError('Copied language shard differs from its source')
            outputs.append(dict(file=target, sha256=language_hashes[name], source=str(language / name)))
            weight_map.update({k: target for k in trained if trained[k]['file'] == name})

        supplement = {}
        for name in base_files:
            with safe_open(base / name, framework='pt', device='cpu') as weights:
                for key in missing:
                    if original[key]['file'] == name:
                        supplement[key] = weights.get_tensor(key).contiguous()
        target = f'model-{count:05d}-of-{count:05d}.safetensors'
        save_file(supplement, staging / target, metadata={'format': 'pt'})
        import torch
        with safe_open(staging / target, framework='pt', device='cpu') as weights:
            for key, tensor in supplement.items():
                if not torch.equal(tensor, weights.get_tensor(key)):
                    raise ValueError(f'Restored tensor differs: {key}')
        weight_map.update({k: target for k in missing})
        outputs.append(dict(file=target, sha256=sha256(staging / target), source='original base visual/MTP tensors'))
        total_size = sum(v['data_offsets'][1] - v['data_offsets'][0] for v in trained.values())
        total_size += sum(original[k]['data_offsets'][1] - original[k]['data_offsets'][0] for k in missing)
        (staging / 'model.safetensors.index.json').write_text(json.dumps(
            dict(metadata={'total_size': total_size}, weight_map=weight_map), indent=2) + '\n')

        metadata = {}
        for name in required + ['video_preprocessor_config.json', 'vocab.json', 'merges.txt', 'generation_config.json', 'LICENSE']:
            if (base / name).is_file():
                shutil.copyfile(base / name, staging / name)
                metadata[name] = sha256(staging / name)
        final = layout(staging)
        if set(final) != set(original) or any(final[k]['shape'] != original[k]['shape'] for k in final):
            raise ValueError('Assembled checkpoint does not match the complete base structure')
        manifest = dict(schema_version=1, status='verified', base_model=str(base), language_model=str(language),
                        language_revision=source.get('revision'), base_shards=base_hashes, language_shards=language_hashes,
                        output_shards=outputs, metadata_sha256=metadata, tokenizer=tokenizer,
                        language_tensors=len(trained), visual_tensors=sum(k.startswith('model.visual.') for k in missing),
                        mtp_tensors=sum(k.startswith('mtp.') for k in missing), mtp_enabled=False,
                        parameter_count=sum(math.prod(v['shape']) for v in final.values()),
                        language_dtypes=dict(Counter(v['dtype'] for v in trained.values())))
        (staging / 'INIT_MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
        staging.rename(output)
        return manifest
    except BaseException:
        shutil.rmtree(staging)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-model', type=Path, required=True)
    parser.add_argument('--language-model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--revision')
    args = parser.parse_args()
    result = restore(args.base_model, args.language_model, args.output, args.revision)
    print(json.dumps({k: result[k] for k in ('status', 'language_tensors', 'visual_tensors', 'mtp_tensors', 'parameter_count')}))


if __name__ == '__main__':
    main()
