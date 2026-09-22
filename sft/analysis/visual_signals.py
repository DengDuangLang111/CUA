"""Export saved OSWorld actions and recorded visual signals; no model calls.

See sft/plans/PLAN-20260914-visual-signal-monitoring.md for usage and schema.
"""
import argparse
import ast
import hashlib
import gzip
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
from urllib.parse import quote, unquote, urlsplit

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from sft.armname import ALIASES, FORMULA_OF
    from sft.data.traj import think_est_tokens, score
else:
    from ..armname import ALIASES, FORMULA_OF
    from ..data.traj import think_est_tokens, score


def read_json(path, default=None):
    path = Path(path)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    compressed = path.with_suffix(path.suffix + ".gz")
    if compressed.is_file():
        with gzip.open(compressed, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    return default


def iter_rows(path):
    """Read one JSONL record at a time, preserving physical line numbers."""
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("expected an object")
                except ValueError as exc:
                    raise ValueError(f"{path}:{number}: {exc}") from exc
                yield number, row


def read_rows(path):
    return list(iter_rows(path))


def signal_index(path):
    """Keep alignment metadata and seek offsets, not every step's token arrays."""
    rows = []
    if path.is_file():
        with path.open("rb") as stream:
            while True:
                offset = stream.tell()
                line = stream.readline()
                if not line:
                    break
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"{path}: expected an object at byte {offset}")
                rows.append({**{k: row.get(k) for k in ("episode", "step_num", "request_id",
                    "request_sha256", "response_sha256", "checkpoint", "backend_provenance")},
                    "_offset": offset})
    return rows


def initial_row(row):
    return row.get("type") == "initial_state" or "action" not in row and row.get("step_num") in (0, None)


def starts_episode(row, previous):
    if previous is None:
        return False
    number, prior = row.get("step_num"), previous.get("step_num")
    return (initial_row(row) or row.get("episode_id") is not None and row.get("episode_id") != previous.get("episode_id")
            or isinstance(number, (int, float)) and isinstance(prior, (int, float)) and
            (number < prior or number == prior and row.get("response") != previous.get("response") and not initial_row(previous)))


def safe_metadata(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {k: safe_metadata(v) for k, v in value.items()
                if not any(word in k.lower() for word in
                           ("password", "secret", "api_key", "authorization", "cookie", "access_token"))}
    if isinstance(value, list):
        return [safe_metadata(v) for v in value]
    return value


def digest(value):
    return hashlib.sha256(value).hexdigest()


def local_file(root, parent, name):
    if not name or not isinstance(name, str):
        return None
    path = (parent / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"File escapes result root: {name}")
    return path if path.is_file() else None


def dimensions(path):
    if path:
        with path.open("rb") as stream:
            header = stream.read(24)
        if header[:8] == b"\x89PNG\r\n\x1a\n" and len(header) == 24:
            return list(struct.unpack(">II", header[16:24]))
    return [None, None]


def mouse_marks(command, cursor=None):
    """Read literal executed pixel coordinates, never execute logged Python."""
    marks = []
    try:
        tree = ast.parse(command)
    except (SyntaxError, TypeError):
        return marks, None
    for statement in tree.body:
        call = statement.value if isinstance(statement, ast.Expr) else None
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name) and call.func.value.id == "pyautogui"):
            cursor = None
            continue
        name = call.func.attr
        if name not in ("click", "doubleClick", "tripleClick", "rightClick", "middleClick", "moveTo", "dragTo"):
            # Keyboard/scroll commands can change the screen; they do not move the pointer.
            if name not in ("typewrite", "write", "press", "hotkey", "keyDown", "keyUp", "scroll", "hscroll", "sleep"):
                cursor = None
            continue
        kwargs = {k.arg: k.value for k in call.keywords}
        try:
            xy = [ast.literal_eval(kwargs.get(key, call.args[i] if len(call.args) > i else None))
                  for i, key in enumerate(("x", "y"))]
        except (ValueError, TypeError):
            cursor = None
            continue
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in xy):
            cursor = None
            continue
        kind = "drag" if name == "dragTo" else "move" if name == "moveTo" else "click"
        mark = dict(type=kind, label=name, x=xy[0], y=xy[1])
        if kind == "drag" and cursor is not None:
            mark.update(fromX=cursor[0], fromY=cursor[1])
        marks.append(mark)
        cursor = xy
    return marks, cursor


