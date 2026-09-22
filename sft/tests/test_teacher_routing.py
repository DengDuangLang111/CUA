"""Static task routing: no inference probes, leases, broker or load polling."""
import copy
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from sft.scripts.eval import run_eval as runner


def registry():
    return {'models':{'teacher':{'checkpoint':'/fixed','min_context':262144,'max_parallel_requests':8,'endpoint':'legacy','teachers':['A','B']}},
        'teachers':{'A':{'capacity':4},'B':{'capacity':4}},
        'benchmarks':{'verified':{'panel_name':'panel','protocol':{}}},
        'hosts':{name:{'slots':slots,'endpoints':{'A':{},'B':{}}} for name,slots in [('windows',2),('workstation',6)]}}


def fake_rpc(host, operation, **kwargs):
    if operation=='describe':
        return dict(commit='fixed',file_hashes={},panel_sha256='fixed',manifest={'tasks':[str(i) for i in range(100)]})
    return [dict(id=t,ready=True,available_slots=4,capacity=4) for t in ('A','B')]


class TeacherRoutingTests(unittest.TestCase):
    def test_two_plus_six_uses_one_plus_one_and_three_plus_three(self):
        r=registry();original=copy.deepcopy(r)
        p=runner.make_plan(r,'teacher','verified',['windows','workstation'],'100',describe_host=fake_rpc)
        self.assertEqual(p['teacher_slots'],{'windows':{'A':1,'B':1},'workstation':{'A':3,'B':3}})
        self.assertEqual([len(v) for v in p['assignments'].values()],[25,75])
        counts=Counter(t for mapping in p['task_teachers'].values() for t in mapping.values())
        self.assertEqual(counts,{'A':50,'B':50});self.assertEqual(r,original)
        self.assertEqual(p['raw_retention'],'delete-after-export')
        for host,tasks in p['assignments'].items():
            self.assertEqual(len(p['task_teachers'][host]),len(tasks))
            self.assertTrue(all(runner.task_teacher(p,host,t) in ('A','B') for t in tasks))
        runner.validate_plan(p)

    def test_unavailable_teacher_is_skipped_without_overfilling_the_other(self):
        def status(host,op,**kwargs):
            rows=fake_rpc(host,op,**kwargs)
            if op=='teachers':rows[0].update(ready=False,available_slots=0,error='no collector')
            return rows
        p=runner.make_plan(registry(),'teacher','verified',['windows','workstation'],'100',describe_host=status)
        self.assertEqual(p['teacher_slots'],{'windows':{'B':1},'workstation':{'B':3}})
        self.assertEqual(sum(h['slots'] for h in p['hosts'].values()),4)
        self.assertTrue(all(t=='B' for m in p['task_teachers'].values() for t in m.values()))
        def unavailable(host,op,**kwargs):
            rows=fake_rpc(host,op,**kwargs)
            if op=='teachers':
                for row in rows:row.update(ready=False,available_slots=0)
            return rows
        with self.assertRaisesRegex(ValueError,'no free, compatible teacher'):
            runner.make_plan(registry(),'teacher','verified',['workstation'],'8',describe_host=unavailable)

    def test_separate_host_plans_do_not_each_take_the_entire_teacher(self):
        r=registry();plans=[runner.make_plan(r,'teacher','verified',[h],'20',describe_host=fake_rpc) for h in r['hosts']]
        for t in ['A','B']:
            self.assertEqual(sum(limits.get(t,0) for p in plans for limits in p['teacher_slots'].values()),4)

    def test_inventory_uses_only_gets_and_checks_checkpoint_capture_and_capacity(self):
        state={'capture':True,'running':2,'root':'/fixed'};methods=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                methods.append('GET '+self.path)
                if self.path=='/v1/models':data=json.dumps({'data':[{'id':'teacher','root':state['root'],'max_model_len':262144}]}).encode()
                elif self.path=='/openapi.json':data=json.dumps({'paths':{'/v1/cua-attention/{name}':{}} if state['capture'] else {}}).encode()
                else:data=(f'vllm:num_requests_running{{model_name="teacher"}} {state["running"]}\nvllm:num_requests_waiting{{model_name="teacher"}} 0\n').encode()
                self.send_response(200);self.end_headers();self.wfile.write(data)
            def do_OPTIONS(self):
                methods.append('OPTIONS '+self.path)
                self.send_response(405 if state['capture'] else 404)
                if state['capture']:self.send_header('Allow','GET')
                self.end_headers()
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as d:
                key=Path(d)/'key';key.write_text('fixture-key')
                host={'endpoints':{'A':{'url':f'http://127.0.0.1:{server.server_port}/v1','key_file':str(key)}}}
                model={'checkpoint':'/fixed','min_context':262144,'teachers':['A']}
                def status():return runner.teacher_status(host,model,{'A':{'capacity':4}})[0]
                self.assertEqual(status()['available_slots'],2)
                state['running']=6;self.assertEqual(status()['available_slots'],0)
                state['capture']=False;self.assertFalse(status()['ready'])
                state['root']='/wrong';self.assertIn('checkpoint',status()['error'].lower())
                self.assertTrue(all(m.startswith(('GET ','OPTIONS ')) for m in methods))
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
