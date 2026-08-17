"""Trajectory-level blind quality audit + judge calibration.

    # score every trajectory (pass AND fail), judge blind to the checker:
    python -m ostg.sft.trajaudit RESULT_DIR --tasks TASKS_DIR \
        [--endpoint http://127.0.0.1:18020/v1] [--model qwen38-27b-local] \
        [--out trajaudit.jsonl] [--limit N]

    # calibration report (AUC / separation / confusion vs checker truth):
    python -m ostg.sft.trajaudit --report trajaudit.jsonl

Design (user spec 2026-08-17): the judge grades completion 0-10 from the
trajectory evidence ALONE -- first/last frames + <=8 evenly spaced middle
screenshots + the full action sequence + one-line think digests. The
checker score is recorded in the output row but NEVER shown to the judge;
the report then measures whether the judge can tell success from failure
at all. A judge only earns curation duties by passing this exam.
Rubric anchors (in the system prompt) pin the scale so scores do not
drift to a noncommittal 7. Metadata, never a filter.
"""
import argparse
import json
import re
from pathlib import Path

from ostg.sft import traj
from ostg.sft.stepaudit import ask, b64, load_instruction, THINK_RE

SYSTEM = (
    "You are grading a completed GUI-agent trajectory from partial evidence: "
    "the task, a few screenshots (first, last, and evenly spaced), the full "
    "action list, and one-line reasoning digests. You are NOT told whether "
    "the task passed. Grade strictly by this scale -- completion: 0-2 clearly "
    "failed or wrong direction; 3-4 major gaps, unlikely complete; 5-6 partly "
    "complete or unverifiable from evidence; 7-8 likely complete with minor "
    "flaws (detours, redundancy); 9-10 clean completion with visible "
    "verification. Reply with ONE JSON object only: "
    '{"completion": 0-10, "efficiency": 0-3, "grounded": 0-3, '
    '"termination": 0-3, "confidence": 0-2, "note": "<=30 words"}.'
)

K_FRAMES = 10


def frames_for(td, steps):
    shots = [td / s.screenshot for s in steps if s.screenshot]
    init = td / "initial_state.png"
    picks = [init] if init.is_file() else shots[:1]
    if len(shots) > 1:
        idx = sorted({round(i * (len(shots) - 1) / (K_FRAMES - 2))
                      for i in range(K_FRAMES - 1)})
        picks += [shots[i] for i in idx]
    seen, out = set(), []
    for p in picks:
        if p.is_file() and p not in seen:
            seen.add(p)
            out.append(p)
    return out[:K_FRAMES]


def digest(steps):
    lines = []
    for s in steps:
        th = (THINK_RE.search(s.response) or [None, ""])[1]
        th = " ".join(th.split())[:90]
        lines.append(f"step {s.num}: {' | '.join(s.actions)[:120]}"
                     + (f"  // {th}" if th else ""))
    return "\n".join(lines)


def audit(a):
    import os
    key = a.key or os.environ.get("OPENAI_API_KEY") or "EMPTY"
    done = set()
    if a.out.exists():
        for line in a.out.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["domain"], r["task_id"]))
    out_f = a.out.open("a", encoding="utf-8")
    n = 0
    for rt in sorted(a.result_dir.glob("*/*/result.txt")):
        td = rt.parent
        domain, task_id = td.parent.name, td.name
        if (domain, task_id) in done:
            continue
        truth = traj.score(td)
        steps = traj.load_steps(td)
        if truth is None or not steps:
            continue
        user = [{"type": "text", "text": "Task: " +
                 load_instruction(a.tasks, domain, task_id)}]
        for p in frames_for(td, steps):
            user.append({"type": "image_url", "image_url":
                         {"url": "data:image/png;base64," + b64(p)}})
        user.append({"type": "text", "text":
                     f"Actions and reasoning digests ({len(steps)} steps):\n"
                     + digest(steps)})
        v = ask(a.endpoint, a.model, key,
                [{"role": "system", "content": SYSTEM},
                 {"role": "user", "content": user}])
        row = {"domain": domain, "task_id": task_id, "n_steps": len(steps),
               "truth": truth, **{f"j_{k}": val for k, val in v.items()}}
        out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
        out_f.flush()
        n += 1
        print(f"[{n}] {domain}/{task_id[:8]} truth={truth} -> {v}")
        if a.limit and n >= a.limit:
            break
    out_f.close()


def report(path):
    rows = [json.loads(l) for l in Path(path).read_text().splitlines()
            if l.strip() and "j_completion" in l]
    rows = [r for r in rows if isinstance(r.get("j_completion"), (int, float))]
    if not rows:
        print("no scored rows")
        return
    ok = [r["j_completion"] for r in rows if r["truth"] == 1.0]
    ko = [r["j_completion"] for r in rows if r["truth"] != 1.0]
    med = lambda v: sorted(v)[len(v) // 2] if v else float("nan")
    print(f"n={len(rows)}  pass={len(ok)} (mean {sum(ok)/max(1,len(ok)):.2f}, "
          f"median {med(ok)})  fail={len(ko)} "
          f"(mean {sum(ko)/max(1,len(ko)):.2f}, median {med(ko)})")
    pairs = wins = 0
    for a_ in ok:
        for b_ in ko:
            pairs += 1
            wins += 1 if a_ > b_ else (0.5 if a_ == b_ else 0)
    print(f"AUC = {wins/pairs:.3f}" if pairs else "AUC undefined")
    best = (0, -1)
    for t in range(11):
        acc = (sum(1 for v in ok if v >= t) + sum(1 for v in ko if v < t)) / len(rows)
        if acc > best[0]:
            best = (acc, t)
    tp = sum(1 for v in ok if v >= best[1]); fn = len(ok) - tp
    fp = sum(1 for v in ko if v >= best[1]); tn = len(ko) - fp
    print(f"best threshold >={best[1]}: acc {best[0]:.3f}  "
          f"TP {tp} FN {fn} FP {fp} TN {tn}")
    doms = {}
    for r in rows:
        doms.setdefault(r["domain"], []).append(
            (r["j_completion"], r["truth"] == 1.0))
    for d, v in sorted(doms.items()):
        p = [c for c, t in v if t]; f = [c for c, t in v if not t]
        print(f"  {d:22s} pass n={len(p):3d} mean {sum(p)/max(1,len(p)):4.1f}"
              f" | fail n={len(f):3d} mean {sum(f)/max(1,len(f)):4.1f}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("result_dir", nargs="?", type=Path)
    ap.add_argument("--tasks", type=Path)
    ap.add_argument("--endpoint", default="http://127.0.0.1:18020/v1")
    ap.add_argument("--model", default="qwen38-27b-local")
    ap.add_argument("--key", default=None)
    ap.add_argument("--out", type=Path, default=Path("trajaudit.jsonl"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--report", type=Path, default=None)
    a = ap.parse_args(argv)
    if a.report:
        report(a.report)
        return 0
    if not a.result_dir or not a.tasks:
        ap.error("RESULT_DIR and --tasks required for audit mode")
    audit(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
