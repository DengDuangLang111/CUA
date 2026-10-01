"""Named, frozen eval plans; bounded task workers on registered WSL hosts.

Uses native benchmark runners and the existing capture/export pipeline. No LLM
or SSH retry loop. See sft/docs/EVAL_AUTOMATION.md for registry and examples.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import uuid

TOOL = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(TOOL))
from sft.analysis.visual_signals import read_json, write_json
from sft.scripts.eval.after_task import queue_task, process_pending


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+@~-]*", value), "Unsafe identifier")
    return value


def task_list(manifest):
    require(isinstance(manifest, dict), "Panel must map domains to task ID lists")
    tasks = []
    for domain, ids in manifest.items():
        require(isinstance(ids, list), "Panel values must be lists")
        tasks.extend((identifier(domain), identifier(task)) for task in ids)
    require(tasks and len(tasks) == len(set(tasks)), "Panel is empty or has duplicate task IDs")
    return tasks


def identity(pid):
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if stat[0] == "Z":
            return None
        return dict(pid=pid, boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(), start_ticks=stat[19])
    except (OSError, IndexError):
        return None


def alive(record):
    return bool(record and identity(record["pid"]) == record)


def command(args, timeout=30, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, **kwargs)
    if result.returncode:
        raise RuntimeError(f"{args[0]} exited {result.returncode}: {result.stderr.strip()[-1600:] or result.stdout.strip()[-1600:]}")
    return result.stdout


def rpc(host, operation, **payload):
    # Only operator-owned registry entries define transport commands.
    remote = host["remote_command"]
    remote = subprocess.list2cmdline(remote) if host.get("windows_shell") else shlex.join(remote)
    result = subprocess.run(host["ssh"] + [remote], input=json.dumps(dict(op=operation, host=host, **payload)),
                            capture_output=True, text=True, timeout=180 if operation in ("doctor", "start") else 60)
    require(result.returncode == 0, f"SSH failed once; no login retries: {result.stderr[-1200:]}")
    reply = json.loads(result.stdout)
    require(reply.get("ok"), reply.get("error", "Remote operation failed"))
    return reply["result"]


def describe(host, benchmark):
    spec = host["benchmarks"][benchmark]
    root = Path(spec["root"]).expanduser().resolve()
    commit = command(["git", "-C", str(root), "rev-parse", "HEAD"]).strip()
    require(commit == spec["commit"], f"Benchmark commit changed: {root}")
    for relative, expected in spec["file_hashes"].items():
        require(hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected,
                f"Benchmark file changed: {relative}")
    path = root / spec["panel"]
    require(hashlib.sha256(path.read_bytes()).hexdigest() == spec["panel_sha256"], "Official panel changed")
    return dict(commit=commit, file_hashes=spec["file_hashes"], manifest=read_json(path), panel_sha256=spec["panel_sha256"])


def teacher_status(host, model, definitions, connect=False):
    """Cheap metadata checks only: no completion probe or background polling."""
    rows = []
    for name in model.get("teachers", []):
        item = dict(id=name, label=definitions[name].get("label", name),
                    capacity=definitions[name]["capacity"], ready=False, available_slots=0)
        try:
            served = inspect_model({"model": model}, host, connect=connect, endpoint_id=name)
            endpoint = host["endpoints"][name]
            key = Path(endpoint["key_file"]).expanduser().read_text().strip()
            base = endpoint["url"].rstrip("/").removesuffix("/v1")
            headers = {"Authorization": "Bearer " + key}
            # The collector route is installed lazily; cached OpenAPI may omit it.
            # OPTIONS tests routing without inference or reading an artifact.
            capture = False
            try:
                urlopen(Request(base + "/v1/cua-attention/" + "0" * 64 + ".rank0.attn", headers=headers, method="OPTIONS"), timeout=10).close()
            except HTTPError as exc:
                capture = exc.code == 405 and "GET" in exc.headers.get("Allow", "")
            item.update(served_model=served, capture=capture)
            require(capture, "This evaluation requires the CUA attention collector")
            with urlopen(Request(base + "/metrics", headers=headers), timeout=10) as response:
                metrics = response.read().decode()
            def count(metric):
                values = re.findall(r"^" + re.escape(metric) + r"(?:\{[^}]*\})?\s+([0-9.eE+\-]+)\s*$", metrics, re.M)
                require(values, "Missing teacher load metric: " + metric)
                numbers = [float(v) for v in values]
                require(all(math.isfinite(v) and v >= 0 for v in numbers), "Invalid teacher load")
                return math.ceil(sum(numbers))
            running, waiting = count("vllm:num_requests_running"), count("vllm:num_requests_waiting")
            item.update(ready=True, running=running, waiting=waiting,
                        available_slots=max(0, item["capacity"] - running - waiting))
        except Exception as exc:
            item["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(item)
    return rows


def teacher_slots(registry, selected, model, snapshots):
    """Static host shares prevent two hosts from each using the whole teacher.

    Partition across all registered hosts, even for a one-host run. This trades
    borrowing idle capacity for simple, reproducible task queues without a broker.
    """
    limits = {name: {} for name in selected}
    for teacher in model["teachers"]:
        capacity = registry["teachers"][teacher]["capacity"]
        require(type(capacity) is int and capacity > 0, "Teacher capacity must be positive")
        members = {n: h["slots"] for n, h in registry["hosts"].items() if teacher in h.get("endpoints", {})}
        require(members, "Teacher has no registered endpoint: " + teacher)
        reports = {n: next(r for r in snapshots[n] if r["id"] == teacher) for n in selected}
        available = min([capacity] + [r["available_slots"] for r in reports.values() if r.get("ready")])
        total = sum(members.values())
        shares = {n: available * slots // total for n, slots in members.items()}
        order = sorted(members, key=lambda n: (-(available * members[n] % total), list(members).index(n)))
        for name in order[:available - sum(shares.values())]:
            shares[name] += 1
        for name in selected:
            if reports[name].get("ready") and reports[name]["available_slots"] and shares.get(name):
                limits[name][teacher] = shares[name]
    allocation = {}
    for name, host in selected.items():
        used = {t: 0 for t in limits[name]}
        for _ in range(host["slots"]):
            candidates = [t for t in used if used[t] < limits[name][t]]
            if not candidates:
                break
            chosen = min(candidates, key=lambda t: (used[t] / limits[name][t], list(used).index(t)))
            used[chosen] += 1
        allocation[name] = {t: n for t, n in used.items() if n}
        require(allocation[name], name + " has no free, compatible teacher: " + json.dumps(snapshots[name]))
    return allocation


def task_teacher(plan, host_id, task):
    return plan.get("task_teachers", {}).get(host_id, {}).get(task_key(task), plan.get("model", {}).get("endpoint", "teacher"))


def make_plan(registry, model_name, benchmark, hosts, count="all", panel=None, panel_name=None, describe_host=rpc, collection="eval", raw_retention="delete-after-export"):
    require(raw_retention in ("keep", "delete-after-export"), "Unknown raw retention policy")
    require(model_name in registry["models"], f"Unregistered model: {model_name}")
    require(benchmark in registry["benchmarks"], f"Unregistered benchmark: {benchmark}")
    model = registry["models"][model_name]
    require(model.get("enabled", True), "Model registration is not ready")
    selected = {name: dict(registry["hosts"][name]) for name in hosts}
    require(selected and len(selected) == len(hosts), "Choose distinct registered hosts")
    require(all(type(h["slots"]) is int and h["slots"] > 0 for h in selected.values()), "VM slots must be positive integers")
    require(sum(h["slots"] for h in selected.values()) <= model["max_parallel_requests"], "VM total exceeds model service capacity")
    snapshots, limits = {}, {}
    if model.get("teachers"):
        require(len(set(model["teachers"])) == len(model["teachers"]), "Duplicate teacher IDs")
        definitions = {t: registry["teachers"][t] for t in model["teachers"]}
        snapshots = {name: describe_host(host, "teachers", model=model, definitions=definitions, connect=True)
                     for name, host in selected.items()}
        limits = teacher_slots(registry, selected, model, snapshots)
        for name, host in selected.items():
            host["requested_slots"] = host["slots"]
            host["slots"] = sum(limits[name].values())
    descriptions = [describe_host(h, "describe", benchmark=benchmark) for h in selected.values()]
    require(len({d["panel_sha256"] for d in descriptions}) == 1, "Hosts disagree on the official task panel")
    require(len({digest((d["commit"], d["file_hashes"])) for d in descriptions}) == 1, "Hosts disagree on benchmark code")
    official = task_list(descriptions[0]["manifest"])
    tasks = task_list(panel) if panel is not None else official
    require(set(tasks) <= set(official), "Custom panel contains tasks outside this benchmark")
    count = len(tasks) if count == "all" else int(count)
    require(0 < count <= len(tasks), "Requested task count is outside the panel")
    tasks = tasks[:count]  # Frozen manifest order, never an unrecorded random subset.
    bench = registry["benchmarks"][benchmark]
    reserved = {"model", "base_url", "api_key", "api_key_env", "result_dir", "test_all_meta_path", "num_envs"}
    require(not (set(bench["protocol"]) & reserved), "Model, credentials, output and worker count are managed by the runner")
    blocked = {"/".join(t): bench.get("blocked", {})["/".join(t)] for t in tasks if "/".join(t) in bench.get("blocked", {})}
    slots = [name for name, host in selected.items() for _ in range(host["slots"])]
    assignments = {name: [] for name in selected}
    runnable = [t for t in tasks if "/".join(t) not in blocked]
    quotas = {name: len(runnable) * h["slots"] // len(slots) for name, h in selected.items()}
    order = list(selected)
    remainders = sorted(order, key=lambda n: (-(len(runnable) * selected[n]["slots"] % len(slots)), order.index(n)))
    for name in remainders[:len(runnable) - sum(quotas.values())]:
        quotas[name] += 1
    cursor = 0
    for task in runnable:
        while len(assignments[slots[cursor % len(slots)]]) >= quotas[slots[cursor % len(slots)]]:
            cursor += 1
        assignments[slots[cursor % len(slots)]].append(task)
        cursor += 1
    panel_name = identifier(panel_name or bench["panel_name"])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{identifier(model_name)}--{identifier(benchmark)}--{panel_name}-n{count}--{stamp}-{uuid.uuid4().hex[:12]}"
    plan = dict(schema_version=1, run_id=run_id, model_name=model_name, model=model, benchmark=benchmark,
                protocol=bench["protocol"], environment=bench.get("environment", {}), panel_name=panel_name,
                official_panel_sha256=descriptions[0]["panel_sha256"], selected_tasks=tasks,
                selected_tasks_sha256=digest(tasks), benchmark_total=len(official), blocked=blocked,
                hosts=selected, assignments=assignments, collection=collection, raw_retention=raw_retention, max_attempts=2,
                allocation="fixed VM-weighted quotas, largest remainder, registry-order ties",
                task_timeout_seconds=bench.get("task_timeout_seconds", 28800))
    if limits:
        plan["teacher_slots"] = limits
        plan["teacher_snapshot"] = snapshots
        plan["teachers"] = definitions
        plan["task_teachers"] = {}
        assigned = {t: 0 for t in model["teachers"]}
        for host, tasks_for_host in assignments.items():
            local = {t: 0 for t in limits[host]}
            routes = {}
            for task in tasks_for_host:
                teacher = min(local, key=lambda t: (local[t] / limits[host][t], assigned[t] / definitions[t]["capacity"], t))
                routes[task_key(task)] = teacher
                local[teacher] += 1
                assigned[teacher] += 1
            plan["task_teachers"][host] = routes
    plan["plan_sha256"] = digest(plan)
    return plan


def validate_plan(plan):
    require(plan.get("plan_sha256") == digest({k: v for k, v in plan.items() if k != "plan_sha256"}),
            "Plan changed after creation; create a new run instead of editing a frozen plan")
    return plan


def paths(plan, host_id):
    host = plan["hosts"][host_id]
    root = Path(host["results_root"]).expanduser().resolve()
    run = root / identifier(plan["run_id"])
    routes = read_json(run / 'service-routes.json', {})
    if routes:
        require(routes.get('plan_sha256') == plan.get('plan_sha256'), 'Service routes belong to another frozen plan')
        require(set(routes) <= {'plan_sha256','revision','endpoints','pause_teachers','reason'}, 'Unsupported runtime override')
        endpoints = dict(host['endpoints'])
        for name, endpoint in routes.get('endpoints', {}).items():
            require(name in endpoints and set(endpoint) <= {'url','key_file','service_id'}, 'Only known service endpoints may change')
            endpoints[name] = dict(endpoints[name], **endpoint)
        host = dict(host, endpoints=endpoints)
    return host, root, run


def owned_native(plan, host_id):
    """Only adopt the exact saved PID/start-time identities and their descendants."""
    _, _, run = paths(plan, host_id)
    owned = set()
    for task in plan.get('assignments', {}).get(host_id, []):
        state = read_json(run/'task-state'/(task_key(task)+'.json'), {})
        if alive(state.get('process')):owned.add(state['process']['pid'])
    parents = {}
    for entry in Path('/proc').glob('[0-9]*'):
        try:parents[int(entry.name)] = int((entry/'stat').read_text().rsplit(')',1)[1].split()[1])
        except (OSError, ValueError, IndexError):pass
    while True:
        more = {pid for pid,parent in parents.items() if parent in owned} - owned
        if not more:return owned
        owned.update(more)


def inspect_model(plan, host, connect=False, large=False, endpoint_id=None):
    endpoint = host["endpoints"][endpoint_id or plan["model"]["endpoint"]]
    key = Path(endpoint["key_file"]).expanduser().read_text().strip()
    def fetch():
        with urlopen(Request(endpoint["url"].rstrip("/") + "/models", headers={"Authorization": "Bearer " + key}), timeout=10) as response:
            models = json.load(response)["data"]
        if large:
            url = endpoint["url"].rstrip("/").removesuffix("/v1") + "/openapi.json"
            with urlopen(Request(url, headers={"Authorization": "Bearer " + key}), timeout=12) as response:
                require(len(response.read()) > 200000, "Large response check failed")
        return models
    try:
        models = fetch()
    except OSError as exc:
        if isinstance(exc, HTTPError) or not connect or not endpoint.get("connect_once"):
            raise
        for args in endpoint.get("prepare_once", []):
            command(args)
        # Exactly one preconfigured connection attempt. Never prompt for login.
        command(endpoint["connect_once"])
        models = fetch()
    matches = [m for m in models if m.get("root", "").rstrip("/") == plan["model"]["checkpoint"].rstrip("/")]
    require(len(matches) == 1, "Serving checkpoint does not match the registered model; no eval launched")
    require(matches[0].get("max_model_len", 0) >= plan["model"].get("min_context", 0), "Serving context is too small")
    return matches[0]


def free_space(host, root):
    import shutil
    available = {str(p): round(shutil.disk_usage(p).free / 2**30, 1)
                 for p in [root.parent, *host.get("backing_drives", [])]}
    require(min(available.values()) >= host.get("min_free_gib", 50), f"Low disk space (GiB): {available}")
    return available


def native_processes():
    found = []
    for p in Path("/proc").glob("[0-9]*"):
        try:
            args = (p / "cmdline").read_bytes().decode().split("\0")
            if any(Path(a).name in ("run_multienv_qwen.py", "run_multienv_qwen_internal_agent.py", "entry.py") for a in args):
                found.append(int(p.name))
        except (OSError, UnicodeError):
            pass
    return found


def doctor(plan, host_id, connect=False):
    host, root, run = paths(plan, host_id)
    checks, errors = {}, {}
    def check(name, function):
        try:
            checks[name] = function()
        except Exception as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"
    check("benchmark", lambda: describe(host, plan["benchmark"])["commit"])
    active = native_processes()
    owned = owned_native(plan, host_id)
    foreign = set(active) - owned
    if foreign:
        errors["host_busy"] = f"Unowned native eval processes already active: {sorted(foreign)}"
    def docker_ready():
        if connect and not active:
            stale = command(["docker", "ps", "-aq", "--filter", "label=org.cua.run=" + plan["run_id"]]).split()
            if stale:
                command(["docker", "rm", "-f", *stale])
        containers = set(command(["docker", "ps", "-q", "--filter", "ancestor=happysixd/osworld-docker"]).split())
        ours = set(command(["docker", "ps", "-q", "--filter", "label=org.cua.run=" + plan['run_id']]).split()) if owned else set()
        require(not (containers - ours),
                "Existing OSWorld containers need an ownership check before starting")
        return command(["docker", "info", "--format", "{{.ServerVersion}}"]).strip()
    check("docker", docker_ready)
    check("disk_free_gib", lambda: free_space(host, root))
    if plan.get("teacher_slots"):
        def check_teachers():
            rows = teacher_status(host, plan["model"], plan["teachers"], connect)
            by_id = {r["id"]: r for r in rows}
            for name, slots in plan["teacher_slots"][host_id].items():
                require(by_id[name]["ready"] and (bool(owned) or by_id[name]["available_slots"] >= slots),
                        "Assigned teacher unavailable or busy; keep the plan fixed: " + json.dumps(by_id[name]))
            return {name: by_id[name]["served_model"] for name in plan["teacher_slots"][host_id]}
        check("served_models", check_teachers)
        if checks.get("served_models"):
            checks["served_model"] = next(iter(checks["served_models"].values()))
    else:
        check("served_model", lambda: inspect_model(plan, host, connect, large=True))
    spec = host["benchmarks"][plan["benchmark"]]
    def check_cli():
        env = os.environ.copy()
        env.pop("CUA_INSPECTION_CONFIG", None)
        # The Windows NTFS venv can take over 30s to import even for --help.
        text = command([spec["python"], str(Path(spec["root"]) / spec["entrypoint"]), "--help",], cwd=spec["root"], env=env, timeout=120)
        require(all("--" + key in text for key in plan["protocol"]), "Registered protocol has unsupported native CLI flags")
        return True
    if owned and read_json(run/'plan.json') == plan:
        checks['native_cli'] = 'unchanged frozen protocol already executing in owned native tasks'
    else:
        check("native_cli", check_cli)
    return dict(ready=not errors, served_model=checks.get("served_model"), checks=checks, errors=errors,
                slots=host["slots"], tasks=len(plan["assignments"][host_id]))


def score_in(attempt, task):
    for path in attempt.rglob("result.txt"):
        if (path.parent.parent.name, path.parent.name) != tuple(task):
            continue
        try:
            value = float(path.read_text().strip())
            if math.isfinite(value) and 0 <= value <= 1:
                return dict(score=value, result_file=str(path))
        except ValueError:
            pass
    return None


def task_key(task):
    return hashlib.sha256("/".join(task).encode()).hexdigest()[:20]


def status(plan, host_id):
    host, root, run = paths(plan, host_id)
    states = [read_json(run / "task-state" / (task_key(t) + ".json"), dict(task=t, status="pending"))
              for t in plan["assignments"][host_id]]
    controller = read_json(run / "controller.json")
    for state in states:
        if state["status"] == "running" and not alive(state.get("process")):
            state.update(status="interrupted", reason="Native task process is no longer alive")
    counts = {name: sum(s["status"] == name for s in states) for name in ("pending", "running", "completed", "failed", "blocked", "interrupted")}
    return dict(host=host_id, run_id=plan["run_id"], controller_alive=alive(controller), counts=counts,
                run_state=read_json(run / "status.json", {"status": "not_started"}), tasks=states,
                teacher_slots=plan.get("teacher_slots", {}).get(host_id))


def start(plan, host_id):
    host, root, run = paths(plan, host_id)
    if alive(read_json(run / "controller.json")):
        return {"already_running": True, "run_dir": str(run)}
    health = doctor(plan, host_id, connect=True)
    require(health["ready"], json.dumps(health["errors"]))
    if run.exists():
        require(read_json(run / "plan.json") == plan, "A run ID cannot be reused for a different plan")
    else:
        run.mkdir(parents=True, exist_ok=False)
        write_json(run / "plan.json", plan)
    spec = host["benchmarks"][plan["benchmark"]]
    with (run / "controller.log").open("ab") as log:
        child = subprocess.Popen([spec["python"], str(Path(__file__).resolve()), "_worker", "--plan", str(run / "plan.json"), "--host", host_id],
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    write_json(run / "controller.json", identity(child.pid))
    return dict(pid=child.pid, run_dir=str(run), tasks=len(plan["assignments"][host_id]), slots=host["slots"])


def argv(protocol):
    result = []
    for key, value in protocol.items():
        if value is True:
            result.append("--" + key)
        elif value is not False and value is not None:
            result += ["--" + key, str(value)]
    return result


def worker(plan, host_id):
    import fcntl
    host, root, run = paths(plan, host_id)
    with (root / ".eval-worker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _work_locked(plan, host_id)


def _work_locked(plan, host_id):
    host, root, run = paths(plan, host_id)
    health = doctor(plan, host_id)
    require(health["ready"], json.dumps(health["errors"]))
    served = health["served_model"]
    spec = host["benchmarks"][plan["benchmark"]]
    first_teacher = next(iter(plan.get("teacher_slots", {}).get(host_id, {})), plan["model"].get("endpoint"))
    endpoint = host["endpoints"][first_teacher]
    config = dict(results_root=str(root), output_dir=str(Path(host["output_dir"]).expanduser()), source=host["source"],
                  run_dir=str(run), collection=plan["collection"], postprocess="deferred", raw_retention=plan.get("raw_retention", "keep"),
                  evaluator_source=str(Path(spec["root"]) / "desktop_env/desktop_env.py"),
                  capture={"enabled": True, "backend": "vllm", "attention_every": 1, "top_logprobs": 5,
                           "attention_download": "background", "key_file": endpoint["key_file"],
                           "download_queue": str(root / ".attention-downloads"),
                           "download_min_free_gib": host.get("min_free_gib", 50),
                           "checkpoint": plan["model"]["checkpoint"]})
    postprocess = host.get('postprocess', {})
    require(not (set(postprocess) - {'export_workers', 'download_workers', 'resume_render', 'producer_cleanup'}),
            'Unknown postprocessing host setting')
    config.update(postprocess)
    write_json(run / "inspection.json", config)
    arm = plan["model"].get("arm", plan["model_name"])
    write_json(run / "args.json", dict(plan["protocol"], model=served["id"], arm=arm))
    write_json(run / "MODEL_BOUNDARY.json", dict(arm=arm, canonical_name=arm, model_id=plan["model_name"],
               checkpoint=plan["model"]["checkpoint"], precision=plan["model"].get("precision"),
               train_recipe=plan["model"].get("train_recipe")))
    write_json(run / "version.json", dict(run_id=plan["run_id"], benchmark=plan["benchmark"],
               panel_sha256=plan["selected_tasks_sha256"], benchmark_commit=spec["commit"],
               protocol=plan["protocol"], served_model=served, teacher_slots=plan.get("teacher_slots", {}).get(host_id), task_isolation="one native subprocess per task attempt"))
    env = dict(os.environ, **{**plan["environment"], **host.get("environment", {})}, OPENAI_API_KEY=Path(endpoint["key_file"]).expanduser().read_text().strip(),
               CUA_INSPECTION_CONFIG=str(run / "inspection.json"), CUA_RUN_ID=plan["run_id"],
               PYTHONPATH=":".join(map(str, [TOOL / "sft/scripts/eval/capture_runtime", TOOL, spec["root"], Path(spec["root"]) / "scripts/python"])))
    command([spec["python"], "-c", "import lib_run_single; assert getattr(lib_run_single.run_single_example,'_cua_capture_wrapped',False)"], cwd=spec["root"], env=env)
    output = Path(config["output_dir"])
    output.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        listening = probe.connect_ex(("127.0.0.1", host["viewer_port"])) == 0
    if not listening:
        with (output / "server.log").open("ab") as log:
            subprocess.Popen([spec["python"], str(TOOL / "sft/scripts/eval/after_task.py"), "serve", str(output), "--port", str(host["viewer_port"])],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    stop = threading.Event()
    def export_pending():
        with (run / "export.log").open("ab") as log:
            child = subprocess.run([spec["python"], str(TOOL / "sft/scripts/eval/after_task.py"),
                "process-pending", "--config", str(run / "inspection.json"), "--memory-limit-gib", "4"],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        if child.returncode:
            write_json(run / "export-error.json", {"error": "Page worker exited", "returncode": child.returncode, "time": time.time()})
    def export_loop():
        while not stop.wait(5):
            try:
                export_pending()
            except Exception as exc:
                write_json(run / "export-error.json", {"error": str(exc), "time": time.time()})
    exporter = threading.Thread(target=export_loop, daemon=True)
    exporter.start()
    previous_status = read_json(run / 'status.json', {})
    write_json(run / "status.json", dict(status="running", started_at=previous_status.get('started_at',time.time()), controller_started_at=time.time()))
    try:
        dispatch_tasks(plan, host_id, env, config)
    finally:
        stop.set()
        exporter.join()
        export_pending()
    counts = status(plan, host_id)["counts"]
    write_json(run / "status.json", dict(status="completed" if counts["completed"] == len(plan['assignments'][host_id]) else "needs_attention",
               finished_at=time.time(), counts=counts))


def dispatch_tasks(plan, host_id, env, config):
    """Fixed GPU/VM slots claim unstarted tasks from one host-local FIFO."""
    from queue import Queue, Empty
    host, _, folder = paths(plan, host_id)
    groups = plan.get('teacher_slots',{}).get(host_id,{plan['model'].get('endpoint'):host['slots']})
    active = {name: Queue() for name in groups}
    pending = Queue()
    for task in plan['assignments'][host_id]:
        state = read_json(folder/'task-state'/(task_key(task)+'.json'),{})
        if alive(state.get('process')):
            teacher = state.get('teacher_id') or task_teacher(plan,host_id,task)
            require(teacher in active,'Active task belongs to an unknown service')
            active[teacher].put(task)
        else:pending.put(task)
    require(all(q.qsize()<=groups[name] for name,q in active.items()),'Active tasks exceed fixed service slots')
    halts = {name: threading.Event() for name in groups}
    def consume(teacher):
        while not halts[teacher].is_set():
            try:task=active[teacher].get_nowait()
            except Empty:
                try:task=pending.get_nowait()
                except Empty:return
            execute_task(plan,host_id,task,env,config,halts[teacher],teacher_override=teacher)
    write_json(folder/'dispatch.json',dict(policy='shared_host_queue',slots=groups,
               active_tasks_keep_service=True,host_assignments_unchanged=True))
    with ThreadPoolExecutor(max_workers=sum(groups.values())) as pool:
        futures=[pool.submit(consume,name) for name,n in groups.items() for _ in range(n)]
        for future in as_completed(futures):future.result()


def execute_task(plan, host_id, task, env, config, halt=None, teacher_override=None):
    host, root, run = paths(plan, host_id)
    spec = host["benchmarks"][plan["benchmark"]]
    state_path = run / "task-state" / (task_key(task) + ".json")
    parent = run / "attempts" / task_key(task)
    prior = read_json(state_path, {})
    if prior.get('status') == 'running' and prior.get('process'):
        attempt = Path(prior['attempt']).resolve()
        require(attempt.parent == parent.resolve(), 'Saved active attempt is outside its task')
        # Controller replacement must never start the same task twice.
        deadline = state_path.stat().st_mtime + plan.get('task_timeout_seconds',28800)
        while alive(prior['process']):
            if time.time() > deadline:
                require(os.getpgid(prior['process']['pid']) == prior['process']['pid'], 'Unexpected adopted process group')
                os.killpg(prior['process']['pid'],signal.SIGTERM)
                break
            time.sleep(2)
        if alive(prior['process']):
            time.sleep(5)
            if alive(prior['process']):os.killpg(prior['process']['pid'],signal.SIGKILL)
        finish_attempt(plan, task, attempt, config, state_path, prior.get('teacher_id'), None, halt)
    previous = sorted(parent.glob("attempt-*"))
    for attempt in previous:
        result = score_in(attempt, task)
        if result is not None:
            previous_teacher = prior.get('teacher_id') or read_json(attempt/'execution.json',{}).get('teacher_id') or task_teacher(plan,host_id,task)
            write_json(state_path, dict(task=task, status="completed", teacher_id=previous_teacher, attempt=str(attempt), **result))
            return
    if len(previous) >= plan["max_attempts"]:
        write_json(state_path, dict(task=task, status="failed", error="Attempt limit reached; originals retained"))
        return
    for number in range(len(previous) + 1, plan["max_attempts"] + 1):
        if halt is not None and halt.is_set():
            return
        attempt = parent / f"attempt-{number:02d}"
        token = plan["run_id"] + ":" + task_key(task) + ":" + str(number)
        teacher = teacher_override or task_teacher(plan, host_id, task)
        while teacher in read_json(run/'service-routes.json', {}).get('pause_teachers', []):
            write_json(state_path, dict(task=task, status='blocked', reason='service_maintenance', teacher_id=teacher))
            time.sleep(2)
        host, root, run = paths(plan, host_id)
        task_env = dict(env, CUA_TASK_ATTEMPT=token)
        try:
            served = inspect_model(plan, host, endpoint_id=teacher)
            endpoint = host["endpoints"][teacher]
            if endpoint.get("key_file"):
                task_env["OPENAI_API_KEY"] = Path(endpoint["key_file"]).expanduser().read_text().strip()
                task_env["CUA_CAPTURE_KEY_FILE"] = endpoint["key_file"]
            command(["docker", "info", "--format", "{{.ServerVersion}}"])
            free_space(host, root)
        except Exception as exc:
            if halt is not None:
                halt.set()
            write_json(state_path, dict(task=task, status="blocked", error=str(exc), attempt=str(attempt)))
            return
        attempt.mkdir(parents=True, exist_ok=False)
        write_json(attempt / "task-panel.json", {task[0]: [task[1]]})
        args = [spec["python"], str(Path(spec["root"]) / spec["entrypoint"])] + argv(plan["protocol"])
        args += ["--model", served["id"], "--base_url", endpoint["url"],
                 "--num_envs", "1", "--test_config_base_dir", str(Path(spec["root"]) / "evaluation_examples"),
                 "--test_all_meta_path", str(attempt / "task-panel.json"), "--result_dir", str(attempt)]
        if spec.get("api_key_env_flag"):
            args += ["--api_key_env", "OPENAI_API_KEY"]
        write_json(attempt / "command.json", args)
        write_json(attempt / "execution.json", dict(runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), served_model=served, teacher_id=teacher, teacher_url=endpoint["url"], service_id=endpoint.get('service_id',teacher), service_routes=read_json(run/'service-routes.json'), attempt_label=token))
        with (attempt / "runner.log").open("ab") as log:
            child = subprocess.Popen(args, cwd=spec["root"], env=task_env, stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=log, start_new_session=True)
            write_json(state_path, dict(task=task, status="running", teacher_id=teacher, attempt=str(attempt), process=identity(child.pid)))
            try:
                code = child.wait(timeout=plan["task_timeout_seconds"])
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                code = 124
        if finish_attempt(plan, task, attempt, config, state_path, teacher, code, halt):
            return


def finish_attempt(plan, task, attempt, config, state_path, teacher, code, halt):
    run = state_path.parent.parent
    execution = read_json(attempt/'execution.json', {})
    token = execution.get('attempt_label') or plan['run_id']+':'+task_key(task)+':'+str(int(attempt.name.split('-')[-1]))
    cleanup_error = None
    try:
        ids = command(['docker','ps','-aq','--filter','label=org.cua.attempt='+token]).split()
        if ids:command(['docker','rm','-f',*ids])
    except Exception as exc:
        cleanup_error = str(exc)
        if halt is not None:halt.set()
    for traj in attempt.rglob('traj.jsonl'):
        key = hashlib.sha256((config['source']+':'+str(traj.parent.resolve())).encode()).hexdigest()[:32]
        if not (Path(config['output_dir'])/'pending'/(key+'.json')).exists():
            queue_task(traj.parent, run, config)
    result = score_in(attempt, task)
    write_json(state_path, dict(task=task,status='completed' if result else 'failed',attempt=str(attempt),
        exit_code=code,teacher_id=teacher,cleanup_error=cleanup_error,**(result or {})))
    return result is not None or cleanup_error is not None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=Path("eval-registry.json"))
    sub = parser.add_subparsers(dest="op", required=True)
    p = sub.add_parser("teachers", help="List registered teachers and their current readiness; no generation probe")
    p.add_argument("--model", required=True)
    p.add_argument("--hosts", nargs="+")
    p = sub.add_parser("plan")
    p.add_argument("--model", required=True)
    p.add_argument("--bench", required=True)
    p.add_argument("--hosts", nargs="+")
    p.add_argument("--tasks", default="all")
    p.add_argument("--panel", type=Path)
    p.add_argument("--panel-name")
    p.add_argument("--collection", choices=("eval", "test"), default="eval")
    p.add_argument("--raw-retention", choices=("keep", "delete-after-export"), default="delete-after-export")
    for name in ("doctor", "run", "resume", "status"):
        p = sub.add_parser(name)
        p.add_argument("--plan", type=Path, required=True)
    sub.add_parser("_rpc")
    p = sub.add_parser("_worker")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--host", required=True)
    args = parser.parse_args()
    if args.op == "_rpc":
        try:
            request = json.load(sys.stdin)
            if request["op"] == "teachers":
                result = teacher_status(request["host"], request["model"], request["definitions"], request.get("connect", False))
            elif request["op"] == "describe":
                result = describe(request["host"], request["benchmark"])
            else:
                require(request["op"] in ("doctor", "start", "status"), "Unsupported remote operation")
                validate_plan(request["plan"])
                fn = {"doctor": doctor, "start": start, "status": status}[request["op"]]
                options = {"connect": request.get("connect", False)} if request["op"] == "doctor" else {}
                result = fn(request["plan"], request["host_id"], **options)
            print(json.dumps(dict(ok=True, result=result)))
        except Exception as exc:
            print(json.dumps(dict(ok=False, error=f"{type(exc).__name__}: {exc}")))
        return
    if args.op == "_worker":
        plan = validate_plan(read_json(args.plan))
        try:
            worker(plan, args.host)
        except Exception as exc:
            write_json(args.plan.parent / "status.json", dict(status="blocked", error=f"{type(exc).__name__}: {exc}"))
            raise
        return
    if args.op == "teachers":
        registry = read_json(args.registry)
        model = registry["models"][args.model]
        require(model.get("teachers"), "Model has no registered teacher list")
        definitions = {t: registry["teachers"][t] for t in model["teachers"]}
        results = {name: rpc(registry["hosts"][name], "teachers", model=model, definitions=definitions)
                   for name in args.hosts or list(registry["hosts"])}
        print(json.dumps(results, indent=2))
        return
    if args.op == "plan":
        registry = read_json(args.registry)
        plan = make_plan(registry, args.model, args.bench, args.hosts or list(registry["hosts"]), args.tasks,
                         read_json(args.panel) if args.panel else None, args.panel_name, collection=args.collection, raw_retention=args.raw_retention)
        state_root = Path(registry["state_dir"]).expanduser().resolve()
        state_root.mkdir(parents=True, exist_ok=True)
        import fcntl
        with (state_root / ".models.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            binding = state_root / "model-bindings" / (identifier(args.model) + ".json")
            identity_record = {"checkpoint": plan["model"]["checkpoint"], "revision": plan["model"].get("revision")}
            require(read_json(binding, identity_record) == identity_record, "Model name is already bound to another checkpoint; use a new model name")
            write_json(binding, identity_record)
        folder = state_root / plan["run_id"]
        folder.mkdir(parents=True, exist_ok=False)
        write_json(folder / "plan.json", plan)
        print(json.dumps(dict(plan=str(folder / "plan.json"), run_id=plan["run_id"], selected=len(plan["selected_tasks"]),
              blocked=plan["blocked"], assignments={k: len(v) for k, v in plan["assignments"].items()},
              teacher_slots=plan.get("teacher_slots"), teacher_snapshot=plan.get("teacher_snapshot")), indent=2))
        return
    plan = validate_plan(read_json(args.plan))
    hosts = {k: v for k, v in plan["hosts"].items() if plan["assignments"][k]}
    results, existing_states = {}, {}
    # Preflight every selected host before dispatching any new VM workload.
    if args.op in ("run", "resume"):
        for name, host in hosts.items():
            existing = rpc(host, "status", plan=plan, host_id=name)
            existing_states[name] = existing
            if not existing["controller_alive"] and existing["counts"]["completed"] < len(plan["assignments"][name]):
                health = rpc(host, "doctor", plan=plan, host_id=name, connect=True)
                require(health["ready"], name + ": " + json.dumps(health["errors"]))
    for name, host in hosts.items():
        try:
            operation = "start" if args.op in ("run", "resume") else args.op
            if operation == "start" and existing_states[name]["counts"]["completed"] == len(plan["assignments"][name]):
                results[name] = {"already_completed": True}
            else:
                results[name] = rpc(host, operation, plan=plan, host_id=name)
        except Exception as exc:
            results[name] = {"error": str(exc)}
    print(json.dumps(dict(run_id=plan["run_id"], model=plan["model_name"], benchmark=plan["benchmark"],
                         selected_tasks=len(plan["selected_tasks"]), blocked=plan["blocked"], hosts=results), indent=2))
    if any("error" in value or value.get("ready") is False for value in results.values()):
        raise SystemExit(1)



if __name__ == "__main__":
    main()
