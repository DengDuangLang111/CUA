"""Capture must preserve execution, exact requests, retry identity and evaluator files."""
import base64
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from contextlib import contextmanager
import hashlib
import unittest
from unittest.mock import patch

from PIL import Image
from sft.analysis.capture import Recorder, ACTIVE, canonical, capture_check, reconstruct_request
from sft.analysis.visual_signals import attention_rows, export_runs, read_rows, validate_bundle, write_json
from sft.scripts.eval.after_task import process_pending, queue_task, render_task, wrap_task


def picture(color):
    out=io.BytesIO();Image.new('RGB',(64,32),color).save(out,format='PNG');return out.getvalue()


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.run=self.root/'run';self.task=self.run/'chrome'/'task';self.task.mkdir(parents=True)
        self.runtime={'result_dir':str(self.run),'model_path':'test-checkpoint'}
        write_json(self.run/'args.json',self.runtime)
        self.rec=Recorder(self.task,{},self.runtime)

    def tearDown(self):self.tmp.cleanup()

    def test_attention_download_streams_and_skips_sdk_omit_header_values(self):
        payload=b'compressed-attention-file';name='a'*64+'.rank0.attn';calls=[]
        class Response:
            def raise_for_status(self):pass
            def iter_bytes(self,size):yield payload[:4];yield payload[4:]
        class Http:
            @contextmanager
            def stream(self,method,url,**kwargs):
                calls.append((method,url,kwargs));yield Response()
        client=SimpleNamespace(base_url='http://localhost/v1/',_client=Http(),
                               default_headers={'Authorization':'Bearer test','omit':object()})
        backend={'attention_blobs':{name:{'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}},
                 'attention':[{'weights_ref':{'blob':name}}]}
        self.rec.download_attention(SimpleNamespace(_client=client),backend)
        self.assertEqual(calls[0][2]['headers'],{'Authorization':'Bearer test'})
        self.assertFalse(calls[0][2]['follow_redirects'])
        self.assertEqual((self.task/backend['attention'][0]['weights_ref']['path']).read_bytes(),payload)
        self.assertFalse(list((self.task/'capture/attention').glob('*.tmp')))

    def test_lossless_request_duplicate_images_and_retry(self):
        uri='data:image/png;base64,'+base64.b64encode(picture('red')).decode()
        request={'model':'m','messages':[{'role':'user','content':[{'type':'image_url','image_url':{'url':uri}},{'type':'image_url','image_url':{'url':uri}}]}]}
        a=self.rec.request(request);b=self.rec.request(request)
        self.assertEqual(reconstruct_request(a,self.task),request)
        self.assertEqual(len(a['images']),2)
        self.assertNotEqual(a['images'][0]['id'],a['images'][1]['id'])
        self.assertEqual(a['images'][0]['path'],a['images'][1]['path'])
        self.assertNotEqual(a['request_id'],b['request_id'])
        self.assertEqual(a['request_sha256'],b['request_sha256'])
        p=self.task/a['request']['messages'][0]['content'][0]['image_url']['url']['data_uri']
        p.write_text('data:image/png;base64,YmFk')
        with self.assertRaises(ValueError):reconstruct_request(a,self.task)

    def test_calls_return_unchanged_and_all_action_images_export(self):
        rec=self.rec;before=picture('red');after=picture('green');actual=self.task/'comparison.txt';actual.write_text('old')
        class Agent:
            def reset(self):return 'reset-result'
            def predict(self,instruction,obs):
                rec.request({'model':'m','messages':[{'role':'user','content':instruction}]})
                rec.last_request['api_response']={'usage':{'completion_tokens':3}}
                return ('<think>test</think>click',['click','DONE'])
        class Env:
            evaluator={'func':'equal','expected':'old'}
            def step(self,action):return ({'screenshot':after},0,action=='DONE',{'feedback':'ok'})
            def metric(self,a,e):return int(a==e)
            def result_getter(self,env,cfg):return str(actual)
            def expected_getter(self,env,cfg):return 'old'
            def evaluate(self):
                path=self.result_getter(self,{})
                score=self.metric(Path(path).read_text(),self.expected_getter(self,{}))
                capture_check('custom',actual=path,expected='old',result=score)
                return {'score':score,'details':['exact']}
        agent,env=Agent(),Env()
        with rec.attach(agent,env):
            self.assertEqual(agent.reset(),'reset-result')
            response,actions=agent.predict('click',{'screenshot':before})
            for action in actions:self.assertEqual(env.step(action)[1],0)
            result=env.evaluate();self.assertEqual(result,{'score':1,'details':['exact']})
        self.assertIsNone(ACTIVE.get())
        self.assertNotIn('predict',vars(agent));self.assertNotIn('metric',vars(env))
        actual.write_text('overwritten')
        events=[r for _,r in read_rows(self.task/'capture/events.jsonl')]
        getter=next(e for e in events if e.get('role')=='result_getter')
        self.assertEqual((self.task/getter['result']['path']).read_text(),'old')
        (self.task/'traj.jsonl').write_text(''.join(json.dumps({'step_num':1,'action':a,'response':response})+'\n' for a in actions))
        (self.task/'result.txt').write_text('1')
        bundle=export_runs(self.root,['run'],'test','/assets')
        frame=bundle['trace_steps'][0]
        self.assertEqual(len(frame['actions']),2)
        self.assertTrue(all(a['before'] and a['after'] for a in frame['actions']))
        self.assertEqual(frame['signal_status'],'matched')
        self.assertEqual(bundle['trace_catalog'][0]['evaluation']['actual_inputs_status'],'recorded')
        self.assertEqual(validate_bundle(bundle,self.task)['status'],'passed')
        image_path=next(Path(p) for p in bundle['assets'].values() if p.endswith('.png'))
        intact=image_path.read_bytes();image_path.write_bytes(b'not an image')
        self.assertEqual(validate_bundle(bundle,self.task)['status'],'failed')
        image_path.write_bytes(intact)
        self.assertTrue(any(p.endswith('.txt') for p in bundle['assets']))
        result=render_task(self.task,self.run,{'results_root':str(self.root),'output_dir':str(self.root.parent/(self.root.name+'-pages')),'source':'test'})
        self.assertEqual(len(result),1)
        import shutil;shutil.rmtree(self.root.parent/(self.root.name+'-pages'))

    def test_inference_exception_not_swallowed_and_http_hooks_restored(self):
        hooks={'request':[],'response':[]}
        resource=SimpleNamespace(_client=SimpleNamespace(_client=SimpleNamespace(event_hooks=hooks)))
        sentinel=RuntimeError('original')
        def fail(resource,**kwargs):raise sentinel
        with self.assertRaises(RuntimeError) as cm:self.rec.completion(fail,resource,{'messages':[]})
        self.assertIs(cm.exception,sentinel);self.assertEqual(hooks,{'request':[],'response':[]})
        events=[r for _,r in read_rows(self.task/'capture/events.jsonl')]
        self.assertEqual(events[-1]['type'],'request_error')

    def test_interventions_preserve_context_and_unselected_image(self):
        from sft.analysis.intervene import perturb
        uri='data:image/png;base64,'+base64.b64encode(picture('red')).decode()
        request={'model':'m','temperature':0.3,'messages':[{'role':'user','content':[
            {'type':'text','text':'unchanged'},
            {'type':'image_url','image_url':{'url':uri}},
            {'type':'image_url','image_url':{'url':uri}}]}]}
        changed=perturb(request,{'operation':'occlude','image_index':0,'box':[0,0,.5,1],'color':[0,0,0]})
        self.assertEqual(changed['temperature'],.3)
        self.assertEqual(changed['messages'][0]['content'][2],request['messages'][0]['content'][2])
        self.assertEqual(request['messages'][0]['content'][1]['image_url']['url'],uri)
        img=Image.open(io.BytesIO(base64.b64decode(changed['messages'][0]['content'][1]['image_url']['url'].split(',')[1])))
        self.assertEqual(img.getpixel((31,0)),(0,0,0));self.assertEqual(img.getpixel((32,0)),(255,0,0))
        self.assertEqual(len(perturb(request,{'operation':'remove','image_index':0})['messages'][0]['content']),2)
        with self.assertRaises(ValueError):perturb(request,{'operation':'blur','image_index':0,'box':[.8,0,.2,1]})

    def test_resuming_legacy_task_preserves_old_episode(self):
        task=self.run/'os'/'resumed';task.mkdir(parents=True)
        old={'step_num':1,'action':'WAIT','response':'old response'}
        (task/'traj.jsonl').write_text(json.dumps(old)+'\n')
        recorder=Recorder(task,{},self.runtime)
        self.assertEqual(recorder.episode,1)
        recorder.step=1;recorder.response='new response'
        recorder.trajectory(type='initial_state')
        recorder.trajectory(action='DONE')
        bundle=export_runs(self.root,['run'],'test','/assets',task_dirs={task})
        self.assertEqual([t['episode'] for t in bundle['trace_catalog']],[0,1])
        self.assertEqual([f['response'] for f in bundle['trace_steps']],['old response','new response'])
        (task/'traj.jsonl').write_text(json.dumps({**old,'response':'edited'})+'\n')
        with self.assertRaises(ValueError):export_runs(self.root,['run'],'test','/assets',task_dirs={task})

    def test_deferred_handoff_retries_processing_without_rerunning_eval(self):
        output=self.root/'output'
        config={'results_root':str(self.root),'output_dir':str(output),'source':'test'}
        config_path=self.root/'inspection.json';write_json(config_path,config)
        calls=[]
        def task(args,example_result_dir):calls.append('eval');return 17
        import os
        with patch.dict(os.environ,{'CUA_INSPECTION_CONFIG':str(config_path)}),patch('sft.scripts.eval.after_task.render_task',side_effect=AssertionError('must be deferred')):
            self.assertEqual(wrap_task(task)(SimpleNamespace(**self.runtime),str(self.task)),17)
        self.assertEqual(calls,['eval']);self.assertFalse((output/'index.html').exists())
        with patch('sft.scripts.eval.after_task.render_task',side_effect=OSError('processing only')):
            self.assertEqual(process_pending(config)['failed'],1)
        with patch('sft.scripts.eval.after_task.render_task',return_value=[{'pipeline_validation':'passed'}]) as renderer:
            self.assertEqual(process_pending(config)['processed'],0)
            self.assertEqual(process_pending(config,retry_failed=True)['processed'],1)
            self.assertEqual(process_pending(config)['processed'],0)
            self.assertEqual(renderer.call_count,2)  # Preview then full enrichment.
            self.assertFalse(renderer.call_args_list[0].kwargs["include_signals"])
            self.assertEqual(renderer.call_args_list[1].kwargs,{})
        self.assertEqual(calls,['eval'])

    def test_new_completion_is_not_lost_during_processing(self):
        config={'results_root':str(self.root),'output_dir':str(self.root/'output'),'source':'test'}
        path=queue_task(self.task,self.run,config)
        original=json.loads(path.read_text())['version']
        def render(*args, **kwargs):
            if not kwargs.get("include_signals", True):
                return []
            queue_task(self.task,self.run,config)
            return [{'pipeline_validation':'passed'}]
        with patch('sft.scripts.eval.after_task.render_task',side_effect=render):
            self.assertEqual(process_pending(config)['pending_newer_version'],1)
        current=json.loads(path.read_text())
        self.assertNotEqual(current['version'],original)
        self.assertEqual(current['status'],'pending')
        self.assertNotIn('processed_version',current)

    def test_incomplete_blob_is_replaced_with_verified_atomic_bytes(self):
        data=picture('yellow');info=self.rec.blob(data,'.png');path=self.task/info['path']
        path.write_bytes(data[:30])
        self.assertEqual(self.rec.blob(data,'.png'),info)
        self.assertEqual(path.read_bytes(),data)

    def test_attention_entropies_zero_and_single_image(self):
        record={'images':[{'id':'a','key_indices':[0,1],'token_count':2},{'id':'b','key_indices':[2,3],'token_count':2}],
                'attention':[{'key_count':5,'weights':[.1,.1,.1,.1,.6]}]}
        row=attention_rows(record)[0]
        self.assertAlmostEqual(row['image_mass'],.4)
        self.assertAlmostEqual(row['image_entropy_normalized'],1)
        self.assertAlmostEqual(row['frames'][0]['spatial_entropy_normalized'],1)
        record['attention'][0]['weights']=[0,0,0,0,1]
        self.assertIsNone(attention_rows(record)[0]['image_entropy_nats'])
        record['images']=record['images'][:1];record['attention'][0]['weights']=[.2,.2,0,0,.6]
        self.assertIsNone(attention_rows(record)[0]['image_entropy_normalized'])


if __name__=='__main__':unittest.main()
