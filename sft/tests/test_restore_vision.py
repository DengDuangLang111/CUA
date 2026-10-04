"""Exact weight-splicing regression tests; run with the training Python environment."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
try:
    import torch
    from safetensors.torch import save_file, load_file
except ImportError:
    torch = None
from sft.data.restore_vision import restore, layout, sha256


@unittest.skipIf(torch is None, 'Requires the existing training PyTorch/safetensors environment')
class RestoreVisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base, self.language, self.output = (self.root / n for n in ('base', 'language', 'assembled'))
        self.base.mkdir(); self.language.mkdir()
        self.weights = {'model.language_model.embed_tokens.weight': torch.ones(4, 2, dtype=torch.bfloat16),
                        'lm_head.weight': torch.ones(4, 2, dtype=torch.bfloat16),
                        'model.visual.encoder.weight': torch.arange(4, dtype=torch.bfloat16).reshape(2, 2),
                        'model.visual.merger.weight': torch.full((2, 2), 3, dtype=torch.bfloat16),
                        'mtp.fc.weight': torch.full((2, 2), 7, dtype=torch.bfloat16)}
        self.trained = {k: v + 10 for k, v in self.weights.items() if not k.startswith(('model.visual.', 'mtp.'))}
        save_file(self.weights, self.base / 'model.safetensors')
        save_file(self.trained, self.language / 'model.safetensors')
        config = {'model_type': 'qwen3_5', 'text_config': {'vocab_size': 4}, 'vision_config': {'patch_size': 16}}
        tokenizer = {'model': {'vocab': {'a': 0, 'b': 1}, 'merges': [['a', 'b']]}, 'added_tokens': []}
        for directory in (self.base, self.language):
            (directory / 'config.json').write_text(json.dumps(config))
            (directory / 'tokenizer.json').write_text(json.dumps(tokenizer))
        for name in ('tokenizer_config.json', 'preprocessor_config.json'):
            (self.base / name).write_text('{}')
        (self.base / 'chat_template.jinja').write_text('base CUA template')
        self.record_download()

    def record_download(self):
        (self.language / 'DOWNLOAD_MANIFEST.json').write_text(json.dumps({'revision': 'test-revision', 'files': [
            {'file': 'model.safetensors', 'sha256': sha256(self.language / 'model.safetensors')}]}))

    def test_exact_language_and_visual_weights_and_no_source_mutation(self):
        before = {str(p): sha256(p) for d in (self.base, self.language) for p in d.iterdir()}
        report = restore(self.base, self.language, self.output, 'test-revision')
        self.assertEqual((report['language_tensors'], report['visual_tensors'], report['mtp_tensors']), (2, 2, 1))
        merged = {}
        for p in self.output.glob('*.safetensors'): merged.update(load_file(p))
        self.assertEqual(set(merged), set(self.weights))
        for key in merged:
            self.assertTrue(torch.equal(merged[key], self.trained[key] if key in self.trained else self.weights[key]))
        self.assertEqual((self.output / 'chat_template.jinja').read_text(), 'base CUA template')
        self.assertEqual(before, {str(p): sha256(p) for d in (self.base, self.language) for p in d.iterdir()})
        self.assertEqual(set(layout(self.output)), set(self.weights))
        with self.assertRaises(FileExistsError): restore(self.base, self.language, self.output, 'test-revision')

    def test_missing_language_tensor_and_changed_shape_are_rejected(self):
        weights = copy.deepcopy(self.trained); weights.pop('lm_head.weight')
        save_file(weights, self.language / 'model.safetensors')
        with self.assertRaisesRegex(ValueError, 'key mismatch'): restore(self.base, self.language, self.output)
        weights = copy.deepcopy(self.trained); weights['lm_head.weight'] = torch.ones(3, 2)
        save_file(weights, self.language / 'model.safetensors')
        with self.assertRaisesRegex(ValueError, 'shapes'): restore(self.base, self.language, self.output)
        self.assertFalse(self.output.exists())

    def test_changed_token_id_revision_and_source_hash_are_rejected(self):
        tokenizer = json.loads((self.language / 'tokenizer.json').read_text())
        tokenizer['model']['vocab']['a'] = 99
        (self.language / 'tokenizer.json').write_text(json.dumps(tokenizer))
        with self.assertRaisesRegex(ValueError, 'vocabulary'): restore(self.base, self.language, self.output)
        (self.language / 'tokenizer.json').write_bytes((self.base / 'tokenizer.json').read_bytes())
        with self.assertRaisesRegex(ValueError, 'revision'): restore(self.base, self.language, self.output, 'wrong')
        save_file({k: v + 1 for k, v in self.trained.items()}, self.language / 'model.safetensors')
        with self.assertRaisesRegex(ValueError, 'checksum'): restore(self.base, self.language, self.output, 'test-revision')


if __name__ == '__main__':
    unittest.main()
