"""One reusable task-completion hook: saved trajectory -> standalone HTML + raw JSON + index.

Install once, then set CUA_INSPECTION_CONFIG before starting an evaluation.
No model calls, screenshot copies, background polling, or evaluation retries.
"""
import argparse
import ast
from contextlib import contextmanager
from functools import wraps
import inspect
import json
import logging
import os
from pathlib import Path
import re
import sys
import time
import threading
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from sft.analysis.visual_signals import digest, evaluation_evidence, export_runs, read_json, task_facets, write_json
from sft.analysis.trajectory_viewer import add_graphs, index_html, task_html, viewer_server



def write_text(path, text):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def add_index_run(index, run):
    # One metadata record per run; task counts are calculated from the index rows.
    index.setdefault("runs", {})[run["id"]] = {key: run.get(key) for key in (
        "canonical_name", "legacy_name", "corpus", "corpus_formula", "checkpoint",
        "path", "source", "args", "model_boundary", "naming_source")}
    index["schema_version"] = 3


def refresh_index(output, task_config_dir=None):
    """Refresh only the index from saved exports; no trajectory/image reprocessing."""
    import fcntl
    output = Path(output).resolve()
    with (output / ".index.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        index = read_json(output / "index.json")
        seen = set()
        for item in index["trajectories"]:
            if item["run_id"] not in seen:
                bundle_path = (output / item["json"]).resolve()
                if not bundle_path.is_relative_to(output):
                    raise ValueError("Task export must be inside output directory")
                add_index_run(index, read_json(bundle_path)["runs"][0])
                seen.add(item["run_id"])
            if task_config_dir:
                example_path = (Path(task_config_dir) / (item["task_path"] + ".json")).resolve()
                if not example_path.is_relative_to(Path(task_config_dir).resolve()):
                    raise ValueError("Task example must be inside task_config_dir")
                item.update(task_facets(read_json(example_path)))
        write_json(output / "index.json", index)
        write_text(output / "index.html", index_html(index))
    return {"runs": len(seen), "episodes": len(index["trajectories"])}


def read_evaluator_source(path):
    if not path:
        return None
    path = Path(path).resolve()
    text = path.read_text(encoding="utf-8")
    node = next(n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef) and n.name == "evaluate")
    return dict(path=str(path), sha256=digest(path.read_bytes()), line=node.lineno,
                code=ast.get_source_segment(text, node), provenance="Evaluator file read at export time; not a historical run snapshot")


