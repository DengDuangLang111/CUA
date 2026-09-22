"""Real HTTP transfers: rollout does not wait, export does, and recovery is lossless."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sft.analysis import attention_download as downloads
from sft.analysis.capture import Recorder
from sft.analysis.visual_signals import read_json, write_json
from sft.scripts.eval.after_task import process_pending, queue_task, render_task
from sft.tests.test_retention import binary_fixture


class DownloadTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root, self.task, raw, self.request, original, self.config = binary_fixture(self.base)
        self.payload = raw.read_bytes()
        raw.unlink()
        self.name = 'a' * 64 + '.rank0.attn'
        self.raw = self.task / 'capture/attention' / self.name
        self.key = self.base / 'private-key'
        self.key.write_text('fixture-secret')
        self.queue = self.root / '.attention-downloads'
        self.calls = []
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                owner.calls.append(dict(path=self.path, range=self.headers.get('Range'), auth=self.headers.get('Authorization')))
                if self.headers.get('Authorization') != 'Bearer fixture-secret':
                    self.send_error(401)
                    return
                offset = int(self.headers['Range'].split('=')[1].split('-')[0]) if self.headers.get('Range') else 0
                self.send_response(206 if offset else 200)
                if offset:
                    self.send_header('Content-Range', f'bytes {offset}-{len(owner.payload)-1}/{len(owner.payload)}')
                self.send_header('Content-Length', str(len(owner.payload) - offset))
                self.end_headers()
                self.wfile.write(owner.payload[offset:])
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.url = f'http://127.0.0.1:{server.server_port}/v1'
        self.capture = dict(attention_download='background', key_file=str(self.key),
                            download_queue=str(self.queue), download_min_free_gib=0)
        self.config.update(capture=self.capture, raw_retention='delete-after-export')
        self.record = json.loads(original)
        for row in self.record['attention']:
            row['weights_ref']['blob'] = self.name
        self.backend = dict(attention_blobs={self.name: dict(bytes=len(self.payload), sha256=hashlib.sha256(self.payload).hexdigest())},
                            attention=self.record['attention'])

    def enqueue(self):
        downloads.enqueue(self.task, self.backend, self.url, self.capture)
        write_json(self.request, self.record)
        (self.task / 'visual_signals.jsonl').write_text(json.dumps(self.record) + '\n')
        queue_task(self.task, self.root / 'fixture-run-a', self.config)

    def test_response_returns_before_any_download_and_preserves_response(self):
        recorder = Recorder(self.task, self.capture, {'result_dir': str(self.root / 'fixture-run-a')})
        response = {'choices': [], 'cua_signals': copy.deepcopy(self.backend)}
        original = copy.deepcopy(response)
        resource = SimpleNamespace(_client=SimpleNamespace(base_url=self.url, _client=SimpleNamespace(event_hooks={})))
        with patch.object(recorder, 'download_attention') as sync:
            result = recorder.completion(lambda *a, **k: response, resource, {'model': 'fixture', 'messages': []})
        self.assertIs(result, response)
        self.assertEqual(response, original)
        sync.assert_not_called()
        self.assertFalse(self.raw.exists())
        self.assertEqual(self.calls, [])
        self.assertTrue(downloads.has_pending(self.queue, self.root))
        saved = ''.join(p.read_text() for p in (self.task / 'capture/downloads').glob('*.json'))
        self.assertNotIn('fixture-secret', saved)
        self.assertFalse(hasattr(recorder, 'requests'))  # No full-history copies held in RAM.

    def test_export_waits_then_renders_and_cleans_up_without_rerunning_model(self):
        self.enqueue()
        before = (self.task / 'result.txt').read_bytes()
        with self.assertRaises(downloads.DownloadPending):
            render_task(self.task, self.root / 'fixture-run-a', self.config)
        report = process_pending(self.config)
        self.assertEqual(report['failed'], 0)
        job = read_json(next((Path(self.config['output_dir']) / 'pending').glob('*.json')))
        self.assertEqual(job['status'], 'waiting_for_attention')
        self.assertNotIn('processed_version', job)
        self.assertTrue(self.request.exists())
        self.assertTrue(downloads.download_one(self.queue, self.root))
        self.assertEqual(self.raw.read_bytes(), self.payload)
        self.assertFalse(downloads.has_pending(self.queue, self.root))
        report = process_pending(self.config)
        self.assertEqual(report['processed'], 1)
        self.assertEqual(report['invalid'], 0)
        self.assertFalse(self.raw.exists())
        self.assertEqual((self.task / 'result.txt').read_bytes(), before)
        entries = render_task(self.task, self.root / 'fixture-run-a', self.config)
        self.assertTrue(entries)  # Re-render after deletion uses the archive.

    def test_range_resume_and_already_verified_file_do_not_redownload(self):
        self.enqueue()
        cut = len(self.payload) // 2
        self.raw.with_suffix('.tmp').write_bytes(self.payload[:cut])
        downloads.download_one(self.queue, self.root)
        self.assertEqual(self.calls[0]['range'], f'bytes={cut}-')
        self.assertEqual(self.raw.read_bytes(), self.payload)
        self.raw.with_suffix('.tmp').write_bytes(b'stale')
        downloads.fetch_blob(downloads.url_stream, self.url + '/unused', {}, self.raw, self.backend['attention_blobs'][self.name])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.raw.read_bytes(), self.payload)
        self.assertFalse(self.raw.with_suffix('.tmp').exists())

    def test_bad_hash_has_bounded_retries_and_preserves_raw_records_until_recovery(self):
        self.enqueue()
        original = self.payload
        self.payload = b'x' * len(self.payload)
        with patch.object(downloads.time, 'sleep'):
            downloads.download_one(self.queue, self.root)
        self.assertEqual(len(self.calls), 3)
        self.assertFalse(self.raw.exists())
        self.assertFalse(downloads.has_pending(self.queue, self.root))
        self.assertFalse(downloads.download_one(self.queue, self.root))
        report = process_pending(self.config)
        self.assertEqual(report['failed'], 1)
        self.assertTrue(self.request.exists())
        self.assertTrue((self.task / 'visual_signals.jsonl').exists())
        self.payload = original
        downloads.retry_failed(self.queue, self.root)
        downloads.download_one(self.queue, self.root)
        report = process_pending(self.config, retry_failed=True)
        self.assertEqual(report['processed'], 1)
        self.assertEqual(report['invalid'], 0)

    def test_global_lock_prevents_duplicate_download_workers(self):
        self.enqueue()
        with downloads.locked(self.queue / '.worker.lock') as held:
            self.assertTrue(held)
            self.assertFalse(downloads.download_one(self.queue, self.root))
        self.assertEqual(self.calls, [])
        self.assertTrue(downloads.download_one(self.queue, self.root))

    def test_worker_cli_finishes_transfer_and_final_export_before_exit(self):
        self.enqueue()
        config = self.base / 'inspection.json'
        write_json(config, self.config)
        script = Path(__file__).resolve().parents[1] / 'scripts/eval/after_task.py'
        result = subprocess.run([sys.executable, str(script), 'process-pending', '--config', str(config)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        job = read_json(next((Path(self.config['output_dir']) / 'pending').glob('*.json')))
        self.assertEqual(job['status'], 'processed')
        self.assertFalse(self.raw.exists())

    def test_two_slots_overlap_distinct_transfers_without_duplicating_a_file(self):
        self.enqueue()
        other = self.root / 'fixture-run-a/chrome/other-task'
        other.mkdir()
        downloads.enqueue(other, copy.deepcopy(self.backend), self.url, self.capture)
        barrier = threading.Barrier(2)
        original = downloads.fetch_blob
        def transfer(*args, **kwargs):
            barrier.wait(timeout=5)
            return original(*args, **kwargs)
        results = []
        with patch.object(downloads, 'fetch_blob', side_effect=transfer):
            threads = [threading.Thread(target=lambda n=n: results.append(downloads.download_one(self.queue, self.root, n))) for n in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(8)
        self.assertEqual(results, [True, True])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual((other/'capture/attention'/self.name).read_bytes(), self.payload)
        self.assertFalse(downloads.has_pending(self.queue, self.root))

    def test_file_lock_and_cancellation_preserve_resume_state(self):
        self.enqueue()
        job = next((self.task/'capture/downloads').glob('*.json'))
        with downloads.locked(job.with_suffix('.download.lock')):
            self.assertFalse(downloads.download_one(self.queue, self.root, 1))
        stop = threading.Event(); stop.set()
        self.assertTrue(downloads.download_one(self.queue, self.root, 1, stop=stop))
        self.assertEqual(read_json(job)['status'], 'pending')
        self.assertEqual(self.calls, [])
        stop.clear(); downloads.download_one(self.queue, self.root, 1, stop=stop)
        self.assertEqual(self.raw.read_bytes(), self.payload)


if __name__ == '__main__':
    unittest.main()
