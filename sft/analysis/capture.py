"""Task-scoped raw evidence capture. Wrappers return the original results unchanged.

Enabled by after_task's capture config. No model calls, scoring, or LLM summaries
are added by this module. Model diagnostics are a separate, explicit probe.
"""
import base64
import difflib
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import hashlib
import inspect
import io
import json
import logging
import os
from pathlib import Path
import re
import time
import uuid

from .visual_signals import digest, initial_row, read_json, read_rows, safe_metadata, starts_episode, write_bytes, write_json

ACTIVE = ContextVar("cua_capture", default=None)
LOG = logging.getLogger("cua.capture")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def append(path, value):
    import fcntl
    line = canonical(value).decode() + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())


def plain(value):
    if hasattr(value, "model_dump"):
        return plain(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return safe_metadata({str(k): plain(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return {"python_type": type(value).__qualname__, "repr": str(value)}


def source(function):
    try:
        path = Path(inspect.getfile(function)).resolve()
        code = inspect.getsource(function)
        return dict(path=str(path), file_sha256=digest(path.read_bytes()), code=code,
                    name=getattr(function, "__qualname__", type(function).__name__))
    except (OSError, TypeError):
        return dict(name=getattr(function, "__qualname__", str(function)), status="source_unavailable")


@contextmanager
def replace(obj, name, value):
    """Restore inherited methods without leaving a shadowing instance attribute."""
    owned = name in vars(obj)
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        if owned:
            setattr(obj, name, old)
        else:
            delattr(obj, name)


def capture_check(name, actual=None, expected=None, result=None, **details):
    """Explicit hook for custom V2 checks; records values, never runs a check."""
    recorder = ACTIVE.get()
    if recorder:
        recorder.try_record(lambda: recorder.event("check", name=name,
                            actual=recorder.evidence(actual), expected=recorder.evidence(expected),
                            result=plain(result), details=plain(details)))


class Recorder:
    def __init__(self, task_dir, config, runtime, example=None):
        self.task = Path(task_dir).resolve()
        self.directory = self.task / "capture"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.config, self.runtime = dict(config), plain(runtime)
        if os.environ.get('CUA_CAPTURE_KEY_FILE'):
            self.config['key_file'] = os.environ['CUA_CAPTURE_KEY_FILE']
        self.session = uuid.uuid4().hex
        manifest_path = self.directory / "manifest.json"
        manifest = read_json(manifest_path)
        if manifest is None:
            native = self.task / "traj.jsonl"
            data = native.read_bytes() if native.exists() else b""
            count, previous = 0, None
            for _, row in read_rows(native):
                if initial_row(row) or "action" in row:
                    count += previous is None or starts_episode(row, previous)
                    previous = row
            manifest = dict(native_prefix_lines=len(data.splitlines()), native_prefix_sha256=digest(data),
                            native_episode_count=count)
            write_json(manifest_path, manifest)
        prior = [r for _, r in read_rows(self.directory / "trajectory.jsonl")]
        self.episode = max([manifest["native_episode_count"]-1] + [r.get("episode_id", -1) for r in prior]) + 1
        self.step, self.attempt, self.phase = 0, 0, None
        self.response, self.last_request, self.before = None, None, None
        self.decision, self.pending_user = None, False
        self.sources, self.errors = {}, []
        boundary = read_json(Path(runtime.get("result_dir", self.task)) / "MODEL_BOUNDARY.json", {})
        self.checkpoint = (config.get("checkpoint") or boundary.get("checkpoint")
                           or boundary.get("weights_reported_by_vllm") or runtime.get("model_path")
                           or runtime.get("checkpoint"))
        self.started = time.perf_counter()
        self.event("task_start", runtime=self.runtime, example=plain(example), checkpoint=self.checkpoint)
        if example is not None:
            write_json(self.directory / "task.json", task_metadata(example))

    def event(self, kind, **fields):
        append(self.directory / "events.jsonl", dict(type=kind, session=self.session,
            episode=self.episode, phase=self.phase, decision_id=self.decision, step_num=self.step,
            timestamp=datetime.now(timezone.utc).isoformat(), **fields))

    def try_record(self, operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except Exception as exc:
            self.errors.append(f"{operation.__name__}: {type(exc).__name__}: {exc}")
            LOG.exception("Evidence capture failed; original evaluation is unchanged")
            return None

    def blob(self, data, suffix=".bin"):
        sha = digest(data)
        path = self.directory / "assets" / (sha + suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.stat().st_size != len(data) or digest(path.read_bytes()) != sha:
            write_bytes(path, data)
        return dict(path=path.relative_to(self.task).as_posix(), sha256=sha, bytes=len(data))

    def image(self, data):
        from PIL import Image
        with Image.open(io.BytesIO(data)) as img:
            info = self.blob(data, "." + (img.format or "bin").lower())
            return {**info, "width": img.width, "height": img.height}

    def observation(self, obs, register=True):
        image = self.image(obs["screenshot"]) if isinstance(obs, dict) and obs.get("screenshot") else None
        if image and register:
            self.sources.setdefault(image["sha256"], set()).add(self.step)
        return image

    def evidence(self, value):
        """Copy files before getters overwrite caches or reset the VM."""
        if isinstance(value, bytes):
            return self.blob(value)
        if isinstance(value, (str, Path)):
            try:
                path = Path(value)
                if path.is_file():
                    return {"original_path": str(path), **self.blob(path.read_bytes(), path.suffix or ".bin")}
            except (ValueError, OSError):
                pass
        if isinstance(value, dict):
            return safe_metadata({str(k): self.evidence(v) for k, v in value.items()})
        if isinstance(value, (list, tuple)):
            return [self.evidence(v) for v in value]
        return plain(value)

    def request(self, kwargs):
        self.attempt += 1
        images = []
        def archive(v):
            if isinstance(v, str) and v.startswith("data:image/"):
                header, encoded = v.split(",", 1)
                if not header.endswith(";base64"):
                    raise ValueError("Expected a base64 image data URI")
                data = base64.b64decode(encoded, validate=True)
                info = self.image(data)
                candidates = sorted(self.sources.get(info["sha256"], []))
                images.append(dict(id=f"image-{len(images)}", **info,
                    source_step=candidates[0] if len(candidates) == 1 else None,
                    source_step_candidates=candidates, source_mapping="byte_or_recorded_transform",
                    token_count=None, key_indices=[]))
                # Retain the exact spelling too: reconstruction is byte-identical, not a re-encoded guess.
                encoded_file = self.blob(v.encode(), ".data-uri")
                return {"$image": info["path"], "sha256": info["sha256"], "data_uri": encoded_file["path"]}
            if isinstance(v, dict):
                return {k: archive(x) for k, x in v.items()}
            if isinstance(v, list):
                return [archive(x) for x in v]
            return v
        request_id = f"cua-{self.session}-{self.step}-{self.attempt}"
        # Transport/authentication fields are excluded, never duplicated into artifacts.
        logical = {k: v for k, v in kwargs.items() if k not in ("extra_headers", "timeout")}
        saved = archive(logical)
        record = dict(schema_version=2, episode=self.episode, phase=self.phase, step_num=self.step,
            decision_id=self.decision, attempt=self.attempt, request_id=request_id,
            request_sha256=digest(canonical(logical)), checkpoint=self.checkpoint,
            origin="evaluation_client", request=saved, images=images, attention=[],
            output_tokens=[], counts={}, session=self.session)
        self.last_request = record
        write_json(self.directory / "requests" / (request_id + ".json"), record)
        return record

    def completion(self, create, resource, kwargs):
        if self.config.get("backend") == "vllm":
            kwargs = dict(kwargs)
            extra = dict(kwargs.get("extra_body") or {})
            extra.update(return_token_ids=True)
            xargs = dict(extra.get("vllm_xargs") or {})
            xargs["cua_capture"] = True
            xargs["cua_attention"] = self.step % int(self.config.get("attention_every", 1)) == 0
            extra["vllm_xargs"] = xargs
            kwargs.update(extra_body=extra, logprobs=True,
                          top_logprobs=int(self.config.get("top_logprobs", 5)))
        capture_started = time.perf_counter()
        request = self.try_record(self.request, kwargs)
        started = time.perf_counter()
        if request is not None:
            request["request_capture_seconds"] = started-capture_started
        wire = []
        # HTTPX hooks see SDK retries too; they never save authorization headers.
        http = getattr(getattr(resource, "_client", None), "_client", None)
        hooks = getattr(http, "event_hooks", None)
        def sent(req):
            wire.append(dict(retry_count=req.headers.get("x-stainless-retry-count"),
                             request_sha256=digest(req.content), sent_at=time.time()))
        def received(resp):
            item = dict(status=resp.status_code, request_id=resp.headers.get("x-request-id"))
            if not kwargs.get("stream"):
                item["body"] = self.blob(resp.read(), ".response.json")
            wire.append(item)
        def safe_sent(req): self.try_record(sent, req)
        def safe_received(resp): self.try_record(received, resp)
        if isinstance(hooks, dict):
            hooks.setdefault("request", []).append(safe_sent)
            hooks.setdefault("response", []).append(safe_received)
        try:
            result = create(resource, **kwargs)
            # Artifact GETs must not pass through the JSON-response capture hook.
            if isinstance(hooks, dict):
                hooks['request'].remove(safe_sent)
                hooks['response'].remove(safe_received)
            if request is not None:
                request.update(api_response=plain(result), client_latency_seconds=time.perf_counter()-started,
                               transport_attempts=wire)
                backend=request['api_response'].get('cua_signals')
                if backend and backend.get('attention_blobs'):
                    mode = self.config.get('attention_download', 'sync')
                    request['attention_download_mode'] = mode
                    if mode == 'background':
                        from .attention_download import enqueue
                        self.try_record(enqueue, self.task, backend, str(resource._client.base_url), self.config)
                    elif mode == 'sync':
                        self.try_record(self.download_attention, resource, backend)
                    else:
                        self.errors.append('Unknown attention_download mode: ' + str(mode))
                self.try_record(write_json, self.directory / "requests" / (request["request_id"] + ".json"), request)
            return result
        except Exception as exc:
            self.try_record(self.event, "request_error", request_id=request["request_id"] if request else None,
                            error_type=type(exc).__name__, error=str(exc), transport_attempts=wire,
                            client_latency_seconds=time.perf_counter()-started)
            raise
        finally:
            if isinstance(hooks, dict):
                if safe_sent in hooks['request']:hooks['request'].remove(safe_sent)
                if safe_received in hooks['response']:hooks['response'].remove(safe_received)

    def download_attention(self, resource, backend):
        """Explicit synchronous compatibility mode; background mode uses the queue."""
        from .attention_download import bind_paths, fetch_blob
        bind_paths(self.task, backend)
        client=resource._client
        headers={k:v for k,v in client.default_headers.items() if isinstance(v,(str,bytes))}
        for name,info in backend['attention_blobs'].items():
            url=str(client.base_url).rstrip('/')+'/cua-attention/'+name
            fetch_blob(client._client.stream, url, headers, self.task/info['path'], info)

    def trajectory(self, **fields):
        request = self.last_request or {}
        append(self.directory / "trajectory.jsonl", dict(episode_id=self.episode,
            phase_index=self.phase, step_num=self.step, decision_id=self.decision,
            request_id=request.get("request_id"), request_sha256=request.get("request_sha256"),
            response=self.response, action_timestamp=datetime.now(timezone.utc).isoformat(), **fields))

    def predict(self, original, instruction, obs, *args, **kwargs):
        self.step += 1
        self.attempt, self.last_request = 0, None
        self.decision = f"{self.session}:{self.step}"
        if self.pending_user:
            self.try_record(self.event, "user_reply", reply=plain(obs.get("user_response")))
            self.pending_user = False
        self.before = self.try_record(self.observation, obs)
        self.try_record(self.event, "decision_start", instruction=instruction,
                        observation=self.before, user_response=plain(obs.get("user_response")))
        if self.step == 1 or self.new_phase:
            self.try_record(self.trajectory, type="initial_state", screenshot_file=(self.before or {}).get("path"))
            self.new_phase = False
        result = original(instruction, obs, *args, **kwargs)
        self.response = result[0]
        self.finish_response(self.response)
        if not result[1]:
            self.pending_user = True
            self.try_record(self.trajectory, action="ASK_USER", question=self.response,
                            screenshot_file=(self.before or {}).get("path"))
        return result

    def finish_response(self, response):
        self.response = response
        if self.last_request is not None:
            record = self.last_request
            record["response_sha256"] = digest(self.response.encode())
            record["response"] = self.response
            api = record.get("api_response", {})
            record["counts"] = {"usage": api.get("usage"), "provenance": "server_returned"}
            record["output_tokens"] = (api.get("choices") or [{}])[0].get("logprobs") or []
            backend = api.get("cua_signals")
            if backend:
                record["capture_errors"] = backend.get("capture_errors", [])
                if "prompt_token_ids" in backend:
                    self.try_record(self.merge_backend, record, backend)
            self.try_record(write_json, self.directory / "requests" / (record["request_id"] + ".json"), record)
            self.try_record(append, self.task / "visual_signals.jsonl", record)

    def merge_backend(self, record, backend):
        """Bind server-side positions to the exact ordered client image occurrences."""
        if len(backend["images"]) != len(record["images"]):
            raise ValueError("Backend/client image occurrence counts differ")
        if backend["prompt_token_ids"] != record["api_response"].get("prompt_token_ids"):
            raise ValueError("Backend/API prompt token IDs differ")
        if self.checkpoint and self.checkpoint != backend["checkpoint"]:
            raise ValueError("Configured and actual backend checkpoints differ")
        record.update(checkpoint=backend["checkpoint"], origin=backend["origin"],
            backend_provenance={k: v for k, v in backend.items() if k not in
                                ("images", "attention", "token_diagnostics", "prompt_token_ids", "output_token_ids")},
            images=[{**sent, **processed} for sent, processed in zip(record["images"], backend["images"])],
            attention=backend["attention"], token_diagnostics=backend["token_diagnostics"],
            input_token_ids=backend["prompt_token_ids"], output_token_ids=backend.get("output_token_ids"),
            entropy_stage=backend["entropy_stage"])
        record["counts"].update(vision={"value": sum(i["token_count"] for i in record["images"]),
                                        "provenance": "actual_model_input_positions"})
        if backend.get("token_counts"):
            record["counts"].update(backend["token_counts"])

    def step_action(self, original, action, *args, **kwargs):
        started = time.perf_counter()
        result = original(action, *args, **kwargs)
        obs, reward, done, info = result
        image = self.try_record(self.observation, obs, False)
        self.try_record(self.trajectory, action=plain(action), reward=plain(reward), done=plain(done),
                        info=plain(info), screenshot_file=(image or {}).get("path"),
                        before_file=(self.before or {}).get("path"), step_latency_seconds=time.perf_counter()-started)
        self.before = image
        return result

    def evaluate(self, original, env, *args, **kwargs):
        self.try_record(lambda: self.event("evaluation_start", criteria=plain(getattr(env, "evaluator", None)),
                        function=source(original), task_source=source(type(getattr(env, "task_config", None)))))
        def observed(function, role):
            if isinstance(function, list):
                return [observed(f, f"{role}[{i}]") for i, f in enumerate(function)]
            if not callable(function):
                return function
            @wraps(function)
            def call(*a, **kw):
                actual_args = a[1:] if a and a[0] is env else a
                inputs = self.try_record(self.evidence, {"args": actual_args, "kwargs": kw})
                comparison = None
                if inputs and (role == "metric" or role.startswith("metric[")) and len(inputs["args"]) > 1:
                    comparison = {"actual": inputs["args"][0], "expected": inputs["args"][1]}
                elif inputs and role == "call_metric" and len(inputs["args"]) > 1:
                    comparison = {"actual": inputs["args"][1], "expected": inputs["kwargs"].get("expected_state")}
                if comparison is not None:
                    expected = json.dumps(comparison["expected"], ensure_ascii=False, indent=2).splitlines()
                    actual = json.dumps(comparison["actual"], ensure_ascii=False, indent=2).splitlines()
                    comparison["value_diff"] = "\n".join(difflib.unified_diff(expected, actual, fromfile="expected", tofile="actual", lineterm=""))
                started = time.perf_counter()
                try:
                    result = function(*a, **kw)
                    self.try_record(lambda: self.event("evaluator_call", role=role, function=source(function),
                                    inputs=inputs, comparison=comparison, result=self.evidence(result),
                                    latency_seconds=time.perf_counter()-started))
                    return result
                except Exception as exc:
                    self.try_record(self.event, "evaluator_error", role=role, inputs=inputs,
                                    error_type=type(exc).__name__, error=str(exc))
                    raise
            return call
        with ExitStack() as stack:
            for role in ("metric", "result_getter", "expected_getter"):
                if hasattr(env, role):
                    stack.enter_context(replace(env, role, observed(getattr(env, role), role)))
            controller = getattr(env, "controller", None)
            for name in ("execute_python_command", "execute_shell_command", "get_file", "get_terminal_output", "get_accessibility_tree"):
                if controller is not None and callable(getattr(controller, name, None)):
                    stack.enter_context(replace(controller, name, observed(getattr(controller, name), "controller."+name)))
            import sys
            for name, module in list(sys.modules.items()):
                if name.endswith("generated_task_utils") and module is not None:
                    for helper in ("get_evaluator_state", "call_metric"):
                        if hasattr(module, helper):
                            stack.enter_context(replace(module, helper, observed(getattr(module, helper), helper)))
            result = original(*args, **kwargs)
            self.try_record(lambda: self.event("evaluation_result", result=self.evidence(result)))
            return result

    @contextmanager
    def attach(self, agent, env, example=None):
        install_openai_hook()
        install_image_hooks()
        token = ACTIVE.set(self)
        self.new_phase = True
        self.try_record(self.event, "adapter_sources", agent=source(type(agent)), env=source(type(env)))
        try:
            with ExitStack() as stack:
                predict, step, evaluate = agent.predict, env.step, env.evaluate
                stack.enter_context(replace(agent, "predict", lambda *a, **kw: self.predict(predict, *a, **kw)))
                stack.enter_context(replace(env, "step", lambda *a, **kw: self.step_action(step, *a, **kw)))
                stack.enter_context(replace(env, "evaluate", lambda *a, **kw: self.evaluate(evaluate, env, *a, **kw)))
                if example is not None and callable(getattr(example, "get_phases", None)):
                    get_phases = example.get_phases
                    def phases(*a, **kw):
                        def wrap(phase):
                            original = phase["evaluate"]
                            @wraps(original)
                            def evaluate_phase(phase_env, *args, **kwargs):
                                return self.evaluate(original, phase_env, phase_env, *args, **kwargs)
                            return {**phase, "evaluate": evaluate_phase}
                        return [wrap(phase) for phase in get_phases(*a, **kw)]
                    stack.enter_context(replace(example, "get_phases", phases))
                if hasattr(agent, "reset"):
                    reset = agent.reset
                    def phase_reset(*a, **kw):
                        value = reset(*a, **kw)
                        if self.phase is not None and self.step:
                            self.episode += 1
                        self.phase = 1 if self.phase is None else self.phase + 1
                        self.new_phase = True
                        self.try_record(self.event, "agent_reset")
                        return value
                    stack.enter_context(replace(agent, "reset", phase_reset))
                yield self
        finally:
            self.try_record(self.event, "task_end", elapsed_seconds=time.perf_counter()-self.started,
                            errors=self.errors, decisions=self.step)
            ACTIVE.reset(token)


def install_openai_hook():
    """One context-local dispatcher for both existing non-streaming OpenAI clients."""
    try:
        from openai.resources.chat.completions import Completions
    except ImportError:
        return
    if getattr(Completions.create, "_cua_capture", False):
        return
    original = Completions.create
    @wraps(original)
    def create(resource, *args, **kwargs):
        recorder = ACTIVE.get()
        if recorder is None or args or kwargs.get("stream"):
            return original(resource, *args, **kwargs)
        return recorder.completion(original, resource, kwargs)
    create._cua_capture = True
    Completions.create = create


def install_image_hooks():
    """Record lineage at existing preprocessors, including compressed history."""
    import sys
    for name, module in list(sys.modules.items()):
        if not name.startswith("mm_agents.qwen") or module is None:
            continue
        function = getattr(module, "process_image", None)
        if not callable(function) or getattr(function, "_cua_capture", False):
            continue
        def wrap(function):
            @wraps(function)
            def process(data, *args, **kwargs):
                result = function(data, *args, **kwargs)
                recorder = ACTIVE.get()
                if recorder:
                    def lineage():
                        input_bytes = data if isinstance(data, bytes) else base64.b64decode(data)
                        output_bytes = result if isinstance(result, bytes) else base64.b64decode(result)
                        origins = recorder.sources.get(digest(input_bytes), set())
                        recorder.sources.setdefault(digest(output_bytes), set()).update(origins)
                    recorder.try_record(lineage)
                return result
            process._cua_capture = True
            return process
        setattr(module, "process_image", wrap(function))


def reconstruct_request(record, task_dir):
    root = Path(task_dir).resolve()
    def restore(v):
        if isinstance(v, dict) and "$image" in v:
            path = (root / v["data_uri"]).resolve()
            if not path.is_relative_to(root):
                raise ValueError("Image reference escapes task directory")
            uri = path.read_text()
            if digest(base64.b64decode(uri.split(",", 1)[1], validate=True)) != v["sha256"]:
                raise ValueError("Saved image hash mismatch")
            return uri
        if isinstance(v, dict):
            return {k: restore(x) for k, x in v.items()}
        if isinstance(v, list):
            return [restore(x) for x in v]
        return v
    value = restore(record["request"])
    if digest(canonical(value)) != record["request_sha256"]:
        raise ValueError("Reconstructed request hash mismatch")
    return value


def task_metadata(example):
    metadata = plain(example)
    if hasattr(example, "to_dict"):
        task_source = source(type(example))
        metadata["_criteria_source"] = task_source
        metadata["evaluator"] = metadata.get("evaluator") or {
            "func": type(example).__name__ + ".evaluate", "task_class_source": task_source.get("code")}
    return metadata
