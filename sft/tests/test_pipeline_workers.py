"""Focused coverage for exact rendering, resume, bounded workers and producer ACKs."""
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import random
import statistics
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image
from sft.analysis import retention
from sft.analysis.attention_store import file_hash
from sft.analysis.attention_download import locked
from sft.analysis.visual_signals import read_json, write_json, digest
from sft.scripts.eval import after_task, cleanup_capture
from sft.tests.test_retention import binary_fixture
from sft.tests.test_visual_signals import fixture


class PipelineWorkerTests(unittest.TestCase):
    def test_quantization_matches_scalar_at_rounding_boundaries(self):
        rng = random.Random(19)
        examples = [[0.0]*10, [0,1], [(n+.5)/255 for n in range(255)]+[1],
                    [10**rng.uniform(-30,0) for _ in range(4096)]]
        with tempfile.TemporaryDirectory() as d:
            for i,values in enumerate(examples):
                maximum=max(values);positive=[v for v in values if v>0]
                pivot=statistics.median(positive) if positive else 1
                denominator=math.log1p(maximum/pivot) if maximum else 1
                expected=bytes(round(v/maximum*255) if maximum else 0 for v in values)
                expected+=bytes(round(math.log1p(v/pivot)/denominator*255) if maximum else 0 for v in values)
                summary={'frames':[{'weights':values}]}
                writer=retention.HeatmapWriter(Path(d),f'{i}.heat')
                writer(summary,[],[values]);path=writer.finish();ref=summary['render_ref']
                with Image.open(io.BytesIO(path.read_bytes()[ref['offset']:ref['offset']+ref['length']])) as image:
                    self.assertEqual(image.tobytes()[:len(expected)],expected)

    def test_buffered_json_preserves_exact_utf8_and_rejects_nan(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'data.json';value={'text':'中文\n</script>','values':[0,.1,1e-100]}
            retention.write_gzip_json(p,value)
            self.assertEqual(gzip.decompress(p.with_suffix('.json.gz').read_bytes()).decode(),
                             json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')))
            with self.assertRaises(ValueError):retention.write_gzip_json(p,{'bad':float('nan')})

    def test_decision_resume_skips_png_work_and_corrupt_cache_is_rebuilt(self):
        with tempfile.TemporaryDirectory() as d:
            root,task,raw,request,original,c=binary_fixture(Path(d));c['raw_retention']='delete-after-export'
            (task/'result.txt').unlink()  # A fully rendered but not finalized task.
            entries=after_task.render_task(task,task.parents[1],c)
            with patch.object(retention.HeatmapWriter,'__call__',side_effect=AssertionError('should reuse decision')):
                self.assertEqual(after_task.render_task(task,task.parents[1],c),entries)
            heat=next((Path(c['output_dir'])/'heatmaps').glob('*.heat'));heat.write_bytes(b'broken')
            after_task.render_task(task,task.parents[1],c)
            self.assertNotEqual(heat.read_bytes(),b'broken');self.assertTrue(raw.exists())
            (task/'result.txt').write_text('0.5')
            with patch.object(retention.HeatmapWriter,'__call__',side_effect=AssertionError('reuse before finalization')):
                after_task.render_task(task,task.parents[1],c)
            self.assertFalse(raw.exists())

    def test_resume_switch_and_input_changes_force_fresh_analysis(self):
        with tempfile.TemporaryDirectory() as d:
            root,task,raw,request,original,c=binary_fixture(Path(d));c['raw_retention']='delete-after-export'
            (task/'result.txt').unlink();after_task.render_task(task,task.parents[1],c)
            with patch.object(retention.HeatmapWriter,'__call__',side_effect=RuntimeError('fresh render')):
                with self.assertRaisesRegex(RuntimeError,'fresh render'):
                    after_task.render_task(task,task.parents[1],{**c,'resume_render':False})
            self.assertTrue(raw.exists())

    def test_two_export_processes_publish_all_tasks_and_do_not_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            root=fixture(Path(d)/'raw');out=Path(d)/'pages'
            c={'results_root':str(root),'output_dir':str(out),'source':'fixture','collection':'test','export_workers':2}
            for name in ['fixture-run-a','fixture-run-b']:
                after_task.queue_task(root/name/'chrome/fixture-task',root/name,c)
            report=after_task.process_pending(c)
            self.assertEqual(report['processed'],2);self.assertEqual(report['failed'],0)
            self.assertEqual(len(read_json(out/'index.json')['trajectories']),4)
            self.assertEqual(after_task.process_pending(c)['processed'],0)

    def test_same_task_export_lock_blocks_duplicate_and_stop_prevents_claim(self):
        with tempfile.TemporaryDirectory() as d:
            root=fixture(Path(d)/'raw');run=root/'fixture-run-a';task=run/'chrome/fixture-task';out=Path(d)/'pages'
            c={'results_root':str(root),'output_dir':str(out),'source':'fixture','collection':'test'}
            runid='run-'+digest(('fixture:'+str(run.resolve())).encode())[:32];key=digest((runid+':chrome/fixture-task').encode())[:32]
            with locked(out/'.task-locks'/(key+'.lock')):
                with self.assertRaises(after_task.RenderBusy):after_task.render_task(task,run,c,wait_for_lock=False)
            job=after_task.queue_task(task,run,c);stop=Path(d)/'stop';stop.touch()
            r=after_task._process_job((str(job),read_json(job),{**c,'_stop_path':str(stop)}))
            self.assertEqual(r['busy'],1);self.assertNotIn('processed_version',read_json(job))


class ProducerCleanupTests(unittest.TestCase):
    def request(self,spool):
        name='a'*64+'.rank0.attn';p=spool/name;p.write_bytes(b'raw attention')
        return p,{'version':1,'receipt_id':'b'*64,'artifacts':[{'name':name,'bytes':p.stat().st_size,'sha256':file_hash(p)}]}

    def test_producer_dry_run_delete_resume_and_keep_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p,r=self.request(root);meta=p.with_suffix('.jsonl');meta.write_text('retained producer metadata')
            unknown=root/('c'*64+'.rank0.attn');unknown.write_text('unattributed')
            self.assertEqual(cleanup_capture.cleanup_spool(root,r,min_age=0)['status'],'dry_run');self.assertTrue(p.exists())
            self.assertEqual(cleanup_capture.cleanup_spool(root,r,True,0)['status'],'deleted');self.assertFalse(p.exists())
            self.assertEqual(cleanup_capture.cleanup_spool(root,r,True,0)['status'],'deleted')
            self.assertTrue(meta.exists());self.assertTrue(unknown.exists())

    def test_mismatch_recent_file_and_symlink_are_not_deleted(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p,r=self.request(root)
            self.assertEqual(cleanup_capture.cleanup_spool(root,r,True,600)['status'],'deferred')
            p.write_bytes(b'changed')
            with self.assertRaises(ValueError):cleanup_capture.cleanup_spool(root,r,True,0)
            p.unlink();foreign=root/'foreign';foreign.write_text('keep');p.symlink_to(foreign)
            with self.assertRaises(ValueError):cleanup_capture.cleanup_spool(root,r,True,0)
            self.assertEqual(foreign.read_text(),'keep')
            r['artifacts'][0]['name']='../foreign'
            with self.assertRaises(ValueError):cleanup_capture.cleanup_spool(root,r,True,0)

    def test_verified_client_archive_is_required_and_producer_ack_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);root,task,raw,request,original,c=binary_fixture(base)
            name='a'*64+'.rank0.attn';new=raw.with_name(name);raw.rename(new)
            record=json.loads(original)
            for row in record['attention']:row['weights_ref']['path']='capture/attention/'+name
            write_json(request,record);(task/'visual_signals.jsonl').write_text(json.dumps(record)+'\n')
            downloads=task/'capture/downloads';downloads.mkdir()
            write_json(downloads/(name+'.json'),{'status':'complete','url':'http://producer/v1/cua-attention/'+name,'bytes':new.stat().st_size,'sha256':file_hash(new)})
            producer=base/'producer';producer.mkdir();remote=producer/name;remote.write_bytes(new.read_bytes())
            c.update(raw_retention='delete-after-export',producer_cleanup={'enabled':True,'checkpoint':'fixture-checkpoint',
                'command':[sys.executable,cleanup_capture.__file__,'--spool',str(producer),'--apply','--min-age-seconds','0']})
            self.assertEqual(cleanup_capture.sweep(c)['status'],'idle');self.assertTrue(remote.exists())
            entries=after_task.render_task(task,task.parents[1],c)
            self.assertEqual(cleanup_capture.sweep({**c,'raw_retention':'keep'})['status'],'disabled')
            result=cleanup_capture.sweep(c);self.assertEqual(result['status'],'deleted');self.assertFalse(remote.exists())
            self.assertEqual(cleanup_capture.sweep(c)['status'],'idle')
            out=Path(c['output_dir']);self.assertTrue((out/entries[0]['json']).exists());self.assertTrue(next((out/'heatmaps').glob('*.heat')).exists())


if __name__=='__main__':unittest.main()
