"""Canonicalise how a trajectory ends, so the corpus teaches an explicit stop.

    python -m ostg.sft.terminalfix RESULT_DIR --tasks TASKS_DIR \
        --targets curate_keep.jsonl [--targets curate_rescue.jsonl] \
        --out terminal_rewrite.jsonl [--endpoint ...] [--workers 8] [--dry N]

Why: measured on the corpus, only ~15% of trajectories end with an explicit
`terminate` call. 72% end with bare prose -- the harness turns "no tool call"
into DONE (mm_agents/qwen/actions.py: `if not pyautogui_code: append(DONE)`)
-- and 13% end with `call_user`, which the harness ALSO scores as DONE. The
4B student inherits that distribution: it terminated explicitly on 100% of
eval-50 before SFT and 0% after, while its cap-hit rate rose 28% -> 34%.
Stopping is the supervision we have least of, and it is taught as a negative
action ("stop calling tools"), which is exactly the signal that fails first
at inference.

What this writes: for each targeted trajectory, a REPLACEMENT for the final
step's target only. Everything earlier is untouched, so the trajectory's
causal chain is intact and the images are reused.

Two-part construction, deliberately not one canned string: the teacher writes
the JUSTIFICATION from the step's own context (short, task-specific), and the
tool call is appended DETERMINISTICALLY. A fixed template would put hundreds
of byte-identical responses into the corpus -- 6% of samples reciting one
sentence -- which teaches the sentence, not the decision.

Tail handling (--tail-policy):
  last-only   rewrite the final step, leave any trailing WAITs as they are
  truncate    also drop trailing steps that changed nothing (no screenshot
              delta) and move the terminate to the first such step, so the
              corpus stops where the work stopped rather than where the
              episode did
`traj.tail_run` already truncates a trailing run of >=5 identical steps at
build time; this is the finer-grained version aimed at 1-4 step stalls.
"""
import argparse
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ostg.sft import traj
from ostg.sft.stepaudit import ask, b64, load_instruction

SYSTEM = """You are writing the final assistant turn of a completed GUI-agent trajectory.

The task has been verified as done. You are given the task, the screen as it looks at the final step, and the actions that led here. Write ONLY the short justification the agent should give before it stops: name the concrete evidence on screen that the requested state exists -- the file that is listed, the value in the cell, the setting that reads as expected.

Rules: at most 60 words. No preamble, no restating the instruction, no markdown, no tool call (one is appended for you). Present tense, concrete nouns from this task. If the screen shows a verification the agent itself ran (a listing, a printed value), cite that."""

TERMINATE_CALL = """

<tool_call>
<function=computer_use>
<parameter=action>
terminate
</parameter>
<parameter=status>
success
</parameter>
</function>
</tool_call>"""


def canonical_response(reason):
    """<think>reason</think> + the deterministic terminate call."""
    reason = " ".join((reason or "").split())
    if not reason:
        reason = "The requested state is present on screen; the task is complete."
    return "<think>\n%s\n</think>%s" % (reason, TERMINATE_CALL)


def sha(p):
    try:
        return hashlib.md5(Path(p).read_bytes()).hexdigest()
    except OSError:
        return None


def stalled_tail(td, steps, max_look=8):
    """How many trailing steps changed nothing on screen.

    Compares consecutive screenshot bytes from the end. A stall means the
    agent kept acting (or waiting) after the world stopped responding --
    those steps teach nothing about finishing and are candidates to drop.
    """
    tail = [s for s in steps[-max_look:] if s.screenshot]
    shas = [sha(td / s.screenshot) for s in tail]
    n = 0
    for i in range(len(shas) - 1, 0, -1):
        if shas[i] and shas[i] == shas[i - 1]:
            n += 1
        else:
            break
    return n


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("result_dir", type=Path)
    ap.add_argument("--tasks", type=Path, required=True)
    ap.add_argument("--targets", type=Path, action="append", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--endpoint", default="http://127.0.0.1:18020/v1")
    ap.add_argument("--model", default="qwen38-27b-local")
    ap.add_argument("--key", default=None)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--effort", default="low")
    ap.add_argument("--tail-policy", choices=("last-only", "truncate"),
                    default="last-only")
    ap.add_argument("--dry", type=int, default=0)
    a = ap.parse_args(argv)

    import os
    key = a.key or os.environ.get("OPENAI_API_KEY") or "EMPTY"
    todo = []
    for p in a.targets:
        for line in p.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                todo.append((r["domain"], r["task_id"]))
    done = set()
    if a.out.exists():
        for line in a.out.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["domain"], r["task_id"]))
    todo = [k for k in dict.fromkeys(todo) if k not in done]
    if a.dry:
        todo = todo[:a.dry]
    print("%d trajectories to canonicalise" % len(todo))

    out_f = a.out.open("a", encoding="utf-8")
    lock = threading.Lock()
    n = [0]

    def one(k):
        domain, task_id = k
        td = a.result_dir / domain / task_id
        steps = traj.load_steps(td)
        if not steps:
            return
        keep_to = len(steps)
        stalled = stalled_tail(td, steps)
        if a.tail_policy == "truncate" and stalled:
            keep_to = max(1, len(steps) - stalled)
        last = steps[keep_to - 1]
        pre = td / (steps[keep_to - 2].screenshot if keep_to > 1
                    else "initial_state.png")
        post = td / last.screenshot if last.screenshot else pre
        if not post.is_file():
            return
        instr = load_instruction(a.tasks, domain, task_id)
        digest = "\n".join("step %d: %s" % (s.num, " | ".join(s.actions)[:110])
                           for s in steps[:keep_to])
        user = [{"type": "text", "text": "Task: " + instr},
                {"type": "text", "text": "Actions so far:\n" + digest},
                {"type": "text", "text": "Final screen:"},
                {"type": "image_url",
                 "image_url": {"url": "data:image/png;base64," + b64(post)}}]
        v = ask(a.endpoint, a.model, key,
                [{"role": "system", "content": SYSTEM},
                 {"role": "user", "content": user}],
                effort=a.effort)
        reason = v.get("reason") if isinstance(v, dict) else None
        if isinstance(v, dict) and "error" in v and not reason:
            # ask() returns {"error": raw} when the reply is not JSON -- which
            # is the normal case here, since we asked for prose.
            reason = str(v.get("error") or "")
        row = {"domain": domain, "task_id": task_id,
               "orig_steps": len(steps), "keep_to": keep_to,
               "stalled_tail": stalled, "tail_policy": a.tail_policy,
               "reason": " ".join(str(reason or "").split())[:600]}
        row["response"] = canonical_response(row["reason"])
        with lock:
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            out_f.flush()
            n[0] += 1
            print("[%d] %s/%s keep_to=%d/%d stall=%d :: %s"
                  % (n[0], domain, task_id[:8], keep_to, len(steps), stalled,
                     row["reason"][:70]))

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(one, todo))
    out_f.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
