"""No GPU/VM use: planner, real subprocess isolation, resume and identity checks."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import types
import shutil
from unittest.mock import patch

from sft.scripts.eval import run_eval as runner


class EvalTests(unittest.TestCase):
    def test_shared_queue_uses_idle_service_and_keeps_active_task_affinity(self):
        import time
        with tempfile.TemporaryDirectory() as d:
            tasks=[('tasks',str(i)) for i in range(6)]
            plan=dict(run_id='shared',model={'endpoint':'slow'},hosts={'h':{'results_root':d,'slots':2}},
                      assignments={'h':tasks},teacher_slots={'h':{'slow':1,'idle':1}})
            run_dir=Path(d)/'shared';run_dir.mkdir()
            runner.write_json(run_dir/'task-state'/(runner.task_key(tasks[0])+'.json'),dict(process={'fixture':True},teacher_id='slow'))
            seen=[];working={'slow':0,'idle':0};lock=threading.Lock()
            def execute(plan,host,task,env,config,halt,teacher_override=None):
                with lock:
                    working[teacher_override]+=1;self.assertLessEqual(working[teacher_override],1);seen.append((task,teacher_override))
                time.sleep(.2 if task==tasks[0] else .005)
                with lock:working[teacher_override]-=1
            with patch.object(runner,'alive',side_effect=lambda p:bool(p)),patch.object(runner,'execute_task',side_effect=execute):
                runner.dispatch_tasks(plan,'h',{}, {})
            self.assertEqual(len(seen),len(tasks));self.assertEqual(len(set(t for t,_ in seen)),len(tasks))
            self.assertIn((tasks[0],'slow'),seen)
            self.assertTrue(all(teacher=='idle' for task,teacher in seen if task!=tasks[0]))

    def test_preflight_allows_only_owned_active_tasks(self):
        with tempfile.TemporaryDirectory() as d:
            plan=dict(run_id='test',benchmark='verified',protocol={},model={'endpoint':'r1'},assignments={'h':[('a','b')]},
                hosts={'h':{'results_root':d,'slots':1,'benchmarks':{'verified':{'root':d,'entrypoint':'fake.py','python':sys.executable}}}})
            with patch.object(runner,'native_processes',return_value=[123]),patch.object(runner,'owned_native',return_value={123}), \
                 patch.object(runner,'describe',return_value={'commit':'same'}),patch.object(runner,'free_space',return_value=100), \
                 patch.object(runner,'inspect_model',return_value={'id':'same'}),patch.object(runner,'command',return_value='container'):
                self.assertTrue(runner.doctor(plan,'h')['ready'])
                with patch.object(runner,'native_processes',return_value=[123,456]):
                    self.assertIn('host_busy',runner.doctor(plan,'h')['errors'])

    def test_runtime_routes_preserve_frozen_protocol_and_reject_unrelated_changes(self):
        with tempfile.TemporaryDirectory() as d:
            plan=dict(run_id='test',plan_sha256='frozen',protocol={'image_max':10},hosts={'h':{'results_root':d,'endpoints':{'r1':{'url':'old','key_file':'key'}}}})
            path=Path(d)/'test/service-routes.json'
            runner.write_json(path,dict(plan_sha256='frozen',endpoints={'r1':{'url':'new','service_id':'a40-1'}}))
            host,_,_=runner.paths(plan,'h')
            self.assertEqual(host['endpoints']['r1']['url'],'new')
            self.assertEqual(plan['hosts']['h']['endpoints']['r1']['url'],'old')
            runner.write_json(path,dict(plan_sha256='frozen',protocol={'image_max':20}))
            with self.assertRaises(ValueError):runner.paths(plan,'h')

    def test_controller_adopts_existing_task_without_duplicate_launch(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);task=('tasks','one');run=root/'run';attempt=run/'attempts'/runner.task_key(task)/'attempt-01'
            out=attempt/'tasks/one';out.mkdir(parents=True)
            child=subprocess.Popen([sys.executable,'-c',"import time,pathlib;time.sleep(.3);pathlib.Path("+repr(str(out/'result.txt'))+").write_text('1.0')"])
            self.addCleanup(lambda: child.wait())
            state=run/'task-state'/(runner.task_key(task)+'.json')
            record={'pid':child.pid,'fixture':True}
            runner.write_json(state,dict(task=task,status='running',attempt=str(attempt),process=record,teacher_id='r1'))
            plan=dict(run_id='run',benchmark='verified',max_attempts=2,hosts={'h':{'results_root':d,'benchmarks':{'verified':{}},'endpoints':{}}})
            config=dict(source='fixture',output_dir=str(root/'pages'))
            with patch.object(runner,'alive',side_effect=lambda p:bool(p) and child.poll() is None),patch.object(runner,'command',return_value=''),patch.object(runner.subprocess,'Popen',side_effect=AssertionError('duplicate task')):
                runner.execute_task(plan,'h',task,{},config)
            self.assertEqual(runner.read_json(state)['score'],1.0)
            self.assertEqual(len(list(attempt.parent.glob('attempt-*'))),1)

    def test_fixed_two_plus_six_split_unique_names_and_panels(self):
        registry = {"models": {"27b-base": {"checkpoint": "/fixed/checkpoint", "max_parallel_requests": 8}},
                    "benchmarks": {b: {"panel_name": "frozen", "protocol": {}} for b in ("verified", "osworld2")},
                    "hosts": {"windows": {"slots": 2}, "workstation": {"slots": 6}}}
        manifest = {"tasks": [f"{n:03d}" for n in range(1, 109)]}
        def describe(*args, **kwargs):
            return dict(manifest=manifest, commit="fixed", file_hashes={"runner.py": "fixed"}, panel_sha256="fixed")
        for benchmark in ("verified", "osworld2"):
            plans = [runner.make_plan(registry, "27b-base", benchmark, ["windows", "workstation"], "8", describe_host=describe) for _ in range(2)]
            self.assertNotEqual(plans[0]["run_id"], plans[1]["run_id"])
            self.assertEqual([len(v) for v in plans[0]["assignments"].values()], [2, 6])
            flat = [tuple(t) for tasks in plans[0]["assignments"].values() for t in tasks]
            self.assertEqual(len(set(flat)), 8)
            self.assertEqual(set(flat), set(plans[0]["selected_tasks"]))
            runner.validate_plan(plans[0])
            changed = dict(plans[0], protocol={"max_steps": 999})
            with self.assertRaisesRegex(ValueError, "Plan changed"):
                runner.validate_plan(changed)
        registry["benchmarks"]["osworld2"]["blocked"] = {"tasks/036": "proxy", "tasks/037": "proxy"}
        hundred = runner.make_plan(registry, "27b-base", "verified", ["windows", "workstation"], "100", describe_host=describe)
        self.assertEqual([len(v) for v in hundred["assignments"].values()], [25, 75])
        plan = runner.make_plan(registry, "27b-base", "osworld2", ["windows", "workstation"], describe_host=describe)
        self.assertEqual(len(plan["selected_tasks"]), 108)
        self.assertEqual(sum(map(len, plan["assignments"].values())), 106)
        self.assertEqual(len(plan["blocked"]), 2)
        cleanup = runner.make_plan(registry, "27b-base", "verified", ["windows", "workstation"], "8",
                                   describe_host=describe, raw_retention="delete-after-export")
        self.assertEqual(cleanup["raw_retention"], "delete-after-export")
        self.assertEqual(hundred["raw_retention"], "delete-after-export")
        kept = runner.make_plan(registry, "27b-base", "verified", ["windows"], "1", describe_host=describe, raw_retention="keep")
        self.assertEqual(kept["raw_retention"], "keep")
        with self.assertRaisesRegex(ValueError, "Plan changed"):
            runner.validate_plan({**cleanup, "raw_retention": "keep"})
        with self.assertRaisesRegex(ValueError, "Unregistered model"):
            runner.make_plan(registry, "typo", "osworld2", ["windows"], describe_host=describe)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            runner.task_list({"tasks": ["001", "001"]})

    def test_one_failed_native_task_does_not_kill_other_task_and_resume_keeps_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            harness = base / "harness"
            harness.mkdir()
            (harness / "fake_native.py").write_text('''import argparse,json,pathlib,sys,time
p=argparse.ArgumentParser();p.add_argument('--test_all_meta_path');p.add_argument('--result_dir');a,_=p.parse_known_args()
m=json.load(open(a.test_all_meta_path));domain=next(iter(m));task=m[domain][0]
out=pathlib.Path(a.result_dir)/'pyautogui/screenshot/fake'/domain/task;out.mkdir(parents=True)
(out/'traj.jsonl').write_text(json.dumps({'step_num':1,'action':'WAIT','fixture':True})+'\\n')
time.sleep(.15 if task=='good' else .02)
if task=='bad':raise SystemExit(1)
(out/'result.txt').write_text('0.0')
''')
            root = base / "results"
            root.mkdir()
            plan = dict(run_id="fixture-run", benchmark="osworld2", max_attempts=2, task_timeout_seconds=10,
                        protocol={}, model={"endpoint": "teacher"}, hosts={"windows": {
                        "results_root": str(root), "min_free_gib": 0, "endpoints": {"teacher": {"url": "http://unused/v1"}},
                        "benchmarks": {"osworld2": {"root": str(harness), "python": sys.executable, "entrypoint": "fake_native.py"}}}})
            config = dict(source="synthetic-fixture", results_root=str(root), output_dir=str(base / "pages"))
            tasks = [("tasks", "bad"), ("tasks", "good")]
            with patch.object(runner, "inspect_model", return_value={"id": "fake"}), patch.object(runner, "command", return_value=""):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    list(pool.map(lambda task: runner.execute_task(plan, "windows", task, {}, config), tasks))
                run = root / plan["run_id"]
                states = [runner.read_json(run / "task-state" / (runner.task_key(task) + ".json")) for task in tasks]
                self.assertEqual([s["status"] for s in states], ["failed", "completed"])
                self.assertEqual(states[1]["score"], 0.0)
                self.assertEqual(len(list((run / "attempts" / runner.task_key(tasks[0])).glob("attempt-*"))), 2)
                result = Path(states[1]["result_file"])
                original = (result.read_bytes(), result.stat().st_mtime_ns)
                runner.execute_task(plan, "windows", tasks[1], {}, config)
                self.assertEqual(original, (result.read_bytes(), result.stat().st_mtime_ns))
                self.assertEqual(len(list((run / "attempts" / runner.task_key(tasks[1])).glob("attempt-*"))), 1)
                self.assertEqual(len(list((base / "pages/pending").glob("*.json"))), 3)

    def test_shared_dependency_failure_does_not_consume_task_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = dict(run_id="fixture", benchmark="osworld2", max_attempts=2,
                        hosts={"windows": {"results_root": str(root), "benchmarks": {"osworld2": {}}}})
            halt = threading.Event()
            with patch.object(runner, "inspect_model", side_effect=OSError("model disconnected")):
                runner.execute_task(plan, "windows", ("tasks", "001"), {}, {}, halt)
            self.assertTrue(halt.is_set())
            self.assertFalse(list(root.rglob("attempt-*")))
            state = runner.read_json(root / "fixture/task-state" / (runner.task_key(("tasks", "001")) + ".json"))
            self.assertEqual(state["status"], "blocked")

    def test_wrong_served_checkpoint_is_rejected(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"data": [{"id": "same-friendly-name", "root": "/wrong/weights", "max_model_len": 262144}]}).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "key"
            key.write_text("synthetic-key")
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                plan = {"model": {"checkpoint": "/expected/weights", "endpoint": "teacher"}}
                host = {"endpoints": {"teacher": {"url": f"http://127.0.0.1:{server.server_port}/v1", "key_file": str(key)}}}
                with self.assertRaisesRegex(ValueError, "checkpoint does not match"):
                    runner.inspect_model(plan, host)
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_container_labels_preserve_existing_labels_and_hook_is_idempotent(self):
        calls = []
        class Collection:
            def run(self, *args, **kwargs):
                calls.append(kwargs)
                return kwargs
        containers = types.ModuleType("docker.models.containers")
        containers.ContainerCollection = Collection
        native = types.ModuleType("lib_run_single")
        native.run_single_example = lambda *args, **kwargs: None
        source = (Path(runner.__file__).parent / "capture_runtime/sitecustomize.py").read_text()
        namespace = {}
        with patch.dict(sys.modules, {"docker.models.containers": containers, "lib_run_single": native}), patch.dict(os.environ,
                {"CUA_INSPECTION_CONFIG": "synthetic-fixture", "CUA_RUN_ID": "run-A", "CUA_TASK_ATTEMPT": "run-A:task-B:1"}):
            exec(compile(source, "sitecustomize.py", "exec"), namespace)
            exec(compile(source, "sitecustomize.py", "exec"), namespace)
            result = Collection().run("fixture", labels={"existing": "keep"})
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["labels"], {"existing": "keep", "org.cua.run": "run-A", "org.cua.attempt": "run-A:task-B:1"})

    def test_task_attempts_publish_one_logical_run(self):
        from sft.tests.test_visual_signals import fixture
        from sft.scripts.eval.after_task import wrap_task
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            raw = fixture(base / "results")
            logical = raw / "logical-eval"
            logical.mkdir()
            shutil.copy(raw / "fixture-run-a/args.json", logical / "args.json")
            config = dict(results_root=str(raw), output_dir=str(base / "pages"), source="fixture",
                          run_dir=str(logical), capture={"enabled": False}, collection="test")
            profile = base / "profile.json"
            runner.write_json(profile, config)
            def native(args, example_result_dir, example=None):
                return "native-result"
            with patch.dict(os.environ, {"CUA_INSPECTION_CONFIG": str(profile)}):
                for task in ("first", "second"):
                    attempt = logical / "attempts" / task / "attempt-01"
                    target = attempt / "chrome" / task
                    shutil.copytree(raw / "fixture-run-a/chrome/fixture-task", target)
                    self.assertEqual(wrap_task(native)(types.SimpleNamespace(result_dir=str(attempt)), str(target)), "native-result")
            runner.process_pending(config)
            index = runner.read_json(base / "pages/index.json")
            self.assertEqual(len(index["runs"]), 1)
            self.assertEqual({r["task_id"] for r in index["trajectories"]}, {"first", "second"})
            self.assertTrue(all(r["run"] == str(logical.resolve()) for r in index["trajectories"]))
            self.assertTrue(all(r["task_path"].startswith("attempts/") for r in index["trajectories"]))


if __name__ == "__main__":
    unittest.main()