def refresh_pages(output, task_config_dir, evaluator_source=None):
    """Add original criteria to saved exports without re-reading any screenshots."""
    import fcntl
    from urllib.parse import quote
    output, task_config_dir = Path(output).resolve(), Path(task_config_dir).resolve()
    source = read_evaluator_source(evaluator_source)
    with (output / ".index.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        index = read_json(output / "index.json")
        manifest = read_json(output / "manifest.json")
        root = Path(manifest["root"]).resolve()
        pages = {item["json"]: item for item in index["trajectories"]}
        for relative, item in pages.items():
            path = (output / relative).resolve()
            example_path = (task_config_dir / (item["task_path"] + ".json")).resolve()
            if not path.is_relative_to(output) or not example_path.is_relative_to(task_config_dir):
                raise ValueError("Export/config path escapes its declared directory")
            bundle, example = read_json(path), read_json(example_path)
            example["_criteria_source"] = dict(path=str(example_path), sha256=digest(example_path.read_bytes()),
                provenance="Current benchmark configuration; historical run did not save a configuration snapshot")
            trace = bundle["trace_catalog"][-1]
            frames = [f for f in bundle["trace_steps"] if f["trace_id"] == trace["id"]]
            last = frames[-1]["actions"][-1]["action"] if frames else None
            evidence = evaluation_evidence(example, last, trace["score"])
            evidence["script"] = source
            for key, name in [("result_file", "result.txt"), ("runtime_log", "runtime.log")]:
                original = (Path(item["run"]) / item["task_path"] / name).resolve()
                if original.is_file() and original.is_relative_to(root):
                    asset = original.relative_to(root).as_posix()
                    manifest["assets"][asset] = str(original)
                    evidence[key] = "/assets/" + quote(asset, safe="/")
            trace["evaluation"] = evidence
            add_graphs(bundle)
            write_json(path, bundle)
            write_text(output / item["html"].split("#")[0], task_html(bundle, relative, output))
        write_json(output / "manifest.json", manifest)
    return {"pages": len(pages)}


def refresh_outputs(config):
    """One command regenerates all existing task pages and the shared index."""
    pages = refresh_pages(config["output_dir"], config["task_config_dir"], config.get("evaluator_source"))
    index = refresh_index(config["output_dir"], config["task_config_dir"])
    return {"pages": pages["pages"], **index}


class RenderBusy(RuntimeError):
    pass


def render_task(task_dir, run_dir, config, example=None, runtime_args=None, include_signals=True, processing_error=None, wait_for_lock=True):
    from sft.analysis.attention_download import locked
    task, run, output = Path(task_dir).resolve(), Path(run_dir).resolve(), Path(config['output_dir']).resolve()
    run_id = 'run-' + digest((config['source'] + ':' + str(run)).encode())[:32]
    key = digest((run_id + ':' + task.relative_to(run).as_posix()).encode())[:32]
    with locked(output / '.task-locks' / (key + '.lock'), wait=wait_for_lock) as acquired:
        if not acquired:
            raise RenderBusy('This task already has an exporter')
        return _render_task(task, run, config, example, runtime_args, include_signals, processing_error)


def _render_task(task_dir, run_dir, config, example=None, runtime_args=None, include_signals=True, processing_error=None):
    import fcntl  # Evaluation runs in WSL; flock also works on the Mac.
    collection = config.get("collection", "eval")
    if collection not in {"eval", "test"}:
        raise ValueError("collection must be eval or test")
    from sft.analysis.retention import POLICIES, RenderedArchive, finish_cleanup, read_archive_record
    policy = config.get("raw_retention", "keep")
    if policy not in POLICIES:
        raise ValueError("Unknown raw_retention policy")
    root = Path(config["results_root"]).resolve()
    task_dir, run_dir = Path(task_dir).resolve(), Path(run_dir).resolve()
    if not task_dir.is_relative_to(run_dir) or not run_dir.is_relative_to(root):
        raise ValueError("Task/run must be inside configured results_root")
    output = Path(config["output_dir"]).resolve()
    run_id = "run-" + digest((config["source"] + ":" + str(run_dir)).encode())[:32]
    task_key = digest((run_id + ":" + task_dir.relative_to(run_dir).as_posix()).encode())[:32]
    if (output / "retention" / (task_key + ".json")).exists():
        # A previously selected cleanup policy cannot restore deleted raw tensors.
        receipt = read_json(output / "retention" / (task_key + ".json"))
        if policy == "keep" and receipt["status"] != "deleted":
            return receipt["entries"]
        return finish_cleanup(task_dir, output, task_key)
    if include_signals:
        from sft.analysis.attention_download import task_ready
        task_ready(task_dir)
    if example is not None and hasattr(example, "to_dict"):
        from sft.analysis.capture import task_metadata
        example = task_metadata(example)
    if output.is_relative_to(root):
        raise ValueError("Keep graph output outside the read-only results_root")
    if not (task_dir / "traj.jsonl").is_file():
        return None  # Setup failures may have no trajectory to inspect.
    if example is None and config.get("task_config_dir"):
        examples_root = Path(config["task_config_dir"]).resolve()
        example_path = (examples_root / (task_dir.relative_to(run_dir).as_posix() + ".json")).resolve()
        if not example_path.is_relative_to(examples_root):
            raise ValueError("Task example must be inside task_config_dir")
        example = read_json(example_path)
    if example is None:
        example = read_json(task_dir / "capture" / "task.json")
    if example is None:
        # Older captured tasks already have this exact metadata in their event log.
        from sft.analysis.visual_signals import read_rows
        events = [row for _, row in read_rows(task_dir / "capture" / "events.jsonl")]
        example = next((e["example"] for e in reversed(events) if e.get("type") == "task_start"), None)
        recorded = next((e.get("task_source") for e in reversed(events) if e.get("type") == "evaluation_start"), None)
        if example and not example.get("evaluator") and recorded and recorded.get("code"):
            import textwrap
            names = [n.name for n in ast.parse(textwrap.dedent(recorded["code"])).body if isinstance(n, ast.ClassDef)]
            example = {**example, "_criteria_source": recorded, "evaluator": {
                "func": (names[0]+".evaluate") if names else "Recorded evaluator", "task_class_source": recorded["code"]}}
    if example is not None:
        example = {**example, "domain": example.get("domain") or task_dir.parent.name}
    run_id = "run-" + digest((config["source"] + ":" + str(run_dir)).encode())[:32]
    task_key = digest((run_id + ":" + task_dir.relative_to(run_dir).as_posix()).encode())[:32]
    archive = RenderedArchive(task_dir, output, task_key, resume=config.get("resume_render", True)) if include_signals and policy == "delete-after-export" and (task_dir / "visual_signals.jsonl").is_file() else None
    signal_number = 0
    def save_signal(frame):
        nonlocal signal_number
        relative = f"signals/{task_key}-{signal_number}.json"
        if archive:
            archive.save(frame, relative)
            signal_number += 1
            return
        signal = dict(frame["signals"])
        raw = {key: signal.pop(key) for key in ("api_response", "input_token_ids", "request") if key in signal}
        if raw:
            raw_relative = relative.removesuffix(".json") + "-raw.json"
            write_json(output / raw_relative, raw)
            signal.update(raw_details_url=raw_relative, raw_fields=list(raw),
                          input_token_count=len(raw["input_token_ids"]) if isinstance(raw.get("input_token_ids"), list) else None)
        write_json(output / relative, signal)
        frame.update(signals=None, signals_url=relative)
        signal_number += 1
    def load_signal(relative):
        path = (output / relative).resolve()
        if not path.is_relative_to(output):
            raise ValueError("Signal file escapes output directory")
        signal = read_json(path)
        raw_path = signal.get("raw_details_url")
        if raw_path:
            raw_path = (output / raw_path).resolve()
            if not raw_path.is_relative_to(output):
                raise ValueError("Raw signal file escapes output directory")
            signal.update(read_json(raw_path))
        if signal.get("raw_details_ref"):
            original = read_archive_record(output, signal["raw_details_ref"])
            signal.update({key: original[key] for key in ("api_response", "input_token_ids", "request") if key in original})
        return signal
    try:
        bundle = export_runs(root, [str(run_dir.relative_to(root))], config["source"],
                             "/assets",
                             legacy_name=config.get("run_aliases", {}).get(run_dir.relative_to(root).as_posix()),
                             task_dirs={task_dir}, task_metadata=example, runtime_args=runtime_args, signal_sink=save_signal, include_signals=include_signals,
                             attention_sink_factory=archive.begin if archive else None,
                             attention_cache=archive.restore if archive else None)
        from sft.analysis.visual_signals import validate_bundle
        bundle["validation"] = validate_bundle(bundle, task_dir, config.get("capture"), signal_loader=load_signal)
        if not include_signals:
            if processing_error:
                bundle["validation"]["errors"].append("Visual-signal processing failed: " + processing_error)
            bundle["validation"]["status"] = "failed" if bundle["validation"]["errors"] else "processing"
            for frame in bundle["trace_steps"]:
                if processing_error:
                    frame.update(signal_status="failed", signal_reason="Visual-signal processing failed: " + processing_error)
        for trace in bundle["trace_catalog"]:
            if "evaluation" in trace:
                trace["evaluation"]["script"] = read_evaluator_source(config.get("evaluator_source"))
        task_path = task_dir.relative_to(run_dir).as_posix()
        run = bundle["runs"][0]
        bundle["partial_tasks"] = [{"run_id": run["id"], "task_path": task_path}]
        task_key = digest((run["id"] + ":" + task_path).encode())[:32]
        output.mkdir(parents=True, exist_ok=True)
        # One local file lock serializes parallel completions and idempotent re-renders.
        with (output / ".index.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            manifest = read_json(output / "manifest.json", {"schema_version": 1, "root": str(root), "assets": {}})
            if manifest["root"] != str(root):
                raise ValueError("An output directory must belong to one results_root")
            # Publish image routes before pages/index can reference the new files.
            manifest["assets"].update(bundle["assets"])
            write_json(output / "manifest.json", manifest)
            bundle_path = output / "tasks" / (task_key + ".json")
            add_graphs(bundle)
            write_json(bundle_path, bundle)
            write_json(output / "validation" / (task_key + ".json"), bundle["validation"])
            page_name = "task-" + task_key + ".html"
            write_text(output / page_name, task_html(bundle, str(bundle_path.relative_to(output)), output))
            entries = []
            for trace in bundle["trace_catalog"]:
                entries.append({**trace, "html": page_name + "#episode=" + str(trace["episode"]),
                                "json": str(bundle_path.relative_to(output)),
                                "pipeline_validation": bundle["validation"]["status"],
                                "collection": collection,
                                "canonical_name": run["canonical_name"], "source": config["source"]})
            index = read_json(output / "index.json", {"schema_version": 1, "trajectories": []})
            index["trajectories"] = [row for row in index["trajectories"]
                                     if (row["run_id"], row["task_path"]) != (run["id"], task_path)] + entries
            add_index_run(index, run)
            write_json(output / "index.json", index)
            write_text(output / "index.html", index_html(index))
        if archive:
            archive.finalize(bundle, entries)
        return entries
    finally:
        if archive:
            archive.close()


def queue_task(task_dir, run_dir, config, example=None, runtime_args=None):
    """Publish a small durable ready record. No parsing, image decode or rendering."""
    from sft.analysis.capture import task_metadata
    from sft.analysis.visual_signals import safe_metadata
    task_dir, run_dir = Path(task_dir).resolve(), Path(run_dir).resolve()
    root = Path(config["results_root"]).resolve()
    if not task_dir.is_relative_to(run_dir) or not run_dir.is_relative_to(root):
        raise ValueError("Ready task/run must belong to results_root")
    key = digest((config["source"]+":"+str(task_dir)).encode())[:32]
    path = Path(config["output_dir"]).resolve() / "pending" / (key+".json")
    job = dict(version=uuid.uuid4().hex, status="pending", task_dir=str(task_dir), run_dir=str(run_dir),
               config=safe_metadata(config), example=task_metadata(example) if example is not None else None,
               runtime_args=safe_metadata(runtime_args), ready_at=time.time())
    with job_lock(path):
        write_json(path, job)
    return path


@contextmanager
def job_lock(path):
    """Protect the short ready-record update, never the expensive render."""
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _process_job(payload):
    from sft.analysis.attention_download import DownloadPending
    path, job, config = payload
    path = Path(path)
    report = {"processed": 0, "failed": 0, "invalid": 0, "pending_newer_version": 0}
    if config.get('_stop_path') and Path(config['_stop_path']).exists():
        return {**report, 'busy': 1}
    with job_lock(path):
        current = read_json(path)
        if current['version'] != job['version']:
            report['pending_newer_version'] = 1
            return report
        if current.get('processed_version') == job['version'] and not config.get('_retry_failed'):
            return report
    try:
        if any(Path(job["config"][k]).resolve() != Path(config[k]).resolve() for k in ("output_dir", "results_root")):
            raise ValueError("Ready record belongs to another results/output root")
        entries = render_task(job["task_dir"], job["run_dir"], job["config"], job["example"], job["runtime_args"], wait_for_lock=False)
        job.update(status="processed" if entries else "no_trajectory", entries=len(entries or []))
        if any(e.get("pipeline_validation") == "failed" for e in entries or []):
            job["status"] = "validation_failed"
            report["invalid"] += 1
        job.pop("error", None)
        report["processed"] += 1
    except RenderBusy:
        report['busy'] = 1
        return report
    except DownloadPending as exc:
        job.update(status="waiting_for_attention", download_note=str(exc))
        with job_lock(path):
            if read_json(path)["version"] == job["version"]:
                write_json(path, job)
        return report  # Keep processed_version unset; retry when files arrive.
    except Exception as exc:
        job.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        report["failed"] += 1
        # Preserve a usable graph and make failed enrichment explicit.
        if job.get("preview_version") == job["version"]:
            try:
                render_task(job["task_dir"], job["run_dir"], job["config"], job["example"],
                            job["runtime_args"], include_signals=False, processing_error=job["error"])
            except Exception:
                logging.getLogger("cua.export").exception("Could not update preview failure status")
    job.update(processed_version=job["version"], processed_at=time.time())
    # A newer rollout completion must not be overwritten by this older render.
    with job_lock(path):
        if read_json(path)["version"] == job["version"]:
            write_json(path, job)
        else:
            report["pending_newer_version"] += 1
    return report


def process_pending(config, retry_failed=False, previews_only=False):
    """One independent worker. Failed rendering can be retried from raw files."""
    import fcntl
    from sft.analysis.attention_download import DownloadPending
    output = Path(config["output_dir"]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"processed": 0, "failed": 0, "invalid": 0, "pending_newer_version": 0}
    with (output / (".preview.lock" if previews_only else ".postprocess.lock")).open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {**report, "busy": True}
        if not previews_only:
            process_pending(config, retry_failed, previews_only=True)
        jobs = []
        for path in sorted((output / "pending").glob("*.json")):
            with job_lock(path):
                job = read_json(path)
            if job.get("processed_version") == job["version"] and not (retry_failed and job["status"] in ("failed", "validation_failed")):
                continue
            if "raw_retention" in config:
                job["config"] = {**job["config"], "raw_retention": config["raw_retention"]}
            job['config'] = {**job['config'], **{k: config[k] for k in ('resume_render',) if k in config}}
            jobs.append((path, job))
        if previews_only:
            # Publish every queued trajectory before starting any expensive heatmap work.
            for path, job in jobs:
                if job.get("preview_version") == job["version"]:
                    continue
                try:
                    if any(Path(job["config"][k]).resolve() != Path(config[k]).resolve() for k in ("output_dir", "results_root")):
                        raise ValueError("Ready record belongs to another results/output root")
                    render_task(job["task_dir"], job["run_dir"], job["config"], job["example"], job["runtime_args"], include_signals=False, wait_for_lock=False)
                    job["preview_version"] = job["version"]
                    with job_lock(path):
                        if read_json(path)["version"] == job["version"]:
                            write_json(path, job)
                except RenderBusy:
                    continue
                except Exception as exc:
                    job["preview_error"] = f"{type(exc).__name__}: {exc}"
            return report
        workers = config.get('export_workers', 1)
        if type(workers) is not int or not 1 <= workers <= 4:
            raise ValueError('export_workers must be between 1 and 4')
        payloads = [(str(path), job, {**config, '_retry_failed': retry_failed}) for path, job in jobs]
        if workers == 1:
            results = map(_process_job, payloads)
            for result in results:
                for key, value in result.items(): report[key] = report.get(key, 0) + value
        elif payloads:
            from concurrent.futures import ProcessPoolExecutor
            from multiprocessing import get_context
            with ProcessPoolExecutor(max_workers=workers, mp_context=get_context('spawn')) as pool:
                for result in pool.map(_process_job, payloads):
                    for key, value in result.items(): report[key] = report.get(key, 0) + value
    return report


def wrap_task(function):
    if getattr(function, "_cua_capture_wrapped", False):
        return function
    signature = inspect.signature(function)
    @wraps(function)
    def completed(*args, **kwargs):
        from contextlib import ExitStack
        config_path = os.environ.get("CUA_INSPECTION_CONFIG")
        arguments = signature.bind(*args, **kwargs).arguments
        context = ExitStack()
        try:
            try:
                config = (read_json(Path(config_path)) or {}) if config_path else {}
                if config_path and config.get("capture", {}).get("enabled", True) and "agent" in arguments and "env" in arguments:
                    from sft.analysis.capture import Recorder
                    recorder = Recorder(arguments["example_result_dir"], config.get("capture", {}),
                                        vars(arguments["args"]), arguments.get("example"))
                    context.enter_context(recorder.attach(arguments["agent"], arguments["env"], arguments.get("example")))
            except Exception:
                context.close()
                logging.getLogger("cua.capture").exception("Capture setup failed; evaluation is unchanged")
            with context:
                return function(*args, **kwargs)
        finally:
            if config_path:
                try:
                    runtime = arguments["args"]
                    config = read_json(Path(config_path))
                    background = config.get('capture', {}).get('attention_download') == 'background'
                    callback = render_task if config.get("postprocess") == "inline" and not background else queue_task
                    callback(arguments["example_result_dir"], config.get("run_dir", runtime.result_dir),
                             config, arguments.get("example"), vars(runtime))
                except Exception:
                    logging.getLogger("cua.inspection").exception("Task post-processing handoff failed; evaluation outcome is unchanged")
    completed._cua_capture_wrapped = True
    return completed


def render_run(run_dir, config, panel=None, task_config_dir=None, expected_tasks=None):
    """Backfill a complete saved run with the same per-task pipeline."""
    run_dir = Path(run_dir).resolve()
    discovered = {(p.parent.parent.name, p.parent.name): p.parent for p in run_dir.rglob("traj.jsonl")}
    if panel:
        specification = read_json(Path(panel))
        if not isinstance(specification, dict) or not all(isinstance(v, list) for v in specification.values()):
            raise ValueError("Panel must map benchmark domains to task-ID lists")
        targets = [(domain, str(task)) for domain, tasks in specification.items() for task in tasks]
        if len(set(targets)) != len(targets):
            raise ValueError("Duplicate task IDs in panel")
    else:
        targets = sorted(discovered)
    if expected_tasks is not None and len(targets) != expected_tasks:
        raise ValueError(f"Expected {expected_tasks} tasks, found {len(targets)}")
    missing = [pair for pair in targets if pair not in discovered]
    if missing:
        raise ValueError(f"Missing trajectories for panel tasks: {missing}")
    errors, completed = [], 0
    for domain, task_id in targets:
        try:
            example = None
            if task_config_dir:
                example = read_json(Path(task_config_dir) / domain / (task_id + ".json"))
                if example is None:
                    raise ValueError("Original task configuration is missing")
                example = {**example, "domain": domain, "_criteria_source": {
                    "path": str(Path(task_config_dir) / domain / (task_id + ".json")),
                    "provenance": "Benchmark configuration supplied for backfill; not a historical run snapshot"}}
            render_task(discovered[(domain, task_id)], run_dir, config, example=example)
            completed += 1
        except Exception as exc:
            errors.append({"domain": domain, "task_id": task_id, "error": str(exc)})
        if (completed + len(errors)) % 10 == 0 or completed + len(errors) == len(targets):
            print(f"[{completed + len(errors)}/{len(targets)}] rendered={completed} errors={len(errors)}", flush=True)
    report = {"run": str(run_dir), "expected": len(targets), "rendered": completed, "errors": errors}
    if errors:
        raise RuntimeError(json.dumps(report, ensure_ascii=False))
    return report


BEGIN, END = "# BEGIN CUA TASK GRAPH HOOK", "# END CUA TASK GRAPH HOOK"


def install_hook(path, function="run_single_example"):
    path = Path(path).resolve()
    source = path.read_text(encoding="utf-8")
    if source.count(BEGIN) != source.count(END) or source.count(BEGIN) > 1:
        raise ValueError("Ambiguous existing hook; refusing to modify the harness")
    source = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", source, flags=re.S).rstrip() + "\n"
    node = next((n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == function), None)
    if node is None or not {"args", "example_result_dir"}.issubset({a.arg for a in node.args.args}):
        raise ValueError("Unsupported task function; expected args and example_result_dir parameters")
    block = f'''
{BEGIN}
if __import__("os").environ.get("CUA_INSPECTION_CONFIG"):
    try:
        import importlib.util as _cua_import
        _cua_spec = _cua_import.spec_from_file_location("cua_task_graph", {str(Path(__file__).resolve())!r})
        _cua_hook = _cua_import.module_from_spec(_cua_spec)
        _cua_spec.loader.exec_module(_cua_hook)
        {function} = _cua_hook.wrap_task({function})
    except Exception:
        __import__("logging").getLogger("cua.inspection").exception("Could not load task graph hook; evaluation remains available")
{END}
'''
    updated = source + block
    compile(updated, str(path), "exec")
    if path.read_text(encoding="utf-8") == updated:
        return
    backup = path.with_name(path.name + ".before-cua-graph")
    if not backup.exists():
        backup.write_bytes(path.read_bytes())
    temporary = path.with_name(path.name + ".cua-graph.tmp")
    temporary.write_text(updated, encoding="utf-8")
    temporary.chmod(path.stat().st_mode)
    temporary.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install", help="Install the disabled-by-default per-task callback once")
    install.add_argument("harness_file", type=Path)
    install.add_argument("--function", default="run_single_example")
    render = commands.add_parser("render", help="Re-render a completed task using the same pipeline")
    render.add_argument("--config", type=Path, required=True)
    render.add_argument("--run-dir", type=Path, required=True)
    render.add_argument("--task-dir", type=Path, required=True)
    bulk = commands.add_parser("render-run", help="Backfill all tasks in a saved evaluation, verifying the requested panel")
    bulk.add_argument("--config", type=Path, required=True)
    bulk.add_argument("--run-dir", type=Path, required=True)
    bulk.add_argument("--panel", type=Path)
    bulk.add_argument("--task-config-dir", type=Path)
    bulk.add_argument("--expected-tasks", type=int)
    pending = commands.add_parser("process-pending", help="Process saved ready tasks independently of rollout")
    pending.add_argument("--config", type=Path, required=True)
    pending.add_argument("--memory-limit-gib", type=float, default=4, help="Linux worker address-space limit; raw captures are retained on failure")
    pending.add_argument("--watch", action="store_true", help="Wait for further ready tasks; one worker per output directory")
    pending.add_argument("--export-workers", type=int)
    pending.add_argument("--download-workers", type=int)
    pending.add_argument("--resume-render", action=argparse.BooleanOptionalAction, default=None)
    pending.add_argument("--retry-producer-cleanup", action="store_true")
    pending.add_argument("--retry-failed", action="store_true", help="Retry failed processing once; never rerun a model")
    refresh = commands.add_parser("refresh-index", help="Refresh index UI/metadata without reprocessing screenshots")
    refresh.add_argument("output_dir", type=Path)
    refresh.add_argument("--task-config-dir", type=Path)
    all_outputs = commands.add_parser("refresh", help="Regenerate all saved pages and the index using one host config")
    all_outputs.add_argument("--config", type=Path, required=True)
    pages = commands.add_parser("refresh-pages", help="Refresh saved task pages and original evaluator criteria, without image reprocessing")
    pages.add_argument("output_dir", type=Path)
    pages.add_argument("--task-config-dir", type=Path, required=True)
    pages.add_argument("--evaluator-source", type=Path)
    serve = commands.add_parser("serve", help="Serve the standalone tool and its original screenshots")
    serve.add_argument("output_dir", type=Path)
    serve.add_argument("--port", type=int, default=8793)
    catalog = commands.add_parser("catalog", help="Serve one live index across existing viewers")
    catalog.add_argument("--config", type=Path, required=True)
    catalog.add_argument("--port", type=int, default=8793)
    for command_parser in (render, bulk, pending):
        command_parser.add_argument("--raw-retention", choices=("keep", "delete-after-export"), default=None,
            help="Keep raw captures (default), or retain rendered heatmaps/text and delete verified redundant raw artifacts")
    args = parser.parse_args(argv)
    def configuration():
        config = read_json(args.config)
        overrides = read_json(Path(config['output_dir']) / 'worker-options.json', {})
        allowed = {'export_workers', 'download_workers', 'resume_render', 'producer_cleanup'}
        if set(overrides) - allowed:
            raise ValueError('Unknown postprocessing worker option')
        config.update(overrides)
        for name in ('export_workers', 'download_workers', 'resume_render'):
            value = getattr(args, name, None)
            if value is not None: config[name] = value
        if args.command == 'process-pending':
            config['_stop_path'] = str(Path(config['output_dir']) / ('.worker-stop-' + str(os.getpid())))
        if getattr(args, "raw_retention", None) is not None:
            config["raw_retention"] = args.raw_retention
        return config
    if args.command == "catalog":
        from sft.analysis.trajectory_catalog import catalog_server
        server = catalog_server(args.config, args.port)
        print(f"Trajectory catalog: http://127.0.0.1:{server.server_port}/", flush=True)
        server.serve_forever()
    elif args.command == "serve":
        server = viewer_server(args.output_dir, args.port)
        print(f"Standalone trajectory debugger: http://127.0.0.1:{args.port}/", flush=True)
        server.serve_forever()
    elif args.command == "install":
        install_hook(args.harness_file, args.function)
        print(f"Installed task graph callback in {args.harness_file}; enable with CUA_INSPECTION_CONFIG")
    elif args.command == "render-run":
        print(json.dumps(render_run(args.run_dir, configuration(), args.panel, args.task_config_dir,
                                    args.expected_tasks), ensure_ascii=False, indent=2))
    elif args.command == "process-pending":
        from sft.analysis import attention_download as downloads
        for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'): os.environ[key] = '1'
        if sys.platform == "linux":
            import resource
            if args.memory_limit_gib <= 0:
                parser.error("--memory-limit-gib must be positive")
            limit = int(args.memory_limit_gib * 1024**3)
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        stop = threading.Event()
        config = configuration()
        import signal
        stop_path = Path(config['_stop_path'])
        stop_path.unlink(missing_ok=True)
        def stop_after_task(*unused):
            stop_path.touch()
            stop.set()
        signal.signal(signal.SIGTERM, stop_after_task)
        signal.signal(signal.SIGINT, stop_after_task)
        from sft.scripts.eval.cleanup_capture import sweep
        if args.retry_producer_cleanup:
            (Path(config['output_dir']) / '.producer-cleanup-blocked.json').unlink(missing_ok=True)
        cleanup_status = {'status': 'pending'}
        def cleanup_loop():
            while not stop.is_set():
                try:
                    cleanup_status.update(sweep(configuration()))
                except Exception as exc:
                    cleanup_status.update(status='blocked', error=str(exc))
                    logging.getLogger('cua.export').exception('Producer cleanup stopped; sources retained')
                    return
                stop.wait(10)
        cleaner = threading.Thread(target=cleanup_loop, daemon=True)
        cleaner.start()
        download_queue = config.get('capture', {}).get('download_queue')
        download_root = config['results_root']
        if args.retry_failed and download_queue:
            downloads.retry_failed(download_queue, download_root)
        download_errors = []
        def download_loop(slot):
            while not stop.is_set():
                try:
                    if not downloads.download_one(download_queue, download_root, slot, stop=stop):
                        stop.wait(1)
                except Exception as exc:
                    download_errors.append(f'{type(exc).__name__}: {exc}')
                    return
        download_workers = config.get('download_workers', 1)
        if type(download_workers) is not int or not 1 <= download_workers <= 4:
            raise ValueError('download_workers must be between 1 and 4')
        downloaders = [threading.Thread(target=download_loop, args=(slot,), daemon=True)
                       for slot in range(download_workers)] if download_queue else []
        for downloader in downloaders: downloader.start()
        def preview_loop():
            while not stop.wait(5):
                try:
                    process_pending(configuration(), previews_only=True)
                except Exception:
                    logging.getLogger("cua.export").exception("Preview publication failed")
        previews = threading.Thread(target=preview_loop, daemon=True)
        previews.start()
        failed = False
        try:
            while not stop.is_set():
                if download_errors:
                    raise RuntimeError('Attention download worker failed: ' + download_errors[0])
                report = process_pending(configuration(), args.retry_failed)
                failed = failed or bool(report['failed'] or report['invalid'])
                if not args.watch or report["processed"] or report["failed"] or report["invalid"]:
                    print(json.dumps(report), flush=True)
                if not args.watch and not downloads.has_pending(download_queue, download_root):
                    # The final file may finish while render_task is waiting.
                    # Drain once more before the controller can declare export done.
                    final = process_pending(configuration(), args.retry_failed)
                    if failed or final['failed'] or final['invalid']:
                        raise SystemExit(1)
                    if cleanup_status['status'] in ('idle', 'disabled', 'blocked', 'dry_run'):
                        break
                args.retry_failed = False
                stop.wait(5)
        finally:
            stop.set()
            previews.join()
            for downloader in downloaders: downloader.join()
            cleaner.join()
            stop_path.unlink(missing_ok=True)
    elif args.command == "refresh-index":
        print(json.dumps(refresh_index(args.output_dir, args.task_config_dir)))
    elif args.command == "refresh":
        print(json.dumps(refresh_outputs(configuration())))
    elif args.command == "refresh-pages":
        print(json.dumps(refresh_pages(args.output_dir, args.task_config_dir, args.evaluator_source)))
    else:
        entries = render_task(args.task_dir, args.run_dir, configuration())
        print(json.dumps(entries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
