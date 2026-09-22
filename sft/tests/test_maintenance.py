import json,os,signal,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from sft.scripts.eval import run_eval as run,maintenance as m

class MaintenanceTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform=='linux','Uses Linux process identities and process groups')
    def test_inflight_waits_and_completed_reply_pauses_and_resumes_same_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);task=('tasks','one');folder=root/'run';attempt=folder/'attempts'/run.task_key(task)/'attempt-01';td=attempt/'tasks/one';cap=td/'capture';cap.mkdir(parents=True)
            counter=root/'counter';code='import time,pathlib\np=pathlib.Path('+repr(str(counter))+')\nfor i in range(1000):\n p.write_text(str(i));time.sleep(.02)'
            child=subprocess.Popen([sys.executable,'-c',code],start_new_session=True)
            try:
                plan=dict(run_id='run',plan_sha256='fixed',hosts={'h':{'results_root':str(root)}},assignments={'h':[task]})
                state=dict(task=task,status='running',attempt=str(attempt),process=run.identity(child.pid),teacher_id='r1')
                run.write_json(folder/'task-state'/(run.task_key(task)+'.json'),state)
                (cap/'events.jsonl').write_text(json.dumps(dict(type='decision_start',session='s',step_num=1,decision_id='s:1'))+'\n')
                req=cap/'requests/cua-s-1-1.json';run.write_json(req,dict(decision_id='s:1',request_id='id'))
                self.assertTrue(m.maintain(plan,'h','pause',['r1'])['pending'])
                run.write_json(req,dict(decision_id='s:1',request_id='id',response_sha256='hash'))
                self.assertFalse(m.maintain(plan,'h','pause',['r1'])['pending'])
                time.sleep(.05)
                self.assertEqual((Path('/proc')/str(child.pid)/'stat').read_text().rsplit(')',1)[1].split()[0],'T')
                m.maintain(plan,'h','resume',['r1']);time.sleep(.08)
                self.assertIsNone(child.poll());self.assertNotEqual((Path('/proc')/str(child.pid)/'stat').read_text().rsplit(')',1)[1].split()[0],'T')
            finally:
                os.killpg(child.pid,signal.SIGCONT);os.killpg(child.pid,signal.SIGTERM);child.wait()

if __name__=='__main__':unittest.main()
