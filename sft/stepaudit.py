"""Step-level quality audit — judge metadata, never a filter.

    python -m ostg.sft.stepaudit RESULT_DIR --tasks TASKS_DIR \
        [--targets FILE.jsonl] [--strata terminal,recovery] \
        [--endpoint http://127.0.0.1:18020/v1] [--model qwen38-27b-local] \
        [--out stepaudit.jsonl] [--limit N]

For each targeted step the judge (the idle teacher serve) sees the task
instruction, the PRE-action screenshot, the step's think (truncated) and
executed actions, and the POST-action screenshot — the outcome evidence
that training samples never carry — and returns structured verdicts:

    action_grounded   0-2  does the action match what is on screen
    outcome_intended  0-2  did the post screenshot show the intended effect
    necessary         0-2  was this step needed for the task
    is_recovery       bool step recovers from an earlier failure
    lucky             bool success looks accidental
    note              free text (short)

Output is METADATA (stepaudit.jsonl) for curation/weighting decisions --
this module drops nothing by design (user directive 2026-08-17: audit
before any rewrite; quality checks ride the pipeline).
Targets: --targets takes a jsonl with domain/task_id/step (e.g. the
think_quarantine files); --strata picks terminal (last step) and/or
recovery (identical-run escapes) from every passing trajectory.
"""
import argparse
import base64
import json
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ostg.sft import traj

VERDICT_TOOL = {
    "name": "verdict",
    "description": "Report the step audit verdict.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action_grounded": {"type": "integer", "minimum": 0, "maximum": 2},
            "outcome_intended": {"type": "integer", "minimum": 0, "maximum": 2},
            "necessary": {"type": "integer", "minimum": 0, "maximum": 2},
            "is_recovery": {"type": "boolean"},
            "lucky": {"type": "boolean"},
            "note": {"type": "string"},
        },
        "required": ["action_grounded", "outcome_intended", "necessary",
                     "is_recovery", "lucky", "note"],
    },
}


def anthropic_cfg(model):
    from ostg import llm
    import os
    llm.load_env("/mnt/d/research/os-simple-taskgen-v8/.env")
    return {"model": model, "max_tokens": 1024, "thinking": False,
            "base": os.environ.get("PPAPI_BASE_URL", "https://app-us.ppapi.ai").rstrip("/"),
            "key": os.environ.get("PPAPI_API_KEY", "")}


def ask_anthropic(cfg, system_text, user_blocks, tool):
    from ostg import llm
    for i in range(3):
        try:
            r = llm.call([{"role": "user", "content": user_blocks}],
                         [{"type": "text", "text": system_text}], cfg, tool=tool)
            for blk in r.get("content", []):
                if blk.get("type") == "tool_use":
                    return blk["input"]
            return {"error": "no tool_use"}
        except Exception as e:  # noqa: BLE001
            if not getattr(e, "transient", False) or i == 2:
                return {"error": str(e)[:200]}
            time.sleep(10 * (i + 1))

THINK_RE = re.compile(r"<think>(.*?)</think>", re.S)

SYSTEM = (
    "You are auditing one step of a completed GUI-agent trajectory. "
    "Judge only from the evidence shown. Reply with ONE JSON object: "
    '{"action_grounded": 0-2, "outcome_intended": 0-2, "necessary": 0-2, '
    '"is_recovery": true/false, "lucky": true/false, "note": "<=25 words"}. '
    "0=no, 1=partly, 2=yes. No other text."
)


def b64(p):
    return base64.b64encode(Path(p).read_bytes()).decode()


def ask(endpoint, model, key, payload_msgs, retries=3, effort="low"):
    # judge runs the teacher template at LOW reasoning effort (user decision
    # 2026-08-17): grading needs looking, not deliberating; xhigh default
    # would triple latency for no rubric benefit.
    body = json.dumps({"model": model, "messages": payload_msgs,
                       "max_tokens": 4096, "temperature": 0.0,
                       "chat_template_kwargs": {"reasoning_effort": effort}}).encode()
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                out = json.load(r)["choices"][0]["message"]["content"]
            m = re.search(r"\{.*\}", out, re.S)
            return json.loads(m.group(0)) if m else {"error": out[:200]}
        except Exception as e:  # noqa: BLE001 -- retry then record
            if i == retries - 1:
                return {"error": str(e)[:200]}
            time.sleep(5 * (i + 1))


