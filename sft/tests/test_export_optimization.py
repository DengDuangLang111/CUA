"""Numerical equivalence, early publication, lazy raw data and bounded browser cache."""
import copy
import json
import math
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from sft.analysis import attention_store
from sft.analysis.visual_signals import attention_analysis, read_json, write_json
from sft.scripts.eval import after_task
from sft.tests.test_visual_signals import fixture


class ExportOptimizationTests(unittest.TestCase):
    def test_binary_rows_decode_once_and_match_dense_reference(self):
        rng = random.Random(83)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            images = [dict(id='history', token_count=3, key_indices=[0, 2, 4]),
                      dict(id='current', token_count=2, key_indices=[1, 3])]
            record = dict(images=images, output_token_ids=list(range(20)), attention=[])
            dense = []
            for i in range(20):
                values = [rng.random() for _ in range(6+i)]
                total = sum(values)
                ref = attention_store.append_row(root/'weights.attn', [v/total for v in values])
                row = dict(layer=2, head=0, output_index=i, key_count=len(values),
                           weights_ref=dict(ref, path='weights.attn'))
                record['attention'].append(row)
                dense.append(attention_store.read_row(row, root))
            original = copy.deepcopy(record)
            with patch.object(attention_store, 'read_row', wraps=attention_store.read_row) as read:
                rows, means = attention_analysis(record, root)
                self.assertEqual(read.call_count, len(dense))
            self.assertEqual(record, original)
            expected_means = [[math.fsum(w[k] for w in dense)/len(dense) for k in im['key_indices']] for im in images]
            for actual, expected in zip(means[0]['frames'], expected_means):
                for a, e in zip(actual['weights'], expected):
                    self.assertAlmostEqual(a, e, delta=1e-12)
            for row, weights in zip(rows, dense):
                masses = [math.fsum(weights[k] for k in im['key_indices']) for im in images]
                for actual, im, mass in zip(row['frames'], images, masses):
                    self.assertAlmostEqual(actual['frame_share'], mass/sum(masses), delta=1e-12)
                    entropy = -math.fsum(weights[k]/mass*math.log(weights[k]/mass) for k in im['key_indices'])
                    self.assertAlmostEqual(actual['spatial_entropy_nats'], entropy, delta=1e-12)
            for invalid in ([float('nan'), 1], [float('inf'), 1], [-.1, 1.1]):
                ref = attention_store.append_row(root/'weights.attn', invalid)
                bad = dict(images=[], attention=[dict(layer=0,head=0,key_count=2,weights_ref=dict(ref,path='weights.attn'))])
                with self.assertRaises(ValueError): attention_analysis(bad, root)
            bad = copy.deepcopy(record);bad['images'][1]['key_indices']=[0, 3]
            with self.assertRaises(ValueError): attention_analysis(bad, root)

    def test_raw_details_are_separate_and_lossless(self):
        with tempfile.TemporaryDirectory() as directory:
            root=fixture(Path(directory)/'raw');task=root/'fixture-run-a/chrome/fixture-task'
            signal=read_json(task/'visual_signals.jsonl')
            signal.update(api_response={'original':'x'*100000}, input_token_ids=list(range(1000)),
                          request={'messages':[]})
            (task/'visual_signals.jsonl').write_text(json.dumps(signal)+'\n')
            output=Path(directory)/'pages';config=dict(results_root=str(root),output_dir=str(output),source='fixture')
            entries=after_task.render_task(task,root/'fixture-run-a',config)
            bundle=read_json(output/entries[0]['json'])
            frame=next(f for f in bundle['trace_steps'] if f.get('signals_url'))
            small=read_json(output/frame['signals_url']);raw=read_json(output/small['raw_details_url'])
            self.assertNotIn('api_response',small)
            self.assertNotIn('input_token_ids',small)
            self.assertEqual(small['input_token_count'],1000)
            self.assertEqual(raw,{k:signal[k] for k in ('api_response','input_token_ids','request')})
            self.assertLess((output/frame['signals_url']).stat().st_size,(output/small['raw_details_url']).stat().st_size)

    def test_new_task_preview_is_available_while_another_task_is_enriching(self):
        with tempfile.TemporaryDirectory() as directory:
            root=fixture(Path(directory)/'raw');output=Path(directory)/'pages'
            config=dict(results_root=str(root),output_dir=str(output),source='fixture')
            first=root/'fixture-run-a/chrome/fixture-task';second=root/'fixture-run-b/chrome/fixture-task'
            first_job=after_task.queue_task(first,first.parents[1],config)
            entered, release = threading.Event(), threading.Event()
            original=after_task.render_task
            failures=[]
            def render(*args,**kwargs):
                if kwargs.get('include_signals',True):
                    entered.set()
                    if not release.wait(15):raise RuntimeError('test timed out')
                    raise ValueError('synthetic enrichment failure')
                return original(*args,**kwargs)
            def work():
                try: after_task.process_pending(config)
                except Exception as exc: failures.append(exc)
            with patch.object(after_task,'render_task',side_effect=render):
                worker=threading.Thread(target=work);worker.start()
                try:
                    self.assertTrue(entered.wait(10))
                    after_task.queue_task(second,second.parents[1],config)
                    after_task.process_pending(config,previews_only=True)
                    index=read_json(output/'index.json')
                    self.assertEqual(len(index['trajectories']),4)  # Two episodes per fixture.
                    self.assertTrue(all(r['pipeline_validation']=='processing' for r in index['trajectories']))
                    self.assertTrue(all((output/r['html'].split('#')[0]).exists() for r in index['trajectories']))
                finally:
                    release.set();worker.join(15)
            self.assertFalse(worker.is_alive());self.assertEqual(failures,[])
            self.assertEqual(read_json(first_job)['status'],'failed')
            first_page=next(r for r in read_json(output/'index.json')['trajectories'] if r['run']==str(first.parents[1].resolve()))
            bundle=read_json(output/first_page['json'])
            self.assertEqual(bundle['validation']['status'],'failed')
            self.assertTrue(all(f['signal_status']=='failed' for f in bundle['trace_steps']))
            self.assertIn('synthetic enrichment failure',bundle['trace_steps'][0]['signal_reason'])

    @unittest.skipUnless(shutil.which('node'), 'Node is used only for browser logic checks')
    def test_browser_cache_deduplicates_requests_and_evicts_old_steps(self):
        html=(Path(after_task.__file__).parents[2]/'analysis/trajectory_viewer.html').read_text()
        source=html[html.index('async function rawSignal'):html.index('\nconst button=')]
        script='''const assert=require('node:assert/strict');let active=null,calls=0;
const current=()=>({frame:active});
const fetch=async url=>{calls++;return {ok:true,json:async()=>({url,api_response:'raw reply'})};};
'''+source+'''
(async()=>{
 const frames=[0,1,2,3].map(i=>({signals_url:'step-'+i}));active=frames[0];
 await Promise.all([fetchSignal(frames[0]),fetchSignal(frames[0])]);assert.equal(calls,1);
 active=frames[1];await fetchSignal(frames[1]);
 active=frames[2];await fetchSignal(frames[2]);
 assert.equal(signalCache.size,2);assert.equal(frames[0].signals,null);
 active=frames[0];await fetchSignal(frames[0]);assert.equal(calls,4);assert.equal(signalCache.size,2);
 const small={raw_details_url:'raw',images:[]};const all=await rawSignal(small);
 assert.equal(all.api_response,'raw reply');assert.equal(small.api_response,undefined);
 console.log('cache and raw details passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        p=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr)
        with tempfile.NamedTemporaryFile(suffix='.js',mode='w') as f:
            f.write(html.split('<script>')[-1].split('</script>')[0]);f.flush()
            p=subprocess.run(['node','--check',f.name],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)


if __name__=='__main__':unittest.main()
