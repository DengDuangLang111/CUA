"""Focused synthetic checks; no GPU/evaluation/API calls. HTTP tests use loopback."""
import copy
import json
import os
from pathlib import Path
import runpy
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zlib
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sft.analysis.visual_signals import asset_server, attention_overviews, attention_rows, digest, export_runs, merge_snapshot, mouse_marks, write_json
from sft.scripts.eval.after_task import install_hook, refresh_index, refresh_outputs, refresh_pages, render_run, render_task, wrap_task
from sft.analysis.trajectory_viewer import action_graph, add_graphs, index_html, task_html, viewer_server


def png(path, width, height, split=None):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    pixels = b''.join(b'\x00' + b''.join(bytes((220, 220, 220)) if x < (width//2 if split is None else split) else bytes((80, 80, 80))
                                        for x in range(width)) for _ in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB',width,height,8,2,0,0,0))
                     + chunk(b'IDAT',zlib.compress(pixels)) + chunk(b'IEND',b''))


def fixture(root):
    response = '<think>Inspect the two synthetic frames.</think>\nfixture action'
    for run_name in ('fixture-run-a','fixture-run-b'):
        task = root/run_name/'chrome'/'fixture-task'
        task.mkdir(parents=True)
        for name in ('initial.png','after1.png','after2.png'):
            png(task/name,800,450)
        write_json(root/run_name/'args.json', dict(arm='mixbtf9b',image_max=10,fold_size=1,model_path='fixture-checkpoint'))
        write_json(root/run_name/'version.json', dict(classification='synthetic fixture; not an evaluation'))
        write_json(task/'task.json', dict(instruction='SYNTHETIC FIXTURE — action alignment and visual-signal validation; not a model evaluation.',domain='chrome'))
        identity=dict(request_id='fixture-request-2',request_sha256='fixture-request-hash')
        rows=[dict(type='initial_state',step_num=0,screenshot_file='initial.png'),
              dict(step_num=1,action='pyautogui.moveTo(400, 225)',response='first decision',screenshot_file='after1.png',app='chrome'),
              dict(step_num=1,action='pyautogui.click(400, 225)',response='first decision',screenshot_file='after2.png',app='chrome'),
              dict(step_num=2,action='pyautogui.dragTo(600, 250)',response=response,screenshot_file='after1.png',**identity),
              dict(step_num=2,action='pyautogui.press("enter")',response=response,screenshot_file='after2.png',**identity),
              dict(type='initial_state',step_num=0,screenshot_file='initial.png'),
              dict(step_num=1,action='WAIT',response='restarted episode',screenshot_file='after1.png')]
        (task/'traj.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        (task/'result.txt').write_text('0.5')
        signal=dict(episode=0,step_num=2,checkpoint='fixture-checkpoint',response_sha256=digest(response.encode()),
                    origin='synthetic_fixture',**identity,counts={'vision':{'value':6,'kind':'exact fixture count'}},
                    output_tokens=[{'token':'click','logprob':-0.7}], images=[
          dict(id='history-0',path='initial.png',source_step=0,sha256=digest((task/'initial.png').read_bytes()),
               key_indices=[0,1],token_count=2,patch_boxes=[[0,0,.5,1],[.5,0,1,1]]),
          dict(id='current-1',path='after2.png',source_step=1,sha256=digest((task/'after2.png').read_bytes()),
               key_indices=[2,3,4,5],token_count=4,patch_boxes=[[0,0,.5,.5],[.5,0,1,.5],[0,.5,.5,1],[.5,.5,1,1]])],
          attention=[dict(layer=0,head=1,query=8,key_count=8,dtype='float32',weights=[.1,.2,.05,.05,.1,.1,.2,.2]),
                     dict(layer=1,head=0,query=9,key_count=8,dtype='float32',weights=[0,0,0,0,0,0,.5,.5])])
        (task/'visual_signals.jsonl').write_text(json.dumps(signal)+'\n')
    return root


def loop_fixture(root):
    """A clearly synthetic, reproducible loop example for the standalone UI."""
    fixture(root)
    run=root/'loop-demo';task=run/'chrome/loop-task'
    shutil.copytree(root/'fixture-run-a',run)
    (run/'chrome/fixture-task').rename(task)
    for name,split in [('initial.png',250),('after1.png',400),('after2.png',550)]:
        png(task/name,800,450,split)
    write_json(task/'task.json',dict(instruction='合成测试轨迹：点击条目，返回后重试同一位置，再输入筛选词。用于验证回边、自环和逐次原始证据；不是真实模型评测。',domain='chrome'))
    original=json.loads((task/'visual_signals.jsonl').read_text())
    commands=['pyautogui.moveTo(400, 225)','pyautogui.click(400, 225)',
              'pyautogui.press("esc")','pyautogui.click(400, 225)',
              'pyautogui.press("esc")','pyautogui.click(400, 225)',
              'pyautogui.click(400, 225)','pyautogui.typewrite("report")','DONE']
    rows=[dict(type='initial_state',step_num=0,screenshot_file='initial.png')];signals=[]
    pictures=['after1.png','after2.png','initial.png','after1.png','initial.png','after2.png','after2.png','after1.png','after1.png']
    for i,(command,picture) in enumerate(zip(commands,pictures),1):
        before=rows[-1]['screenshot_file']
        response=f'<think>[Synthetic record {i}] Inspect the current screen before executing action {i}. This visit retains its own observation and reasoning.</think>\n<tool_call>{command}</tool_call>'
        identity=dict(request_id=f'fixture-request-{i}',request_sha256=digest(f'fixture input {i}'.encode()))
        rows.append(dict(step_num=i,action=command,response=response,screenshot_file=picture,app='chrome',
                         action_timestamp=f'20260915@0336{i:02d}',reward=0,done=command=='DONE',info={},**identity))
        record=copy.deepcopy(original);record.update(step_num=i,response_sha256=digest(response.encode()),**identity)
        record['images'][0]['sha256']=digest((task/'initial.png').read_bytes())
        record['images'][1].update(path=before,sha256=digest((task/before).read_bytes()),source_step=i-1)
        record['output_tokens']=[{'token':command.split('(')[0],'logprob':-.1*i}]
        signals.append(record)
    (task/'traj.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    (task/'visual_signals.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in signals))
    return root


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=fixture(Path(self.temp.name))

    def export(self, runs=None):
        return export_runs(self.root,runs or ['fixture-run-a'],'fixture','http://127.0.0.1:8788')

    def test_episodes_actions_and_read_only_inputs(self):
        before={str(p):digest(p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}
        out=self.export()
        self.assertEqual([c['actionCount'] for c in out['trace_catalog']],[4,1])
        self.assertEqual([s['step'] for s in out['trace_steps']],[1,2,1])
        self.assertEqual([c['score'] for c in out['trace_catalog']],[None,.5])
        first=out['trace_steps'][0]
        self.assertEqual(first['actions'][0]['after'],first['actions'][1]['before'])
        self.assertEqual(first['actions'][0]['width'],800)
        self.assertEqual(out['trace_steps'][1]['actions'][0]['markers'][0]['fromX'],400)
        self.assertIsNone(out['trace_steps'][1]['actions'][0]['app'])
        self.assertEqual(before,{str(p):digest(p.read_bytes()) for p in self.root.rglob('*') if p.is_file()})

    def test_separate_initial_image_is_used_without_inserting_a_fake_log_row(self):
        task=self.root/'fixture-run-a/chrome/fixture-task'
        shutil.copy2(task/'initial.png',task/'initial_state.png')
        rows=[json.loads(line) for line in (task/'traj.jsonl').read_text().splitlines()][1:5]
        (task/'traj.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
        output=self.export()
        first=output['trace_steps'][0]['actions'][0]
        self.assertTrue(first['before'].endswith('initial_state.png'))
        self.assertEqual(first['row_number'],1)
        self.assertEqual(first['width'],800)

    def test_bulk_backfill_verifies_panel_and_renders_every_task(self):
        output=self.root.parent/(self.root.name+'-bulk')
        self.addCleanup(shutil.rmtree,output,True)
        run=self.root/'fixture-run-a'
        shutil.copytree(run/'chrome/fixture-task',run/'chrome/second-task')
        panel=self.root/'panel.json';write_json(panel,{'chrome':['fixture-task','second-task']})
        config=dict(results_root=str(self.root),output_dir=str(output),source='fixture')
        report=render_run(run,config,panel=panel,expected_tasks=2)
        self.assertEqual(report['rendered'],2)
        self.assertEqual(report['errors'],[])
        self.assertEqual(len(list(output.glob('task-*.html'))),2)
        with self.assertRaisesRegex(ValueError,'Expected 100'):
            render_run(run,config,panel=panel,expected_tasks=100)

    def test_same_name_runs_stay_separate_and_rebuild_is_idempotent(self):
        out=self.export(['fixture-run-a','fixture-run-b'])
        self.assertEqual(len({r['id'] for r in out['runs']}),2)
        self.assertEqual({r['canonical_name'] for r in out['runs']},{'9b-full-mixbtf'})
        self.assertEqual({r['corpus_formula'] for r in out['runs']},{'v11n+v16.tf'})
        snapshot={'queries':{'trace_catalog':{'rows':[{'id':'legacy'}],'source':{}},'trace_steps':{'rows':[],'source':{}}}}
        merged=merge_snapshot(snapshot,out)
        expected=copy.deepcopy(merged)
        self.assertEqual(merge_snapshot(merged,out),expected)
        self.assertEqual(len(merged['queries']['trace_catalog']['rows']),5)

    def test_attention_mass_counts_zero_and_no_second_softmax(self):
        frame=self.export()['trace_steps'][1]
        self.assertEqual(frame['signal_status'],'matched')
        signal=frame['signals']
        row=signal['attention'][0]
        self.assertAlmostEqual(row['image_mass'],.6)
        self.assertAlmostEqual(row['frames'][0]['frame_share'],.5)
        self.assertAlmostEqual(row['frames'][0]['mean_weight'],.15)
        self.assertAlmostEqual(row['frames'][1]['mean_weight'],.075)
        self.assertIsNone(signal['attention'][1]['frames'][0]['frame_share'])
        self.assertEqual(row['weights'],[.1,.2,.05,.05,.1,.1,.2,.2])
        self.assertNotIn('output_entropy',signal)
        self.assertEqual(len(frame['actions']),2)

    def test_bad_alignment_never_displays_another_decisions_attention(self):
        p=self.root/'fixture-run-a/chrome/fixture-task/visual_signals.jsonl'
        original=p.read_text()
        for field in ('checkpoint','request_id','request_sha256','response_sha256'):
            record=json.loads(original);record[field]='wrong'
            p.write_text(json.dumps(record)+'\n')
            frame=self.export()['trace_steps'][1]
            self.assertEqual(frame['signal_status'],'unverified')
            self.assertIsNone(frame['signals'])
        p.unlink()
        self.assertTrue(all(s['signal_status']=='unavailable' for s in self.export()['trace_steps']))

    def test_overview_averages_raw_image_weights_before_shares_and_entropy(self):
        signal=dict(output_token_ids=[7,8], images=[
            dict(id='history',key_indices=[0],token_count=1),
            dict(id='current',key_indices=[2],token_count=1)], attention=[
            dict(layer=23,head=0,output_index=0,key_count=3,weights=[.6,.2,.2]),
            dict(layer=23,head=0,output_index=1,key_count=4,weights=[0,.2,.2,.6])])
        original=copy.deepcopy(signal)
        row=attention_overviews(signal)[0]
        self.assertTrue(row['complete'])
        self.assertEqual(row['output_indices'],[0,1])
        self.assertEqual(row['frames'][0]['weights'],[.3])
        self.assertEqual(row['frames'][1]['weights'],[.2])
        self.assertAlmostEqual(row['image_mass'],.5)
        # Mean of normalized shares would incorrectly give .375, instead of .6.
        self.assertAlmostEqual(row['frames'][0]['frame_share'],.6)
        import math
        self.assertAlmostEqual(row['image_entropy_nats'],-.6*math.log(.6)-.4*math.log(.4))
        self.assertEqual(signal,original)
        self.assertNotIn('query',row)
        self.assertNotIn('key_count',row)

    def test_overview_separates_heads_and_marks_incomplete_or_ambiguous_positions(self):
        signal=dict(output_token_ids=[7,8,9],images=[dict(id='image',key_indices=[0,1],token_count=2)],attention=[
            dict(layer=23,head=0,output_index=0,key_count=2,weights=[1,0]),
            dict(layer=23,head=0,output_index=2,key_count=2,weights=[0,1]),
            dict(layer=23,head=1,output_index=0,key_count=2,weights=[0,0]),
            dict(layer=22,head=0,output_index=0,key_count=2,weights=[1,0])])
        rows=attention_overviews(signal)
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[0]['frames'][0]['weights'],[.5,.5])
        self.assertFalse(rows[0]['complete'])
        self.assertEqual(rows[0]['output_total'],3)
        self.assertIsNone(rows[1]['frames'][0]['frame_share'])
        self.assertIsNone(rows[1]['image_entropy_nats'])
        signal['attention'].append(copy.deepcopy(signal['attention'][0]))
        self.assertEqual(len(attention_overviews(signal)),2)  # Ambiguous duplicate group omitted.
        for row in signal['attention']:row.pop('output_index')
        self.assertEqual(attention_overviews(signal),[])

    def test_overview_is_derived_for_html_without_modifying_saved_bundle(self):
        bundle=add_graphs(self.export())
        signal=bundle['trace_steps'][1]['signals']
        signal.pop('attention_overviews',None)
        signal['output_token_ids']=[7]
        signal['attention'][0]['output_index']=0
        original=copy.deepcopy(bundle)
        import re
        page=task_html(bundle,'tasks/test.json')
        payload=json.loads(re.search(r'id="trajectory-data">(.*?)</script>',page,re.S)[1])
        overview=payload['episodes'][0]['frames'][1]['signals']['attention_overviews'][0]
        self.assertTrue(overview['complete'])
        self.assertAlmostEqual(overview['image_mass'],.6)
        self.assertEqual(bundle,original)

    def test_changed_image_and_bad_mapping(self):
        task=self.root/'fixture-run-a/chrome/fixture-task'
        png(task/'initial.png',400,225)
        frame=self.export()['trace_steps'][1]
        self.assertEqual(frame['signal_status'],'unverified')
        record=json.loads((task/'visual_signals.jsonl').read_text())
        record['images'][1]['key_indices'][0]=0
        with self.assertRaises(ValueError):attention_rows(record)

    def test_malformed_optional_signals_do_not_hide_actions(self):
        p=self.root/'fixture-run-a/chrome/fixture-task/visual_signals.jsonl'
        p.write_text('{incomplete optional record\n')
        out=self.export()
        self.assertEqual(sum(len(s['actions']) for s in out['trace_steps']),5)
        self.assertTrue(all(s['signal_status']=='unverified' and s['signals'] is None for s in out['trace_steps']))
        self.assertTrue(all(s['signal_source'] for s in out['trace_steps']))

    def test_literal_coordinates_and_unsafe_or_missing_inputs(self):
        marks,cursor=mouse_marks('pyautogui.click(x=100,y=200)')
        self.assertEqual((marks[0]['x'],marks[0]['y']),(100,200))
        self.assertEqual(mouse_marks('pyautogui.click()')[0],[])
        self.assertEqual(mouse_marks('pyautogui.click(eval("0"), 20)')[0],[])
        marks,_=mouse_marks('pyautogui.dragTo(300,400)',cursor)
        self.assertEqual(marks[0]['fromX'],100)
        self.assertEqual(mouse_marks('if True: pyautogui.click(5,6)')[0],[])
        with self.assertRaises(ValueError):self.export(['../outside'])
        task=self.root/'fixture-run-a/chrome/fixture-task'
        with (task/'traj.jsonl').open('a') as f:f.write('{malformed\n')
        with self.assertRaisesRegex(ValueError,'traj.jsonl:8'):self.export()

    def test_installed_callback_generates_graph_without_manual_export(self):
        output=self.root.parent/(self.root.name+'-graphs')
        self.addCleanup(shutil.rmtree,output,True)
        config=self.root/'hook-config.json'
        write_json(config,dict(results_root=str(self.root),output_dir=str(output),source='fixture',postprocess='inline'))
        harness=self.root/'fake_harness.py'
        original='def run_single_example(args, example_result_dir, example=None):\n    return 17\n'
        harness.write_text(original)
        install_hook(harness)
        installed=harness.read_bytes()
        install_hook(harness)
        self.assertEqual(harness.read_bytes(),installed)
        self.assertEqual(harness.with_name(harness.name+'.before-cua-graph').read_text(),original)
        run=self.root/'fixture-run-a';task=run/'chrome/fixture-task'
        with patch.dict(os.environ,{'CUA_INSPECTION_CONFIG':str(config)}):
            function=runpy.run_path(str(harness))['run_single_example']
            self.assertEqual(function(SimpleNamespace(result_dir=run),str(task)),17)
            first=json.loads((output/'index.json').read_text())
            self.assertEqual(function(SimpleNamespace(result_dir=str(run)),str(task)),17)
            self.assertEqual(json.loads((output/'index.json').read_text()),first)
        self.assertEqual(len(first['trajectories']),2)
        page=output/first['trajectories'][0]['html'].split('#')[0]
        self.assertIn('轨迹调试器',page.read_text())
        self.assertNotIn('127.0.0.1:8776',page.read_text())
        data=json.loads((output/first['trajectories'][0]['json']).read_text())
        self.assertEqual(len(data['graphs'][first['trajectories'][0]['id']]['action']['occurrences']),4)
        self.assertFalse(list(output.rglob('*.png')))

    def test_render_failure_preserves_original_return_and_exception(self):
        def success(args,example_result_dir):return 'original result'
        def failed(args,example_result_dir):raise ValueError('original evaluation error')
        args=SimpleNamespace(result_dir=str(self.root))
        with patch.dict(os.environ,{'CUA_INSPECTION_CONFIG':str(self.root/'missing-config.json')}):
            with self.assertLogs('cua.inspection',level='ERROR'):
                self.assertEqual(wrap_task(success)(args,str(self.root)),'original result')
            with self.assertLogs('cua.inspection',level='ERROR'):
                with self.assertRaisesRegex(ValueError,'original evaluation error'):
                    wrap_task(failed)(args,str(self.root))

    def test_index_refresh_retains_runs_and_uses_original_task_facets(self):
        output=self.root.parent/(self.root.name+'-index')
        self.addCleanup(shutil.rmtree,output,True)
        config=dict(results_root=str(self.root),output_dir=str(output),source='fixture')
        for name in ('fixture-run-a','fixture-run-b'):
            run=self.root/name
            render_task(run/'chrome/fixture-task',run,config)
        examples=self.root/'examples'
        write_json(examples/'chrome/fixture-task.json',dict(related_apps=['chrome','terminal'],evaluator={'func':'exact_match'}))
        before={str(p):p.read_bytes() for p in (output/'tasks').glob('*.json')}
        self.assertEqual(refresh_index(output,examples),dict(runs=2,episodes=4))
        index=json.loads((output/'index.json').read_text())
        self.assertEqual(len(index['runs']),2)  # Same model name still has two independent runs.
        self.assertTrue(all(r['related_apps']==['chrome','terminal'] and r['evaluator_functions']==['exact_match'] for r in index['trajectories']))
        self.assertEqual(before,{str(p):p.read_bytes() for p in (output/'tasks').glob('*.json')})
        index['trajectories'][0]['instruction']='</script><script>bad()</script>'
        self.assertNotIn('</script><script>bad()',index_html(index))

    def test_evaluator_backfill_keeps_original_actions_score_and_episode_scope(self):
        output=self.root.parent/(self.root.name+'-evaluation')
        self.addCleanup(shutil.rmtree,output,True)
        run=self.root/'fixture-run-a'
        config=dict(results_root=str(self.root),output_dir=str(output),source='fixture')
        render_task(run/'chrome/fixture-task',run,config)
        examples=self.root/'examples'
        criteria={'func':'compare_text_file','expected':{'type':'cloud_file','path':'https://example.invalid/expected.txt'},'result':{'type':'vm_file','path':'/tmp/output.txt'}}
        write_json(examples/'chrome/fixture-task.json',{'evaluator':criteria})
        source=self.root/'evaluator.py';source.write_text('def evaluate(self):\n    raise RuntimeError("must never execute")\n')
        path=next((output/'tasks').glob('*.json'));before=json.loads(path.read_text())
        self.assertEqual(refresh_pages(output,examples,source)['pages'],1)
        after=json.loads(path.read_text())
        self.assertEqual(after['trace_steps'],before['trace_steps'])
        self.assertNotIn('evaluation',after['trace_catalog'][0])
        evidence=after['trace_catalog'][-1]['evaluation']
        self.assertEqual(evidence['score'],.5)
        self.assertEqual(evidence['last_action'],'WAIT')
        self.assertEqual(evidence['criteria'],criteria)
        self.assertEqual(evidence['actual_inputs_status'],'not_recorded')
        self.assertIn('must never execute',evidence['script']['code'])
        self.assertFalse(list(output.rglob('*.png')))
        config.update(task_config_dir=str(examples),evaluator_source=str(source))
        self.assertEqual(refresh_outputs(config),dict(pages=1,runs=1,episodes=2))
        generated={str(p):p.read_bytes() for p in output.rglob('*') if p.suffix in ('.html','.json')}
        refresh_outputs(config)
        self.assertEqual(generated,{str(p):p.read_bytes() for p in output.rglob('*') if p.suffix in ('.html','.json')})
        # The normal per-task path attaches the same evidence without a refresh command.
        (run/'chrome/fixture-task/task.json').unlink()  # Native runs use the external benchmark config.
        render_task(run/'chrome/fixture-task',run,config)
        live=json.loads(path.read_text())['trace_catalog'][-1]['evaluation']
        self.assertEqual(live['criteria'],criteria)
        self.assertEqual(live['script']['sha256'],evidence['script']['sha256'])

    def test_base_run_alias_is_scoped_and_keeps_original_metadata(self):
        output=self.root.parent/(self.root.name+'-alias')
        self.addCleanup(shutil.rmtree,output,True)
        config=dict(results_root=str(self.root),output_dir=str(output),source='fixture',
                    run_aliases={'fixture-run-a':'t38i10'})
        for name in ('fixture-run-a','fixture-run-b'):
            run=self.root/name;render_task(run/'chrome/fixture-task',run,config)
        index=json.loads((output/'index.json').read_text())
        records=list(index['runs'].values())
        self.assertEqual({r['canonical_name'] for r in records},{'27b-base@10f1','9b-full-mixbtf'})
        teacher=next(r for r in records if r['canonical_name']=='27b-base@10f1')
        self.assertEqual(teacher['args']['arm'],'mixbtf9b')  # Imported label never rewrites the saved args.
        self.assertEqual(teacher['checkpoint'],'fixture-checkpoint')
        self.assertEqual(teacher['naming_source'],'Explicit per-run import alias')
        page=index_html(index)
        self.assertIn('Qwen3.8-27B',page)
        self.assertIn('原始权重 · 未做本项目 SFT',page)

    def test_parallel_callbacks_keep_independent_pages_and_ignore_old_report_config(self):
        output=self.root.parent/(self.root.name+'-graphs')
        self.addCleanup(shutil.rmtree,output,True)
        run=self.root/'fixture-run-a'
        tasks=[run/'chrome/fixture-task',run/'chrome/second-task']
        shutil.copytree(tasks[0],tasks[1])
        output.mkdir()
        snapshot=output/'viewer.json';write_json(snapshot,{'queries':{}})
        config=output/'config.json'
        write_json(config,dict(results_root=str(self.root),output_dir=str(output),source='fixture',snapshot=str(snapshot),viewer_url='https://old-report.invalid',build_command=['must-not-run']))
        script=Path(__file__).resolve().parents[1]/'scripts/eval/after_task.py'
        processes=[subprocess.Popen([sys.executable,str(script),'render','--config',str(config),
                    '--run-dir',str(run),'--task-dir',str(task)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                   for task in [tasks[0],tasks[1],tasks[0]]]
        for process in processes:
            stdout,stderr=process.communicate(timeout=15)
            self.assertEqual(process.returncode,0,stderr)
        index=json.loads((output/'index.json').read_text())
        self.assertEqual(len(index['trajectories']),4)
        self.assertEqual(json.loads(snapshot.read_text()),{'queries':{}})
        self.assertEqual(len(list(output.glob('task-*.html'))),2)
        for page in output.glob('task-*.html'):
            self.assertNotIn('old-report.invalid',page.read_text())
        data=[json.loads(p.read_text()) for p in (output/'tasks').glob('*.json')]
        self.assertEqual(sum(len(s['actions']) for d in data for s in d['trace_steps']),10)

    def test_screenshot_server_accepts_new_task_without_restart(self):
        output=self.root.parent/(self.root.name+'-graphs')
        self.addCleanup(shutil.rmtree,output,True)
        config=dict(results_root=str(self.root),output_dir=str(output),source='fixture')
        first=self.root/'fixture-run-a';second=self.root/'fixture-run-b'
        render_task(first/'chrome/fixture-task',first,config)
        server=asset_server(output/'manifest.json',0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url=f'http://127.0.0.1:{server.server_port}/fixture-run-b/chrome/fixture-task/initial.png'
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(url)
            self.assertEqual(error.exception.code,404)
            render_task(second/'chrome/fixture-task',second,config)
            with urllib.request.urlopen(url) as response:
                self.assertEqual(response.read(),(second/'chrome/fixture-task/initial.png').read_bytes())
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_whole_long_trajectory_is_not_truncated_or_deduplicated(self):
        bundle=self.export()
        trace=bundle['trace_catalog'][0]
        frames=[]
        for number in range(100):
            frame=copy.deepcopy(bundle['trace_steps'][0])
            frame.update(step=number+1,order=number)
            frames.append(frame)
        grouped=action_graph(frames,'action')
        self.assertEqual(len(grouped['occurrences']),200)
        self.assertEqual(len(grouped['nodes']),2)
        self.assertEqual(sum(len(n['occurrences']) for n in grouped['nodes']),200)
        self.assertEqual(sum(len(e['occurrences']) for e in grouped['edges']),199)
        self.assertEqual(len(action_graph(frames,'steps')['nodes']),200)

    def test_return_edges_self_loops_and_app_identity(self):
        actions=['pyautogui.click(4, 5)', 'pyautogui.press("esc")',
                 'pyautogui.click(4,5)', 'pyautogui.click(4,5)']
        frames=[dict(step=i+1,actions=[dict(action=a,app='chrome',row_number=i+1)]) for i,a in enumerate(actions)]
        g=action_graph(frames)
        self.assertEqual(g['route'],[0,1,0,0])
        self.assertEqual(g['nodes'][0]['occurrences'],[0,2,3])
        self.assertEqual([(e['source'],e['target']) for e in g['edges']],[(0,1),(1,0),(0,0)])
        frames[-1]['actions'][0]['app']='editor'
        self.assertEqual(len(action_graph(frames)['nodes']),3)
        self.assertEqual(len(action_graph(frames,'state')['nodes']),4)  # Missing hashes never merge.
        for f in frames:f['actions'][0]['before_sha256']='same-image'
        self.assertEqual(len(action_graph(frames,'state')['nodes']),2)

    def test_raw_prediction_cannot_escape_embedded_json(self):
        bundle=add_graphs(self.export())
        text='</script><script>window.injected=true</script>'
        bundle['trace_steps'][0]['response']=text
        page=task_html(bundle,'tasks/test.json')
        self.assertNotIn(text,page)
        import re
        data=json.loads(re.search(r'id="trajectory-data">(.*?)</script>',page,re.S)[1])
        self.assertEqual(data['episodes'][0]['frames'][0]['response'],text)

    def test_standalone_server_serves_only_tool_and_allowlisted_evidence(self):
        output=self.root.parent/(self.root.name+'-viewer')
        self.addCleanup(shutil.rmtree,output,True)
        config=dict(results_root=str(self.root),output_dir=str(output),source='fixture')
        run=self.root/'fixture-run-a'
        entries=render_task(run/'chrome/fixture-task',run,config)
        server=viewer_server(output,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            for path in ['/', '/'+entries[0]['html'].split('#')[0],'/assets/fixture-run-a/chrome/fixture-task/initial.png']:
                with urllib.request.urlopen(base+path) as response:self.assertEqual(response.status,200)
            for path in ['/config.json','/../../etc/passwd','/assets/../../etc/passwd']:
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(base+path)
                self.assertEqual(error.exception.code,404)
        finally:
            server.shutdown();server.server_close();thread.join()



if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--write-fixture':
        print(fixture(Path(sys.argv[2]).resolve()))
    elif len(sys.argv)==3 and sys.argv[1]=='--write-loop-fixture':
        print(loop_fixture(Path(sys.argv[2]).resolve()))
    else:
        unittest.main()
