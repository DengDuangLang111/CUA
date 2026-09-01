"""Grade CUA SFT targets with an adapted WebSTAR o4-mini step critic.

The command is resumable and append-only. It grades a calibration target file
by default; full-corpus grading requires the explicit `--all` safety flag. The
real neutral-build, raw-result, and task-set paths are required explicitly and
must share the same source names.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:  # production checkout is imported as `ostg`; local worktree uses `sft`
    from ostg.sft import traj
except ModuleNotFoundError:  # pragma: no cover - environment-dependent import
    from sft import traj

from .common import (StepKey, iter_jsonl, load_source_rows,
                     parse_named_paths, sha256_bytes, sha256_text)
from .prompt import STEP_JUDGE_PROMPT, prompt_sha256
from .visuals import annotate_action


SCORE_RE = re.compile(r"Expected\s+value\s*:\s*(10|[0-9])\b", re.IGNORECASE)


def parse_score(text):
    matches = SCORE_RE.findall(text or "")
    if not matches:
        raise ValueError("judge response has no final 'Expected value: N'")
    score = int(matches[-1])
    if not 0 <= score <= 10:
        raise ValueError(f"judge score outside 0..10: {score}")
    return score


def resolve_task_dir(base, key):
    """Resolve an exact raw trajectory directory without task-id-only joins."""
    base = Path(base)
    candidates = [
        base / key.domain / key.task_id,
        base / key.run / key.domain / key.task_id,
    ]
    candidates.extend(base.glob(f"*/{key.run}/{key.domain}/{key.task_id}"))
    found = []
    for path in candidates:
        if path.is_dir() and path not in found:
            found.append(path)
    if len(found) != 1:
        raise FileNotFoundError(
            f"{key.text()}: expected one raw task dir under {base}, found "
            f"{[str(path) for path in found]}")
    return found[0]


def load_instruction(tasks_base, key):
    tasks_base = Path(tasks_base)
    candidates = [
        tasks_base / "examples" / key.domain / f"{key.task_id}.json",
        tasks_base / key.domain / f"{key.task_id}.json",
    ]
    found = [path for path in candidates if path.is_file()]
    if len(found) != 1:
        raise FileNotFoundError(
            f"{key.text()}: expected one task JSON, found {found}")
    return json.loads(found[0].read_text(encoding="utf-8"))["instruction"]


def pre_action_image(task_dir, steps, index):
    path = (task_dir / "initial_state.png" if index == 0
            else task_dir / steps[index - 1].screenshot)
    if not path.is_file():
        raise FileNotFoundError(f"missing pre-action screenshot: {path}")
    return path


def model_visible_images(source_row, count):
    """Return the latest model-visible image paths when the source has them."""
    paths = []
    for message in source_row.sample.get("messages", []):
        for part in message.get("content", []):
            if part.get("type") == "image" and part.get("path"):
                path = Path(part["path"])
                if not path.is_absolute():
                    path = source_row.source_dir / path
                paths.append(path)
    latest = paths[-count:]
    return latest if len(latest) == count and all(path.is_file() for path in latest) else []


def data_url(png_bytes):
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")


def build_judge_messages(key, source_row, result_base, tasks_base,
                         max_screenshots=3, crop_size=200,
                         save_annotated=None):
    task_dir = resolve_task_dir(result_base, key)
    steps = traj.load_steps(task_dir)
    by_num = {step.num: (idx, step) for idx, step in enumerate(steps)}
    if key.step not in by_num:
        raise ValueError(f"{key.text()}: step absent from raw trajectory")
    index, current = by_num[key.step]
    meta = source_row.sample.get("meta") or {}
    orig_steps = meta.get("orig_steps")
    if orig_steps is not None and int(orig_steps) != len(steps):
        raise ValueError(
            f"{key.text()}: raw step count {len(steps)} != orig_steps "
            f"{orig_steps}")

    start = max(0, index - max_screenshots + 1)
    window_indices = list(range(start, index + 1))
    visible_paths = model_visible_images(source_row, len(window_indices))
    annotated = []
    for offset, step_index in enumerate(window_indices):
        step = steps[step_index]
        before = (visible_paths[offset] if visible_paths
                  else pre_action_image(task_dir, steps, step_index))
        full_png, crop_png = annotate_action(before, step.actions, crop_size)
        annotated.append((step.num, full_png,
                          crop_png if step_index == index else None))

    instruction = load_instruction(tasks_base, key)
    previous = [
        f"step {step.num}: " + " | ".join(step.actions)
        for step in steps[max(0, index - max_screenshots + 1):index]
    ]
    proposed = "\n".join(
        f"{position}. {action}"
        for position, action in enumerate(current.actions, 1)
    ) or "[No executed action]"
    intro = (
        f"USER_TASK:\n{instruction}\n\n"
        f"PREVIOUS_EXECUTED_ACTIONS:\n"
        f"{chr(10).join(previous) if previous else '[none]'}\n\n"
        f"PROPOSED_NEXT_ACTION_BUNDLE:\n{proposed}\n\n"
        "The images below are chronological. Each full screenshot is the "
        "state before its annotated action; the last full screenshot is the "
        "state before the proposed current step."
    )
    content = [{"type": "text", "text": intro}]
    image_hashes = []
    for number, full_png, crop_png in annotated:
        content.append({"type": "text", "text": f"Pre-action screenshot for step {number}:"})
        content.append({"type": "image_url",
                        "image_url": {"url": data_url(full_png)}})
        image_hashes.append(sha256_bytes(full_png))
        if crop_png is not None:
            content.append({"type": "text", "text": "Current action target crop:"})
            content.append({"type": "image_url",
                            "image_url": {"url": data_url(crop_png)}})
            image_hashes.append(sha256_bytes(crop_png))

    if save_annotated:
        safe = sha256_text(key.text())[:20]
        out_dir = Path(save_annotated) / safe
        out_dir.mkdir(parents=True, exist_ok=True)
        for number, full_png, crop_png in annotated:
            (out_dir / f"step_{number:03d}_annotated.png").write_bytes(full_png)
            if crop_png is not None:
                (out_dir / f"step_{number:03d}_crop.png").write_bytes(crop_png)

    return ([{"role": "system", "content": STEP_JUDGE_PROMPT},
             {"role": "user", "content": content}], {
                 "raw_task_dir": str(task_dir.resolve()),
                 "raw_actions": list(current.actions),
                 "input_image_sha256": image_hashes,
             })


def call_chat_completions(endpoint, key, model, messages,
                          max_completion_tokens=12000, retries=3):
    body = json.dumps({
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_completion_tokens,
    }).encode("utf-8")
    url = endpoint.rstrip("/") + "/chat/completions"
    request = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    last_error = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                payload = json.load(response)
            content = payload["choices"][0]["message"].get("content")
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "") for part in content
                    if isinstance(part, dict))
            if not content:
                raise ValueError("judge returned empty content")
            return str(content)
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"judge request failed after {retries} attempts: {last_error}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True,
                        help="neutral build as NAME=DIR; repeat per source")
    parser.add_argument("--result", action="append", required=True,
                        help="raw trajectory tree as NAME=DIR")
    parser.add_argument("--tasks", action="append", required=True,
                        help="task set as NAME=DIR")
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--targets", type=Path,
                              help="calibration/full target-key JSONL")
    target_group.add_argument("--all", action="store_true",
                              help="explicitly grade every source row")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pass-id", required=True)
    parser.add_argument("--model", default="o4-mini")
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--save-annotated", type=Path, default=None)
    args = parser.parse_args(argv)

    source_dirs = parse_named_paths(args.source, "--source")
    result_dirs = parse_named_paths(args.result, "--result")
    task_dirs = parse_named_paths(args.tasks, "--tasks")
    if set(source_dirs) != set(result_dirs) or set(source_dirs) != set(task_dirs):
        raise ValueError("--source, --result, and --tasks names must match exactly")
    index, source_reports = load_source_rows(source_dirs)

    if args.targets:
        target_keys = [StepKey.from_dict(row) for row in iter_jsonl(args.targets)]
    else:
        target_keys = sorted(index)
    if len(target_keys) != len(set(target_keys)):
        raise ValueError("target file contains duplicate step keys")
    missing = [key.text() for key in target_keys if key not in index]
    if missing:
        raise ValueError(f"target keys absent from sources: {missing[:5]}")
    if args.limit:
        target_keys = target_keys[:args.limit]

    done = set()
    if args.out.exists():
        for row in iter_jsonl(args.out):
            if row.get("pass_id") == args.pass_id and row.get("score") is not None:
                done.add(StepKey.from_dict(row))
    todo = [key for key in target_keys if key not in done]

    endpoint = args.endpoint or os.environ.get("OPENAI_BASE_URL") \
        or "https://api.openai.com/v1"
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY or --api-key is required")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    output = args.out.open("a", encoding="utf-8")
    lock = threading.Lock()
    failures = []
    completed = [0]

    def grade_one(key):
        source_row = index[key]
        messages, evidence = build_judge_messages(
            key, source_row, result_dirs[key.source_build],
            task_dirs[key.source_build], save_annotated=args.save_annotated)
        judge_text = None
        score = None
        parse_error = None
        for parse_attempt in range(3):
            judge_text = call_chat_completions(
                endpoint, api_key, args.model, messages)
            try:
                score = parse_score(judge_text)
                break
            except ValueError as exc:
                parse_error = exc
                if parse_attempt < 2:
                    time.sleep(2 * (parse_attempt + 1))
        if score is None:
            raise ValueError(f"judge never returned a valid score: {parse_error}")
        return {
            "schema_version": 1,
            "policy_version": "webstar-filter-v1",
            **key.as_dict(),
            "n_steps": int((source_row.sample.get("meta") or {}).get("n_steps") or 0),
            "terminal": int((source_row.sample.get("meta") or {}).get("step") or 0)
                        == int((source_row.sample.get("meta") or {}).get("n_steps") or -1),
            "score": score,
            "judge_text": judge_text,
            "grader_model": args.model,
            "pass_id": args.pass_id,
            "prompt_sha256": prompt_sha256(),
            "source_response_sha256": sha256_text(
                source_row.sample.get("response", "")),
            **evidence,
        }

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(grade_one, key): key for key in todo}
        for future in as_completed(futures):
            key = futures[future]
            try:
                row = future.result()
            except Exception as exc:  # keep failed keys absent so resume retries
                failures.append({"key": key.text(), "error": str(exc)[:500]})
                print(f"[FAIL] {key.text()}: {exc}")
                continue
            with lock:
                output.write(json.dumps(row, ensure_ascii=False) + "\n")
                output.flush()
                completed[0] += 1
                print(f"[{completed[0]}/{len(todo)}] {key.text()} score={row['score']}")
    output.close()

    report = {
        "pass_id": args.pass_id,
        "model": args.model,
        "prompt_sha256": prompt_sha256(),
        "source_reports": source_reports,
        "requested": len(target_keys),
        "already_done": len(done),
        "completed_now": completed[0],
        "failures": failures,
    }
    report_path = args.out.with_suffix(args.out.suffix + f".{args.pass_id}.report.json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False)
                           + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