def image_attention_stats(images, values_by_image, keep_weights):
    frames = []
    for image, values in zip(images, values_by_image):
        mass = sum(values)
        entropy = -sum((w / mass) * math.log(w / mass) for w in values if w > 0) if mass else None
        frame = dict(image_id=image["id"], token_count=len(values), frame_mass=mass,
                     mean_weight=mass / len(values) if values else None,
                     spatial_entropy_nats=entropy,
                     spatial_entropy_normalized=entropy / math.log(len(values)) if entropy is not None and len(values) > 1 else None)
        if keep_weights:
            frame["weights"] = values
        frames.append(frame)
    total = sum(f["frame_mass"] for f in frames)
    for frame in frames:
        frame["frame_share"] = frame["frame_mass"] / total if total else None
    entropy = -sum(f["frame_share"] * math.log(f["frame_share"]) for f in frames if f["frame_share"]) if total else None
    return dict(image_mass=total, frames=frames, image_entropy_nats=entropy,
                image_entropy_normalized=entropy / math.log(len(frames)) if entropy is not None and len(frames) > 1 else None)


def attention_analysis(record, task_dir=None, include_overviews=True, row_sink=None):
    """Decode each query once; validate fixed image mappings once per decision."""
    from sft.analysis.attention_store import read_row
    images, seen = record.get("images", []), set()
    for image in images:
        indices = image["key_indices"]
        if (len(indices) != image["token_count"] or
                any(type(i) is not int or i < 0 or i in seen for i in indices) or len(set(indices)) != len(indices)):
            raise ValueError("Invalid or overlapping image-token mapping")
        seen.update(indices)
    largest_key = max(seen, default=-1)
    total = len(record["output_token_ids"]) if record.get("output_token_ids") is not None else record.get("counts", {}).get("output", {}).get("value")
    groups = {}
    if include_overviews:
        for row in record.get("attention", []):
            groups.setdefault((row["layer"], row["head"]), []).append(row.get("output_index"))
    means = {key: [[0.0] * im["token_count"] for im in images] for key, positions in groups.items()
             if all(type(i) is int and i >= 0 and (type(total) is not int or i < total) for i in positions)
             and len(set(positions)) == len(positions)}
    summaries = []
    for row in record.get("attention", []):
        binary = "weights_ref" in row
        compact = row.get('weights_scope', 'full') == 'image_keys'
        if row.get('weights_scope', 'full') not in ('full', 'image_keys'):
            raise ValueError('Unknown attention weights scope')
        weights = read_row(row, task_dir) if binary else row["weights"]
        # Binary decoding guarantees float32 elements; do not repeat Python type checks per key.
        expected_count = sum(im['token_count'] for im in images) if compact else row['key_count']
        if (compact and row.get('stored_key_count') != expected_count) or len(weights) != expected_count or (not binary and not all(
                isinstance(w, (int, float)) and not isinstance(w, bool) for w in weights)):
            raise ValueError("Invalid attention weights/key_count")
        try:
            weights_sum = math.fsum(weights)
        except (ValueError, OverflowError) as exc:
            raise ValueError("Invalid attention weights/key_count") from exc
        if not math.isfinite(weights_sum) or min(weights, default=0) < 0:
            raise ValueError("Invalid attention weights/key_count")
        if largest_key >= row['key_count']:
            raise ValueError("Invalid or overlapping image-token mapping")
        if compact:
            full_sum = row.get('weights_sum')
            if not isinstance(full_sum, (float,int)) or not math.isfinite(full_sum) or full_sum < weights_sum - 1e-12:
                raise ValueError('Invalid full-context attention mass')
            weights_sum = full_sum
            values, offset = [], 0
            for image in images:
                end = offset + image['token_count']
                values.append(list(weights[offset:end])); offset = end
        else:
            values = [[weights[i] for i in image["key_indices"]] for image in images]
        summaries.append({**row, "weights_sum": weights_sum,
                          **image_attention_stats(images, values, keep_weights=not binary)})
        if row_sink:
            row_sink(summaries[-1], images, values)
        key = (row.get("layer"), row.get("head"))
        if key in means:
            count = len(groups[key])
            for accumulated, current in zip(means[key], values):
                for i, value in enumerate(current):
                    accumulated[i] += value / count
    overviews = []
    for (layer, head), values in means.items():
        positions = sorted(groups[layer, head])
        overviews.append(dict(image_attention_stats(images, values, keep_weights=True),
            weights_sum=math.fsum(v for image in values for v in image), layer=layer, head=head,
            aggregation="mean_raw_attention", output_indices=positions, output_total=total,
            complete=type(total) is int and positions == list(range(total))))
    return summaries, overviews


