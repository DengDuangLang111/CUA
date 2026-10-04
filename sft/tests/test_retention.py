"""Cleanup is opt-in, loss is explicit, and verified pictures survive raw deletion."""
import copy
import gzip
import io
import json
import math
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch

from PIL import Image
from sft.analysis.attention_store import append_row, file_hash
from sft.analysis import retention
from sft.analysis.visual_signals import export_runs, read_json, write_json
from sft.analysis.trajectory_viewer import viewer_server
from sft.scripts.eval.after_task import render_task
from sft.tests.test_visual_signals import fixture


def binary_fixture(base):
    root = fixture(base/'raw');task=root/'fixture-run-a/chrome/fixture-task'
    record=read_json(task/'visual_signals.jsonl');folder=task/'capture/attention';folder.mkdir(parents=True)
    raw=folder/'fixture.attn'
    for row in record['attention']:
        row['weights_ref']={**append_row(raw,row.pop('weights')),'path':'capture/attention/fixture.attn'}
    for row in record['attention']:row['weights_ref']['sha256']=file_hash(raw)
    request=task/'capture/requests'/f"{record['request_id']}.json";request.parent.mkdir();write_json(request,record)
    original=json.dumps(record)+'\n';(task/'visual_signals.jsonl').write_text(original)
    config=dict(results_root=str(root),output_dir=str(base/'pages'),source='fixture',collection='test')
    return root,task,raw,request,original,config


