"""Bounded-memory exports retain raw signals and isolate renderer allocation failure."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tracemalloc
import unittest

from sft.analysis.visual_signals import export_runs, read_json, signal_index, write_json
from sft.scripts.eval.after_task import render_task
from sft.scripts.eval import run_eval
from sft.tests.test_visual_signals import fixture


class ExportMemoryTests(unittest.TestCase):
    def test_signal_index_does_not_retain_full_trajectory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'signals.jsonl'
            record = json.dumps(dict(episode=0, step_num=1, request_id='request', payload='x' * 1024**2))
            with path.open('w') as stream:
                for _ in range(40):
                    stream.write(record + '\n')
            tracemalloc.start()
            rows = signal_index(path)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            self.assertEqual(len(rows), 40)
            self.assertLess(peak, 8 * 1024**2)
            self.assertTrue(all('payload' not in row for row in rows))
            with path.open('rb') as stream:
                stream.seek(rows[-1]['_offset'])
                self.assertEqual(json.loads(stream.readline())['payload'], 'x' * 1024**2)

    def test_streaming_json_is_atomic_and_avoids_a_whole_payload_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'output.json'
            value = ['x' * 1024**2] * 40
            tracemalloc.start()
            write_json(path, value)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            self.assertLess(peak, 8 * 1024**2)
            self.assertEqual(read_json(path), value)
            write_json(path, {'previous': True})
            with self.assertRaises(ValueError):
                write_json(path, {'invalid': float('nan')})
            self.assertEqual(read_json(path), {'previous': True})
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_external_step_files_preserve_all_signal_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fixture(Path(directory) / 'raw')
            task = root / 'fixture-run-a/chrome/fixture-task'
            expected = export_runs(root, ['fixture-run-a'], 'fixture', '/assets')
            output = Path(directory) / 'pages'
            entries = render_task(task, root / 'fixture-run-a', dict(results_root=str(root),
                output_dir=str(output), source='fixture', collection='test'))
            actual = read_json(output / entries[0]['json'])
            for before, after in zip(expected['trace_steps'], actual['trace_steps']):
                if before['signals']:
                    self.assertIsNone(after['signals'])
                    self.assertEqual(read_json(output / after['signals_url']), before['signals'])
            self.assertIn('signals_url', (output / entries[0]['html'].split('#')[0]).read_text())
            self.assertNotEqual(actual['validation']['status'], 'failed')

    def test_dead_process_is_reported_as_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / 'fixture'
            task = ('tasks', '001')
            plan = dict(run_id='fixture', assignments={'windows': [task]},
                        hosts={'windows': {'results_root': directory}})
            write_json(run / 'task-state' / (run_eval.task_key(task) + '.json'),
                       dict(task=task, status='running', process={'pid': 99999999}))
            state = run_eval.status(plan, 'windows')
            self.assertEqual(state['counts']['running'], 0)
            self.assertEqual(state['counts']['interrupted'], 1)

    @unittest.skipUnless(sys.platform == 'linux', 'RLIMIT_AS is enforced on the Linux evaluation hosts')
    def test_worker_memory_error_is_recorded_without_harming_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = dict(output_dir=str(root / 'pages'), results_root=str(root / 'raw'))
            write_json(root / 'config.json', config)
            pending = root / 'pages/pending/task.json'
            write_json(pending, dict(version='one', status='pending', config=config,
                task_dir=str(root / 'raw/task'), run_dir=str(root / 'raw'), example=None, runtime_args=None))
            code = '''from sft.scripts.eval import after_task
import sys
def allocate(*args, **kwargs):
    return bytearray(512 * 1024**2)
after_task.render_task = allocate
after_task.main(['process-pending', '--config', sys.argv[1], '--memory-limit-gib', '0.125'])
'''
            child = subprocess.run([sys.executable, '-c', code, str(root / 'config.json')],
                                   capture_output=True, text=True, timeout=20)
            self.assertEqual(child.returncode, 1, child.stderr)
            self.assertEqual(read_json(pending)['status'], 'failed')
            self.assertIn('MemoryError', read_json(pending)['error'])
            self.assertEqual(bytearray(1024)[0], 0)  # Parent remains usable.


if __name__ == '__main__':
    unittest.main()