def attention_rows(record, task_dir=None):
    return attention_analysis(record, task_dir, include_overviews=False)[0]


def attention_overviews(record, task_dir=None):
    """Mean raw weights per layer/head, then recompute shares and entropy."""
    return attention_analysis(record, task_dir)[1]


def task_facets(task):
    """Index filters use original benchmark fields, never inferred task labels."""
    functions = task.get("evaluator", {}).get("func", [])
    return {"related_apps": task.get("related_apps", []),
            "evaluator_functions": functions if isinstance(functions, list) else [functions] if functions else []}


def evaluation_evidence(task, last_action, score_value):
    """Keep the evaluator contract separate from its unrecorded runtime inputs."""
    return dict(criteria=safe_metadata(task.get("evaluator", {})),
                criteria_source=task.get("_criteria_source") or "Task configuration supplied to the exporter",
                last_action=last_action, score=score_value,
                actual_inputs_status="not_recorded")


def export_runs(root, runs, source, asset_base, legacy_name=None, task_dirs=None, task_metadata=None, runtime_args=None, signal_sink=None, include_signals=True, attention_sink_factory=None, attention_cache=None):
    root = Path(root).resolve()
    if task_dirs is not None:
        task_dirs = {Path(task).resolve() for task in task_dirs}
    assets, catalog, steps, index = {}, [], [], []
    image_hashes = {}

    def image_hash(path):
        if path is None:
            return None
        if path not in image_hashes:
            hasher = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    hasher.update(chunk)
            image_hashes[path] = hasher.hexdigest()
        return image_hashes[path]

    def asset(path):
        if path is None:
            return None
        relative = path.relative_to(root).as_posix()
        assets[relative] = str(path)
        return asset_base.rstrip("/") + "/" + quote(relative, safe="/")

    for relative in runs:
        run = (root / relative).resolve()
        if not run.is_relative_to(root) or not run.is_dir():
            raise ValueError(f"Not a result directory under --root: {relative}")
        # Stable short addresses fit the viewer's 200-character focus limit.
        run_id = "run-" + digest((source + ":" + str(run)).encode())[:32]
        args = safe_metadata({**read_json(run / "args.json", {}), **(runtime_args or {})})
        boundary = safe_metadata(read_json(run / "MODEL_BOUNDARY.json", {}))
        version = safe_metadata(read_json(run / "version.json", {}))
        alias = legacy_name or args.get("arm") or boundary.get("arm") or args.get("model")
        canonical = boundary.get("canonical_name") or (ALIASES.get(alias) if isinstance(alias, str) else None)
        if alias in ALIASES.values():
            canonical = alias
        # Decode a registered canonical name only; never infer names from substrings of a path.
        corpus = canonical.split("-")[2].split("~")[0].split("@")[0] if canonical and any(m in canonical for m in ("-full-", "-lora-")) else None
        checkpoint = (boundary.get("checkpoint") or boundary.get("weights_reported_by_vllm")
                      or args.get("checkpoint") or args.get("model_path"))
        run_row = dict(id=run_id, source=source, path=str(run), relative_path=run.relative_to(root).as_posix(),
                       legacy_name=alias, canonical_name=canonical, checkpoint=checkpoint,
                       naming_source="Explicit per-run import alias" if legacy_name else "Saved run metadata",
                       corpus=corpus, corpus_formula=FORMULA_OF.get(corpus, corpus),
                       args=args, model_boundary=boundary, version=version, tasks=0, episodes=0,
                       completed_tasks=0, full_pass_tasks=0, sample_action_timestamp=None)
        index.append(run_row)
        trajectories = (run.rglob("traj.jsonl") if task_dirs is None else
                        (task / "traj.jsonl" for task in task_dirs if task.is_relative_to(run)))
        for trajectory in sorted(trajectories):
            if not trajectory.resolve().is_relative_to(root):
                raise ValueError(f"Trajectory escapes result root: {trajectory}")
            task_dir = trajectory.parent
            task_path = task_dir.relative_to(run).as_posix()
            task = safe_metadata(read_json(task_dir / "task.json", task_metadata or {}))
            signal_error = None
            try:
                signals = signal_index(task_dir / "visual_signals.jsonl") if include_signals else []
            except ValueError as exc:
                signals, signal_error = [], str(exc)
            if checkpoint is None:
                observed_checkpoints = {s["checkpoint"] for s in signals if s.get("checkpoint") and s.get("backend_provenance")}
                if len(observed_checkpoints) == 1:
                    checkpoint = observed_checkpoints.pop()
                    run_row.update(checkpoint=checkpoint, checkpoint_source="Recorded inference backend")
            captured = task_dir / "capture" / "trajectory.jsonl"
            raw_rows = read_rows(trajectory)
            capture_manifest = read_json(task_dir / "capture" / "manifest.json", {})
            if captured.is_file():
                prefix_length = capture_manifest.get("native_prefix_lines", 0)
                if prefix_length:
                    prefix = b"".join(trajectory.read_bytes().splitlines(keepends=True)[:prefix_length])
                    if digest(prefix) != capture_manifest["native_prefix_sha256"]:
                        raise ValueError("Original trajectory prefix changed after capture started")
                raw_rows = [r for r in raw_rows if r[0] <= prefix_length] + read_rows(captured)
            episode, previous, before, cursor, frames = -1, None, None, None, []
            episode_catalog, task_frames = [], []
            initial_file_fallback = False
            for line_number, row in raw_rows:
                initial = initial_row(row)
                number = row.get("step_num")
                explicit_episode = row.get("episode_id")
                restart = starts_episode(row, previous)
                if episode < 0 or restart:
                    episode += 1
                    before, cursor, frames = None, None, []
                    trace_id = "trace-" + digest((run_id + ":" + task_path + ":episode:" + str(episode)).encode())[:32]
                    entry = dict(id=trace_id, run_id=run_id, run=str(run), task_id=task_dir.name,
                                 task_path=task_path, episode=episode, episode_id=explicit_episode,
                                 title=task.get("instruction") or task_dir.name, instruction=task.get("instruction"),
                                 domain=task.get("domain"), model=canonical or alias, checkpoint=checkpoint,
                                 protocol=json.dumps(args, ensure_ascii=False), width=None, height=None,
                                 steps=0, actionCount=0, score=None, inspection=True,
                                 download=asset(captured if captured.is_file() else trajectory.resolve()),
                                 native_trajectory=asset(trajectory.resolve()), notes=[], ending=None, **task_facets(task))
                    catalog.append(entry)
                    episode_catalog.append(entry)
                    if episode == 0 and not initial:
                        before = local_file(root, task_dir, "initial_state.png")
                        initial_file_fallback = before is not None
                        if before:
                            entry["notes"].append("Initial observation is recorded separately in initial_state.png.")
                image = local_file(root, task_dir, row.get("screenshot_file") or row.get("initial_state"))
                if initial:
                    before = image
                    previous = row
                    continue
                if "action" not in row:
                    entry["notes"].append(f"Non-action row {line_number}; preserved in original JSONL.")
                    continue
                response = row.get("response")
                same_decision = bool(frames and number is not None and frames[-1]["step"] == number and frames[-1]["response"] == response)
                if not same_decision:
                    frame = dict(trace_id=trace_id, run_id=run_id, episode=episode, order=len(frames), step=number,
                                 response=response, request_id=row.get("request_id"), request_sha256=row.get("request_sha256"),
                                 actions=[], think_tokens_estimate=think_est_tokens(response) if isinstance(response, str) and "<think>" in response else None,
                                 signals=None, signal_source=asset(local_file(root, task_dir, "visual_signals.jsonl")),
                                 signal_status="unverified" if signal_error else "unavailable",
                                 signal_reason=signal_error or "No recorded visual signals for this decision.")
                    frames.append(frame)
                    frame["interventions"] = [v for _, v in read_rows(task_dir / "capture/interventions.jsonl")
                                              if v.get("parent_request_id") == frame["request_id"]]
                    steps.append(frame)
                    task_frames.append(frame)
                marks, cursor = mouse_marks(row["action"], cursor)
                if run_row["sample_action_timestamp"] is None:
                    run_row["sample_action_timestamp"] = row.get("action_timestamp")
                width, height = dimensions(before)
                frame["actions"].append(dict(action=row["action"], before=asset(before), after=asset(image),
                    before_sha256=image_hash(before),
                    timestamp=row.get("action_timestamp"), markers=marks, width=width, height=height,
                    app=row.get("app") or row.get("active_app"), row_number=line_number,
                    action_index=len(frame["actions"]), raw=safe_metadata(row)))
                entry.update(steps=len(frames), actionCount=entry["actionCount"] + 1,
                             width=width, height=height, ending=row["action"] if row["action"] in ("DONE", "FAIL") else None)
                before, previous = image, row
            # result.txt is one task-level final result, not a score for every appended episode.
            if initial_file_fallback and len(episode_catalog) > 1 and task_frames:
                # A shared initial_state.png may have been replaced by a later retry.
                first_action = task_frames[0]["actions"][0]
                first_action.update(before=None, before_sha256=None, width=None, height=None)
                episode_catalog[0]["notes"].append("Initial image unavailable for the old episode: the standalone file has no episode identity.")
            if episode_catalog:
                value = score(task_dir)
                episode_catalog[-1]["score"] = value if value is not None and math.isfinite(value) else None
                last_action = task_frames[-1]["actions"][-1]["action"] if task_frames else None
                evidence = evaluation_evidence(task, last_action, episode_catalog[-1]["score"])
                evidence.update(result_file=asset(local_file(root, task_dir, "result.txt")),
                                runtime_log=asset(local_file(root, task_dir, "runtime.log")))
                def evidence_assets(value):
                    if isinstance(value, dict):
                        mapped = {k: evidence_assets(v) for k, v in value.items()}
                        if value.get("sha256") and isinstance(value.get("path"), str):
                            path = local_file(root, task_dir, value["path"])
                            if path and image_hash(path) == value["sha256"]:
                                mapped["src"] = asset(path)
                        return mapped
                    if isinstance(value, list):
                        return [evidence_assets(v) for v in value]
                    return value
                events = [r for _, r in read_rows(task_dir / "capture" / "events.jsonl")
                          if r.get("type") in ("evaluation_start", "evaluator_call", "evaluator_error", "evaluation_result", "check")]
                if events:
                    evidence.update(actual_inputs_status="recorded", checks=evidence_assets(events))
                evidence["rich_result"] = read_json(task_dir / "result.json")
                evidence["phase_results"] = read_json(task_dir / "phase_results.json")
                evidence["events_file"] = asset(local_file(root, task_dir, "capture/events.jsonl"))
                episode_catalog[-1]["evaluation"] = evidence
                run_row["tasks"] += 1
                run_row["episodes"] += len(episode_catalog)
                run_row["completed_tasks"] += int(episode_catalog[-1]["score"] is not None)
                run_row["full_pass_tasks"] += int(episode_catalog[-1]["score"] == 1)
            for frame in task_frames:
                if not include_signals:
                    frame.update(signal_status="processing", signal_reason="Visual signals are being processed; the trajectory and screenshots are ready.")
                    continue
                candidates = [s for s in signals if s.get("episode") == frame["episode"] and s.get("step_num") == frame["step"]]
                if not candidates:
                    continue
                frame.update(signal_status="unverified", signal_reason="Signal identity or request alignment could not be verified.")
                # A later diagnostic enriches exactly the same request, never a different retry.
                candidates = [s for s in candidates if not frame["request_id"] or s.get("request_id") == frame["request_id"]]
                if candidates and len({(s.get("request_id"), s.get("request_sha256"), s.get("response_sha256")) for s in candidates}) == 1:
                    candidates = [candidates[-1]]
                if len(candidates) != 1:
                    frame["signal_reason"] = "More than one signal record matches this episode/step."
                    continue
                with (task_dir / "visual_signals.jsonl").open("rb") as stream:
                    stream.seek(candidates[0]["_offset"])
                    record = json.loads(stream.readline())
                checkpoint_matches = bool(checkpoint and record.get("checkpoint") == checkpoint)
                if not ((checkpoint_matches or not record.get("attention")) and frame["request_id"] and
                        record.get("request_id") == frame["request_id"] and frame["request_sha256"] and
                        record.get("request_sha256") == frame["request_sha256"] and isinstance(frame["response"], str) and
                        record.get("response_sha256") == digest(frame["response"].encode())):
                    continue
                try:
                    mapped = []
                    for info in record.get("images", []):
                        path = local_file(root, task_dir, info["path"])
                        if not path or digest(path.read_bytes()) != info.get("sha256"):
                            raise ValueError("Request-image bytes are missing or differ from the recorded hash")
                        boxes = info.get("patch_boxes")
                        if boxes is not None and (len(boxes) != info["token_count"] or any(
                            len(b) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1 for v in b)
                            or b[0] > b[2] or b[1] > b[3] for b in boxes)):
                            raise ValueError("Invalid normalized patch boxes")
                        mapped.append({**info, "src": asset(path)})
                    if len({i["id"] for i in mapped}) != len(mapped):
                        raise ValueError("Duplicate image occurrence IDs")
                    restored = attention_cache(record) if attention_cache else None
                    if restored is not None:
                        rows, overviews = restored
                    else:
                        row_sink = attention_sink_factory(record) if attention_sink_factory else None
                        rows, overviews = attention_analysis(record, task_dir, row_sink=row_sink)
                    frame["signals"] = {**evidence_assets(safe_metadata(record)), "images": mapped,
                                        "attention": evidence_assets(rows),
                                        "attention_overviews": overviews,
                                        "request_file": asset(local_file(root, task_dir, "capture/requests/"+str(record["request_id"])+".json"))}
                    frame.update(signal_status="matched", signal_reason="Request ID, request hash, response and image bytes match." +
                                 (" Checkpoint matches." if checkpoint_matches else " Checkpoint not verified; no attention is shown."))
                    if record.get("capture_errors"):
                        frame.update(signal_status="partial", signal_reason="Request matches; some model diagnostics failed. See capture errors.")
                except (KeyError, TypeError, ValueError, OSError) as exc:
                    frame["signal_reason"] = str(exc)
                if signal_sink and frame.get("signals"):
                    frame["_signal_offset"] = candidates[0]["_offset"]
                    signal_sink(frame)
                    frame.pop("_signal_offset", None)
                del record
    return dict(schema_version=1, root=str(root), assets=assets, runs=index, trace_catalog=catalog, trace_steps=steps)