class RetentionTests(unittest.TestCase):
    def test_default_keep_and_unknown_policy(self):
        with tempfile.TemporaryDirectory() as d:
            root,task,raw,request,original,c=binary_fixture(Path(d))
            render_task(task,root/'fixture-run-a',c)
            self.assertTrue(raw.exists());self.assertTrue(request.exists())
            self.assertEqual((task/'visual_signals.jsonl').read_text(),original)
            with self.assertRaisesRegex(ValueError,'Unknown raw_retention'):
                render_task(task,root/'fixture-run-a',{**c,'raw_retention':'typo'})

    def test_all_rendered_rows_raw_text_statistics_and_http_survive_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            root,task,raw,request,original,c=binary_fixture(Path(d));c['raw_retention']='delete-after-export'
            before=export_runs(root,['fixture-run-a'],'fixture','/assets')
            expected=next(f['signals'] for f in before['trace_steps'] if f['signals'])
            score=(task/'result.txt').read_bytes()
            entries=render_task(task,root/'fixture-run-a',c);out=Path(c['output_dir'])
            self.assertFalse(raw.exists());self.assertFalse(request.exists());self.assertFalse((task/'visual_signals.jsonl').exists())
            self.assertEqual((task/'result.txt').read_bytes(),score);self.assertTrue((task/'initial.png').exists())
            bundle=read_json(out/entries[0]['json']);frame=next(f for f in bundle['trace_steps'] if f.get('signals_url'))
            stored=read_json(out/frame['signals_url']);ref=stored['raw_details_ref']
            self.assertEqual(retention.read_archive_record(out,ref),json.loads(original))
            with gzip.open(out/ref['src'],'rt') as stream:self.assertEqual(stream.read(),original)
            self.assertEqual(stored['attention_overviews'],expected['attention_overviews'])
            self.assertEqual(len(stored['attention']),len(expected['attention']))
            for a,b in zip(stored['attention'],expected['attention']):
                for name in ('weights_sum','image_mass','image_entropy_nats','image_entropy_normalized','frames'):
                    self.assertEqual(a[name],b[name])
                self.assertNotIn('weights_ref',a)
                r=a['render_ref']
                with (out/r['src']).open('rb') as f:f.seek(r['offset']);png=f.read(r['length'])
                with Image.open(io.BytesIO(png)) as image:
                    self.assertEqual(image.mode,'L');pixels=list(image.tobytes());self.assertGreaterEqual(len(pixels),2*r['value_count'])
            first=stored['attention'][0];rr=first['render_ref']
            with (out/rr['src']).open('rb') as f:f.seek(rr['offset']);image=Image.open(io.BytesIO(f.read(rr['length'])));pixels=list(image.tobytes())
            self.assertEqual(pixels[:6],[128,255,64,64,128,128])
            self.assertEqual(render_task(task,root/'fixture-run-a',c),entries)  # Resume uses verified retained outputs.
            server=viewer_server(out,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();url=f'http://127.0.0.1:{server.server_port}/'
            try:
                with urllib.request.urlopen(url+frame['signals_url']) as response:
                    self.assertEqual(response.headers['Content-Encoding'],'gzip')
                    self.assertEqual(json.loads(gzip.decompress(response.read())),stored)
                for r in (ref,first['render_ref']):
                    req=urllib.request.Request(url+r['src'],headers={'Range':f"bytes={r['offset']}-{r['offset']+r['length']-1}"})
                    with urllib.request.urlopen(req) as response:self.assertEqual(response.status,206);self.assertEqual(len(response.read()),r['length'])
                from sft.analysis.trajectory_catalog import catalog_server
                cfg=Path(d)/'catalog.json'
                write_json(cfg,{'sources':[{'id':'fixture','label':'fixture','url':url.rstrip('/'),'collection':'test'}]})
                catalog=catalog_server(cfg,0);ct=threading.Thread(target=catalog.serve_forever,daemon=True);ct.start()
                try:
                    proxy=f'http://127.0.0.1:{catalog.server_port}/sources/fixture/'
                    with urllib.request.urlopen(proxy+frame['signals_url']) as response:
                        self.assertEqual(response.headers['Content-Encoding'],'gzip')
                        self.assertEqual(json.loads(gzip.decompress(response.read())),stored)
                    for r in (ref,first['render_ref']):
                        req=urllib.request.Request(proxy+r['src'],headers={'Range':f"bytes={r['offset']}-{r['offset']+r['length']-1}"})
                        with urllib.request.urlopen(req) as response:self.assertEqual(response.status,206);self.assertEqual(len(response.read()),r['length'])
                finally:catalog.shutdown();catalog.server_close();ct.join()
            finally:server.shutdown();server.server_close();thread.join()

    def test_render_failure_or_missing_final_score_keeps_sources(self):
        with tempfile.TemporaryDirectory() as d:
            root,task,raw,request,original,c=binary_fixture(Path(d));c['raw_retention']='delete-after-export'
            with patch.object(retention.HeatmapWriter,'finish',side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):render_task(task,root/'fixture-run-a',c)
            self.assertTrue(raw.exists());self.assertTrue(request.exists());self.assertTrue((task/'visual_signals.jsonl').exists())
            (task/'result.txt').unlink();render_task(task,root/'fixture-run-a',c)
            self.assertTrue(raw.exists());self.assertTrue(request.exists())

    def test_missing_archive_or_changed_task_prevents_deletion(self):
        with tempfile.TemporaryDirectory() as d:
            root,task,raw,request,original,c=binary_fixture(Path(d));c['raw_retention']='delete-after-export'
            with patch.object(retention,'finish_cleanup',return_value=None):render_task(task,root/'fixture-run-a',c)
            out=Path(c['output_dir']);receipt=next((out/'retention').glob('*.json'));key=receipt.stem
            archive=next((out/'archives').glob('*.gz'));saved=archive.read_bytes();archive.write_bytes(b'corrupt')
            with self.assertRaises(ValueError):retention.finish_cleanup(task,out,key)
            self.assertTrue(raw.exists());self.assertTrue(request.exists())
            archive.write_bytes(saved);(task/'traj.jsonl').write_text((task/'traj.jsonl').read_text()+'\n')
            with self.assertRaisesRegex(ValueError,'Task changed'):retention.finish_cleanup(task,out,key)
            self.assertTrue(raw.exists())

    def test_ready_cleanup_can_resume_after_partial_unlink_and_keep_cancels_pending_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            root,task,raw,request,original,c=binary_fixture(Path(d));c['raw_retention']='delete-after-export'
            with patch.object(retention,'finish_cleanup',return_value=None):
                entries=render_task(task,root/'fixture-run-a',c)
            out=Path(c['output_dir']);receipt=next((out/'retention').glob('*.json'))
            render_task(task,root/'fixture-run-a',{**c,'raw_retention':'keep'})
            self.assertTrue(raw.exists())
            raw.unlink()  # Simulate a crash after one verified raw file was removed.
            self.assertEqual(retention.finish_cleanup(task,out,receipt.stem),entries)
            self.assertFalse(request.exists());self.assertEqual(read_json(receipt)['status'],'deleted')

    def test_duplicate_wire_response_and_unused_video_are_removed(self):
        with tempfile.TemporaryDirectory() as d:
            root,task,raw,request,original,c=binary_fixture(Path(d));c['raw_retention']='delete-after-export'
            wire=task/'capture/assets/wire.response.json';wire.parent.mkdir(parents=True)
            write_json(wire,{'id':'reply','choices':[]})
            r=json.loads(original);r['api_response']={'id':'reply','choices':[],'usage':None}
            r['transport_attempts']=[{'status':200,'body':{'path':'capture/assets/wire.response.json','sha256':file_hash(wire)}}]
            (task/'visual_signals.jsonl').write_text(json.dumps(r)+'\n');write_json(request,r)
            video=task/'recording.mp4';video.write_bytes(b'unreferenced fixture video')
            entries=render_task(task,root/'fixture-run-a',c)
            self.assertFalse(wire.exists());self.assertFalse(video.exists())
            out=Path(c['output_dir']);bundle=read_json(out/entries[0]['json']);frame=next(f for f in bundle['trace_steps'] if f.get('signals_url'))
            signal=read_json(out/frame['signals_url'])
            self.assertNotIn('body',signal['transport_attempts'][0])
            self.assertEqual(retention.read_archive_record(out,signal['raw_details_ref'])['api_response'],r['api_response'])

    def test_unmatched_attention_and_foreign_candidates_cannot_be_deleted(self):
        with tempfile.TemporaryDirectory() as d:
            root,task,raw,request,original,c=binary_fixture(Path(d));c['raw_retention']='delete-after-export'
            r=json.loads(original);r['request_sha256']='mismatch';(task/'visual_signals.jsonl').write_text(json.dumps(r)+'\n')
            with self.assertRaisesRegex(ValueError,'Not every captured'):render_task(task,root/'fixture-run-a',c)
            self.assertTrue(raw.exists())
            (task/'visual_signals.jsonl').write_text(original)
            with patch.object(retention,'finish_cleanup',return_value=None):render_task(task,root/'fixture-run-a',c)
            out=Path(c['output_dir']);receipt=next((out/'retention').glob('*.json'));data=read_json(receipt)
            foreign=Path(d)/'unrelated.attn';foreign.write_text('keep')
            data['sources'][str(foreign)]={'sha256':file_hash(foreign),'size':4};write_json(receipt,data)
            with self.assertRaisesRegex(ValueError,'authorized raw paths'):retention.finish_cleanup(task,out,receipt.stem)
            self.assertEqual(foreign.read_text(),'keep');self.assertTrue(raw.exists())


if __name__=='__main__':unittest.main()
