"""Repository layout and serialization regression checks; no GPU/VM/API calls."""
import ast
import contextlib
import copy
import importlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
# The live package is named ostg; this mirror directory is named CUA.
spec = importlib.util.spec_from_file_location(
    'ostg', ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
package = importlib.util.module_from_spec(spec)
sys.modules['ostg'] = package
spec.loader.exec_module(package)


def files():
    out = subprocess.check_output(['git', 'ls-files', '-co', '--exclude-standard', '-z'], cwd=ROOT)
    return sorted({ROOT / x.decode() for x in out.split(b'\0') if x and (ROOT / x.decode()).is_file()})


class RepositoryLayout(unittest.TestCase):
    def test_python_syntax_and_internal_import_targets(self):
        for path in files():
            if path.suffix != '.py':
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    if node.module.startswith('ostg.'):
                        target = ROOT.joinpath(*node.module.split('.')[1:])
                        self.assertTrue(target.is_dir() or target.with_suffix('.py').is_file(),
                                        f'{path}: {node.module}')

    def test_markdown_file_links(self):
        for path in files():
            if path.suffix != '.md':
                continue
            for target in re.findall(r'!?\[[^\]\n]*\]\(([^\n)]+)\)', path.read_text()):
                target = target.strip('<>').split('#')[0]
                if not target or re.match(r'[a-zA-Z][\w+.-]*:', target):
                    continue
                target = re.sub(r':\d+(?:[-–]\d+)?$', '', target)
                if target.startswith('/') and not target.startswith(str(ROOT) + '/'):
                    continue  # external machine/artifact references
                self.assertTrue((path.parent / target).exists(), f'{path.relative_to(ROOT)} -> {target}')

    def test_moved_generation_and_data_helpers(self):
        gen = importlib.import_module('ostg.taskgen.generation.gen')
        self.assertTrue((gen.PROMPTS / 'single_json.txt').is_file())
        taxonomy = importlib.import_module('ostg.taskgen.generation.taxonomy')
        self.assertEqual(len(taxonomy.INTENTS), 5)
        self.assertEqual(len(taxonomy.DOMAINS), 13)
        traj = importlib.import_module('ostg.sft.data.traj')
        self.assertEqual(traj.think_est_tokens('<think>1234567</think>'), 2)
        convert = importlib.import_module('ostg.sft.data.to_swift').convert
        row = convert({'messages': [{'role': 'user', 'content': [{'type': 'image', 'path': 'x.png'}]}],
                       'response': 'answer', 'meta': {'domain': 'chrome'}})
        self.assertEqual(row['images'], ['x.png'])
        self.assertEqual(row['messages'][-1]['content'], 'answer')
        self.assertEqual(row['channel'], 'chrome')
        # Existing regression checks travel with their modules.
        filters = importlib.import_module('ostg.sft.tests.test_filters')
        filters.main()
        filters.test_whole_traj_reject()
        filters.test_think_est_tokens()
        importlib.import_module('ostg.sft.experiments.swe_mem.test_prepare_copy').main()

    def test_readme_tree(self):
        subprocess.run([sys.executable, 'scripts/update_readme_tree.py', '--check'], cwd=ROOT, check=True)

    def test_swift_conversion_contracts(self):
        canonical = importlib.import_module('ostg.sft.data.to_swift')
        legacy = importlib.import_module('ostg.sft.data.export')
        weighted = importlib.import_module('ostg.sft.experiments.swe_mem.prepare_copy')
        sample = {'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': 'Read '}, {'type': 'image', 'path': 'images/a.png'},
            {'type': 'image', 'path': '/absolute/b.png'}]}],
            'response': 'Answer\n\u7b54\u6848', 'meta': {'domain': 'chrome'}}
        untouched = copy.deepcopy(sample)
        expected = {'messages': [{'role': 'user', 'content': 'Read <image><image>'},
                                 {'role': 'assistant', 'content': 'Answer\n\u7b54\u6848'}],
                    'images': ['images/a.png', '/absolute/b.png'], 'channel': 'chrome'}
        self.assertEqual(canonical.convert(sample), expected)
        self.assertEqual(legacy.to_swift(sample), expected)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory).resolve()
            weighted_expected = copy.deepcopy(expected)
            weighted_expected['images'] = [str(source / 'images/a.png'), '/absolute/b.png']
            weighted_expected['messages'][-1]['loss_scale'] = 1.75
            self.assertEqual(weighted.to_swift(sample, source, 1.75), weighted_expected)
        self.assertEqual(sample, untouched)

        text_only = {'messages': [{'role': 'user', 'content': []}], 'response': 'done'}
        rows = [{'role': 'user', 'content': ''}, {'role': 'assistant', 'content': 'done'}]
        self.assertEqual(canonical.convert(text_only), {'messages': rows})
        self.assertEqual(legacy.to_swift(text_only),
                         {'messages': rows, 'images': [], 'channel': 'unknown'})
        text_only['meta'] = {'domain': ''}
        self.assertEqual(legacy.to_swift(text_only)['channel'], 'unknown')
        for sample, error in [({'response': 'done'}, KeyError),
                              ({'messages': [{'role': 'user', 'content': None}], 'response': 'done'}, TypeError),
                              ({'messages': [{'role': 'user', 'content': 'text'}], 'response': 'done'}, AttributeError)]:
            with self.assertRaises(error):
                legacy.to_swift(sample)
        plain = {'messages': [{'role': 'user', 'content': 'text'}], 'response': 'done'}
        self.assertEqual(weighted.to_swift(plain, Path('/tmp'), 0.5)['messages'],
                         [{'role': 'user', 'content': 'text'},
                          {'role': 'assistant', 'content': 'done', 'loss_scale': 0.5}])

    def test_swift_cli_output_bytes(self):
        canonical = importlib.import_module('ostg.sft.data.to_swift')
        legacy = importlib.import_module('ostg.sft.data.export')
        sample = {'messages': [], 'response': '\u4f60\u597d'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = '\n' + json.dumps(sample, ensure_ascii=False) + '\n\n'
            for name in ('samples.jsonl', 'val_samples.jsonl'):
                (root / name).write_text(source, encoding='utf-8')
            for module, args, expected in [
                (canonical, [directory], {'messages': [{'role': 'assistant', 'content': '\u4f60\u597d'}]}),
                (legacy, [directory, '--dialect', 'swift'],
                 {'messages': [{'role': 'assistant', 'content': '\u4f60\u597d'}], 'images': [], 'channel': 'unknown'})]:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(module.main(args), 0)
                for name in ('train_swift.jsonl', 'val_swift.jsonl'):
                    self.assertEqual((root / name).read_bytes(),
                                     (json.dumps(expected, ensure_ascii=False) + '\n').encode())
            self.assertEqual((root / 'samples.jsonl').read_text(), source)

    def test_generator_codecs_and_preserved_policy(self):
        gen = importlib.import_module('ostg.taskgen.generation.gen')
        shared = importlib.import_module('ostg.llm')
        self.assertEqual(gen._protocol({'model': 'Claude-test'}), 'anthropic')
        self.assertEqual(gen._protocol({'model': 'qwen-test'}), 'openai')
        self.assertEqual(gen._to_openai_messages(
            [{'role': 'user', 'content': [{'type': 'text', 'text': 'task'}]}],
            [{'type': 'text', 'text': 'system'}]),
            [{'role': 'system', 'content': 'system'}, {'role': 'user', 'content': 'task'}])
        response = {'choices': [{'message': {'reasoning': 'think', 'content': 'answer',
                     'tool_calls': [{'function': {'name': 'emit_task_specs', 'arguments': '{"specs": []}'}}]},
                     'finish_reason': 'tool_calls'}], 'usage': {'prompt_tokens': 3, 'completion_tokens': 4}}
        translated = gen._from_openai_response(response)
        self.assertEqual(translated['content'][0], {'type': 'thinking', 'thinking': 'think'})
        self.assertEqual(translated['usage'], {'input_tokens': 3, 'output_tokens': 4})
        self.assertEqual(gen.extract(translated), [])
        events = [{'choices': [{'delta': {'reasoning_content': 'think', 'content': 'answer',
                   'tool_calls': [{'index': 0, 'function': {'name': 'emit_task_specs', 'arguments': '{"specs":'}}]}}]},
                  {'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': ' []}'}}]},
                                'finish_reason': 'tool_calls'}], 'usage': response['usage']}]
        stream = [('data: ' + json.dumps(e) + '\n').encode() for e in events] + [b'data: [DONE]\n']
        self.assertEqual(gen._from_openai_response(gen._assemble_openai(stream)), translated)
        cfg = {'model': 'qwen-test', 'base': 'https://example.invalid', 'key': 'dummy',
               'max_tokens': 100, 'temperature': 0.3}
        with patch('urllib.request.urlopen') as request:
            request.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
            gen.call([], [], cfg)
            payload = json.loads(request.call_args.args[0].data)
            self.assertNotIn('temperature', payload)  # generator policy remains unchanged
            self.assertEqual(payload['tool_choice']['function']['name'], gen.TOOL)
        encoded = {'content': [{'type': 'tool_use', 'name': gen.TOOL, 'input': {'specs': '[{"x": 1}]'}}]}
        self.assertEqual(gen.extract(encoded), '[{"x": 1}]')
        self.assertEqual(shared.extract(encoded, gen.TOOL), [{'x': 1}])


if __name__ == '__main__':
    unittest.main()