def write_bytes(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name+".", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def write_json(path, value):
    """Atomic streaming serialization; never build another whole JSON in RAM."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name+".", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def validate_bundle(bundle, task_dir, capture_config=None, signal_loader=None):
    """Check real artifacts before publishing a task page; never change its score."""
    from PIL import Image
    errors, warnings, sizes = [], [], {}
    task_dir = Path(task_dir).resolve()
    config = capture_config or {}
    files = bundle["assets"]
    image_count = 0
    for relative, filename in files.items():
        path = Path(filename)
        if not path.is_file():
            errors.append(f"Missing asset: {relative}")
        elif path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"):
            try:
                with Image.open(path) as image:
                    image.load()
                    sizes[relative] = image.size
                image_count += 1
            except Exception as exc:
                errors.append(f"Image cannot be decoded: {relative}: {exc}")
    frames = bundle["trace_steps"]
    actions = [a for f in frames for a in f["actions"]]
    captured = (task_dir / "capture" / "manifest.json").exists()
    for action in actions:
        for side in ("before", "after"):
            url = action.get(side)
            if not url:
                (errors if action.get("raw", {}).get("decision_id") else warnings).append(f"Missing {side} screenshot at row {action['row_number']}")
                continue
            relative = unquote(urlsplit(url).path.removeprefix("/assets/"))
            if relative not in sizes:
                errors.append(f"Page image is not a decodable manifest asset: {url}")
    for frame in frames:
        new_frame = any(a.get("raw", {}).get("decision_id") for a in frame["actions"])
        signals = frame.get("signals")
        if signals is None and signal_loader and frame.get("signals_url"):
            signals = signal_loader(frame["signals_url"])
        if frame["signal_status"] == "processing":
            continue
        if captured and frame.get("request_id") and frame["signal_status"] not in ("matched", "partial"):
            errors.append(f"Signal identity mismatch at step {frame['step']}: {frame['signal_reason']}")
        if not signals:
            if new_frame and config.get("backend") == "vllm":
                errors.append(f"No model signals at step {frame['step']}")
            continue
        errors.extend(f"Step {frame['step']} capture error: {e}" for e in signals.get("capture_errors", []))
        if signals.get("request"):
            try:
                from sft.analysis.capture import reconstruct_request
                reconstruct_request(signals, task_dir)
            except Exception as exc:
                errors.append(f"Request reconstruction failed at step {frame['step']}: {exc}")
        if config.get("backend") != "vllm":
            continue
        if not signals.get("backend_provenance"):
            errors.append(f"No instrumented backend evidence at step {frame['step']}")
            continue
        input_ids, output_ids = signals.get("input_token_ids", []), signals.get("output_token_ids", [])
        for row in signals.get("attention", []):
            if row["key_count"] != row["query"] + 1 or row["query"] != len(input_ids)-1+row["output_index"]:
                errors.append(f"Causal query/output alignment failed at step {frame['step']}")
            if abs((row['weights_sum'] if 'weights_sum' in row else sum(row['weights']))-1) > 1e-4:
                errors.append(f"Attention row is not normalized at step {frame['step']}")
        image_token_id = signals["backend_provenance"].get("model_config", {}).get("image_token_id")
        for image in signals["images"]:
            if image_token_id is not None and any(i >= len(input_ids) or input_ids[i] != image_token_id for i in image["key_indices"]):
                errors.append(f"Visual keys do not point to image tokens at step {frame['step']}")
        expected_attention = signals["request"].get("extra_body", {}).get("vllm_xargs", {}).get("cua_attention", True)
        if expected_attention and not signals.get("attention"):
            errors.append(f"Requested attention is missing at step {frame['step']}")
        scope=signals['backend_provenance'].get('capture_scope',{})
        if scope.get('output_indices')=='all':
            wanted=set(range(len(output_ids)))
            for layer in scope.get('layers',[]) if expected_attention else []:
                for head in scope.get('heads',[]):
                    positions=[r['output_index'] for r in signals.get('attention',[]) if r['layer']==layer and r['head']==head]
                    if set(positions)!=wanted or len(positions)!=len(wanted):
                        errors.append(f"Incomplete all-token attention at step {frame['step']}, layer {layer}, head {head}")
            positions=[r['output_index'] for r in signals.get('token_diagnostics',[])]
            if set(positions)!=wanted or len(positions)!=len(wanted):
                errors.append(f"Incomplete all-token entropy at step {frame['step']}")
        for row in signals.get("token_diagnostics", []):
            index = row["output_index"]
            if index >= len(output_ids) or output_ids[index] != row["token_id"]:
                errors.append(f"Output token identity mismatch at step {frame['step']}")
            if not math.isfinite(row["entropy_nats"]) or row["entropy_nats"] < -1e-6:
                errors.append(f"Invalid full-vocabulary entropy at step {frame['step']}")
    if captured:
        native_actions = [r["action"] for _, r in read_rows(task_dir / "traj.jsonl") if "action" in r]
        if native_actions != [a["action"] for a in actions]:
            errors.append("Captured action order/count differs from the native trajectory")
    events = [r for _, r in read_rows(task_dir / "capture" / "events.jsonl")]
    if events and events[-1].get("type") == "task_end":
        errors.extend(events[-1].get("errors", []))
    return dict(status="failed" if errors else "incomplete" if warnings else "passed", errors=errors, warnings=warnings,
                decisions=len(frames), actions=len(actions), decoded_images=image_count,
                verified_signal_decisions=sum(f["signal_status"] == "matched" for f in frames))


def merge_snapshot(snapshot, bundle):
    run_ids = {r["id"] for r in bundle["runs"]}
    queries = snapshot.setdefault("queries", {})
    partial = {(r["run_id"], r["task_path"]) for r in bundle.get("partial_tasks", [])}
    replaced_traces = {r["id"] for r in queries.get("trace_catalog", {}).get("rows", [])
                       if (r.get("run_id"), r.get("task_path")) in partial}
    for name, rows in (("inspection_runs", bundle["runs"]), ("trace_catalog", bundle["trace_catalog"]), ("trace_steps", bundle["trace_steps"])):
        query = queries.setdefault(name, {"rows": [], "source": {"name": "CUA inspection export", "type": "file"}})
        if partial and name != "inspection_runs":
            query["rows"] = [r for r in query["rows"] if (r.get("trace_id") or r.get("id")) not in replaced_traces] + rows
        else:
            query["rows"] = [r for r in query["rows"] if (r.get("run_id") or r.get("id")) not in run_ids] + rows
        files = set(query["source"].get("files", []))
        files.update(r["path"] for r in bundle["runs"])
        query["source"]["files"] = sorted(files)
    for run in queries["inspection_runs"]["rows"]:
        if run["id"] not in run_ids:
            continue
        episodes = [r for r in queries["trace_catalog"]["rows"] if r.get("run_id") == run["id"]]
        latest = {r["task_path"]: r for r in sorted(episodes, key=lambda r: r["episode"])}
        run.update(tasks=len(latest), episodes=len(episodes),
                   completed_tasks=sum(r["score"] is not None for r in latest.values()),
                   full_pass_tasks=sum(r["score"] == 1 for r in latest.values()))
    return snapshot


class AssetHandler(SimpleHTTPRequestHandler):
    """Expose only explicitly exported files, bound to loopback; no directory listing."""
    def translate_path(self, url):
        key = unquote(urlsplit(url).path).lstrip("/")
        path = self.server.assets.get(key)
        return path if path else str(self.server.missing_path)

    def list_directory(self, path):
        self.send_error(403)

    def send_head(self):
        manifest = getattr(self.server, "manifest_path", None)
        if manifest:
            stamp = manifest.stat().st_mtime_ns
            if stamp != self.server.manifest_stamp:
                bundle = read_json(manifest)
                root = Path(bundle["root"]).resolve()
                self.server.assets = {key: str(Path(path).resolve()) for key, path in bundle["assets"].items()
                                      if Path(path).resolve().is_relative_to(root)}
                self.server.manifest_stamp = stamp
        key = unquote(urlsplit(self.path).path).lstrip("/")
        if key not in self.server.assets:
            self.send_error(404)
            return None
        return super().send_head()


def asset_server(manifest, port=8788):
    manifest = Path(manifest).resolve()
    bundle = read_json(manifest)
    root = Path(bundle["root"]).resolve()
    server = ThreadingHTTPServer(("127.0.0.1", port), AssetHandler)
    server.assets = {key: str(Path(path).resolve()) for key, path in bundle["assets"].items()
                     if Path(path).resolve().is_relative_to(root)}
    server.missing_path = root / ".inspection-file-not-exported"
    server.manifest_path = manifest
    server.manifest_stamp = manifest.stat().st_mtime_ns
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export")
    exp.add_argument("--root", type=Path, required=True)
    exp.add_argument("--run", action="append", required=True, help="Run path relative to --root; repeat for separate runs")
    exp.add_argument("--source", required=True)
    exp.add_argument("--legacy-name", help="Explicit existing arm alias; otherwise use recorded arm/model")
    exp.add_argument("--asset-base", default="http://127.0.0.1:8788")
    exp.add_argument("--output", type=Path, required=True)
    exp.add_argument("--snapshot", type=Path, help="Merge into an existing viewer src/data.json")
    serve = sub.add_parser("serve")
    serve.add_argument("manifest", type=Path)
    serve.add_argument("--port", type=int, default=8788)
    merge = sub.add_parser("merge", help="Import an export into the existing viewer without rereading remote results")
    merge.add_argument("bundle", type=Path)
    merge.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "merge":
        bundle = read_json(args.bundle)
        if bundle.get("schema_version") != 1:
            parser.error("Unsupported inspection schema_version")
        write_json(args.snapshot, merge_snapshot(read_json(args.snapshot), bundle))
        print(f"Merged {len(bundle['runs'])} runs into {args.snapshot}")
        return
    if args.command == "serve":
        server = asset_server(args.manifest, args.port)
        print(f"Serving exported files on http://127.0.0.1:{args.port}", flush=True)
        server.serve_forever()
        return
    if args.output.resolve().is_relative_to(args.root.resolve()):
        parser.error("Keep generated output outside the read-only result root")
    bundle = export_runs(args.root, args.run, args.source, args.asset_base, args.legacy_name)
    write_json(args.output, bundle)
    if args.snapshot:
        write_json(args.snapshot, merge_snapshot(read_json(args.snapshot), bundle))
    print(f"Exported {len(bundle['runs'])} runs, {len(bundle['trace_catalog'])} episodes, "
          f"{sum(len(s['actions']) for s in bundle['trace_steps'])} actions to {args.output}")


if __name__ == "__main__":
    main()