def load_instruction(tasks_dir, domain, task_id):
    p = Path(tasks_dir) / "examples" / domain / f"{task_id}.json"
    return json.loads(p.read_text(encoding="utf-8"))["instruction"]


def targets_from_strata(result_dir, strata):
    for rt in sorted(Path(result_dir).glob("*/*/result.txt")):
        td = rt.parent
        if traj.score(td) != 1.0:
            continue
        steps = traj.load_steps(td)
        if not steps:
            continue
        picks = set()
        if "terminal" in strata:
            picks.add(steps[-1].num)
        if "recovery" in strata:
            drops = traj.identical_runs(steps)
            for i, s in enumerate(steps):
                if i and (i - 1) in drops and i not in drops:
                    picks.add(s.num)
        for n in sorted(picks):
            yield td.parent.name, td.name, n


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("result_dir", type=Path)
    ap.add_argument("--tasks", type=Path, required=True)
    ap.add_argument("--targets", type=Path, default=None)
    ap.add_argument("--strata", default="")
    ap.add_argument("--endpoint", default="http://127.0.0.1:18020/v1")
    ap.add_argument("--model", default="qwen38-27b-local")
    ap.add_argument("--key", default=None)
    ap.add_argument("--out", type=Path, default=Path("stepaudit.jsonl"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--backend", choices=("qwen", "anthropic"), default="qwen")
    ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args(argv)

    import os
    key = a.key or os.environ.get("OPENAI_API_KEY") or "EMPTY"

    todo = []
    if a.targets:
        for line in a.targets.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                todo.append((r["domain"], r["task_id"], r["step"]))
    if a.strata:
        todo.extend(targets_from_strata(a.result_dir, a.strata.split(",")))
    if a.limit:
        todo = todo[:a.limit]

    done = set()
    if a.out.exists():
        for line in a.out.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["domain"], r["task_id"], r["step"]))

    cfg = anthropic_cfg(a.model) if a.backend == "anthropic" else None
    out_f = a.out.open("a", encoding="utf-8")
    lock = threading.Lock()
    n_ok = [0]

    def one(target):
        domain, task_id, num = target
        if (domain, task_id, num) in done:
            return
        td = a.result_dir / domain / task_id
        steps = traj.load_steps(td)
        by_num = {s.num: (i, s) for i, s in enumerate(steps)}
        if num not in by_num:
            return
        i, s = by_num[num]
        pre = td / steps[i - 1].screenshot if i else td / "initial_state.png"
        post = td / s.screenshot
        if not pre.is_file() or not post.is_file():
            return
        think = (THINK_RE.search(s.response) or [None, ""])[1]
        think = think[:1500] + ("…[truncated]" if len(think) > 1500 else "")
        texts = [
            "Task instruction: " + load_instruction(a.tasks, domain, task_id),
            f"Step {num}/{steps[-1].num}. Screenshot BEFORE the action:",
            "Agent's reasoning (may be truncated): " + think,
            "Executed action(s): " + " | ".join(s.actions),
            "Screenshot AFTER the action:",
        ]
        if a.backend == "anthropic":
            user = [{"type": "text", "text": texts[0]},
                    {"type": "text", "text": texts[1]},
                    {"type": "image", "source": {"type": "base64",
                     "media_type": "image/png", "data": b64(pre)}},
                    {"type": "text", "text": texts[2]},
                    {"type": "text", "text": texts[3]},
                    {"type": "text", "text": texts[4]},
                    {"type": "image", "source": {"type": "base64",
                     "media_type": "image/png", "data": b64(post)}}]
            verdict = ask_anthropic(cfg, SYSTEM, user, VERDICT_TOOL)
        else:
            user = [{"type": "text", "text": texts[0]},
                    {"type": "text", "text": texts[1]},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64(pre)}},
                    {"type": "text", "text": texts[2]},
                    {"type": "text", "text": texts[3]},
                    {"type": "text", "text": texts[4]},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64(post)}}]
            verdict = ask(a.endpoint, a.model, key,
                          [{"role": "system", "content": SYSTEM},
                           {"role": "user", "content": user}])
        row = {"domain": domain, "task_id": task_id, "step": num,
               "n_steps": steps[-1].num,
               "think_est_tokens": traj.think_est_tokens(s.response),
               "actions": s.actions, **{f"j_{k}": v for k, v in verdict.items()}}
        with lock:
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            out_f.flush()
            n_ok[0] += 1
            print(f"[{n_ok[0]}] {domain}/{task_id[:8]} step {num}: {verdict}")

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(one, todo))
    out_f.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
