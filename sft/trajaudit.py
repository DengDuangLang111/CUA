"""Trajectory-level blind quality audit + judge calibration.

    # score every trajectory (pass AND fail), judge blind to the checker:
    python -m ostg.sft.trajaudit RESULT_DIR --tasks TASKS_DIR \
        [--endpoint http://127.0.0.1:18020/v1] [--model qwen38-27b-local] \
        [--out trajaudit.jsonl] [--limit N] [--rubric v1|v2|v2req]

    # calibration report (AUC / separation / confusion vs checker truth):
    python -m ostg.sft.trajaudit --report trajaudit.jsonl \
        [--score-field j_derived]

Design (user spec 2026-08-17): the judge grades completion 0-10 from the
trajectory evidence ALONE -- first/last frames + <=8 evenly spaced middle
screenshots + the full action sequence + one-line think digests. The
checker score is recorded in the output row but NEVER shown to the judge;
the report then measures whether the judge can tell success from failure
at all. A judge only earns curation duties by passing this exam.
Rubric anchors (in the system prompt) pin the scale so scores do not
drift to a noncommittal 7. Metadata, never a filter.

Rubrics (2026-08-17 evening, after the v1 exam -- AUC .763/.774, nine
shared false positives traced to agents' self-verification theater):
    v1     free 0-10 grade, terse prompt. The shipped baseline; stays the
           default so replays reproduce the exam byte-for-byte.
    v2     same output fields, restructured prompt (labeled frames, an
           explicit screenshots-outrank-claims rule, XML-tagged inputs),
           temperature pinned to 0 on the API judge, vLLM guided_json on
           the local judge.
    v2req  v2 + requirement decomposition: the judge first lists the
           concrete requirements a strict grader would check, statuses
           each with cited evidence frames/steps, THEN scores. A script
           derives a second score from the statuses (critical x2 weight,
           unverifiable excluded from the denominator, per spec never
           counted as 0); the free-vs-derived gap is a self-consistency
           probe, and hallucinated citations are counted, not trusted.
"""
import argparse
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ostg.sft import traj
from ostg.sft.stepaudit import ask, b64, load_instruction, THINK_RE

GRADE_TOOL = {
    "name": "grade",
    "description": "Report the trajectory grade.",
    "input_schema": {
        "type": "object",
        "properties": {
            "completion": {"type": "integer", "minimum": 0, "maximum": 10},
            "efficiency": {"type": "integer", "minimum": 0, "maximum": 3},
            "grounded": {"type": "integer", "minimum": 0, "maximum": 3},
            "termination": {"type": "integer", "minimum": 0, "maximum": 3},
            "confidence": {"type": "integer", "minimum": 0, "maximum": 2},
            "note": {"type": "string"},
        },
        "required": ["completion", "efficiency", "grounded",
                     "termination", "confidence", "note"],
    },
}

REQ_PROPS = {
    "id": {"type": "string"},
    "text": {"type": "string"},
    "critical": {"type": "boolean"},
    "status": {"type": "string", "enum": [
        "satisfied", "mostly_satisfied", "partial",
        "weak_evidence", "not_satisfied", "unverifiable"]},
    "evidence_steps": {"type": "array", "items": {"type": "integer"}},
    "evidence_frames": {"type": "array", "items": {"type": "integer"}},
    "evidence": {"type": "string"},
}

GRADE_TOOL_REQ = {
    "name": "grade",
    "description": "Report the requirement-grounded trajectory grade.",
    "input_schema": {
        "type": "object",
        "properties": {
            # requirements first on purpose: field order nudges the judge to
            # decompose and verify before it commits to a number.
            "requirements": {
                "type": "array", "minItems": 1, "maxItems": 10,
                "items": {"type": "object", "properties": REQ_PROPS,
                          "required": list(REQ_PROPS)},
            },
            "completion": {"type": "integer", "minimum": 0, "maximum": 10},
            "efficiency": {"type": "integer", "minimum": 0, "maximum": 3},
            "grounded": {"type": "integer", "minimum": 0, "maximum": 3},
            "termination": {"type": "integer", "minimum": 0, "maximum": 3},
            "confidence": {"type": "integer", "minimum": 0, "maximum": 2},
            "note": {"type": "string"},
        },
        "required": ["requirements", "completion", "efficiency", "grounded",
                     "termination", "confidence", "note"],
    },
}


def ask_anthropic(cfg, user_blocks, system=None, tool=None):
    """Same rubric, Claude backend: thinking disabled + forced grade tool,
    so the schema is structural rather than regex-extracted. 10-way pools
    are safe -- ppapi rate limits far above that."""
    from ostg import llm
    system = SYSTEM if system is None else system
    tool = GRADE_TOOL if tool is None else tool
    msgs = [{"role": "user", "content": user_blocks}]
    sysb = [{"type": "text", "text": system}]
    for i in range(3):
        try:
            r = llm.call(msgs, sysb, cfg, tool=tool)
            for blk in r.get("content", []):
                if blk.get("type") == "tool_use":
                    return blk["input"]
            return {"error": "no tool_use in reply"}
        except Exception as e:  # noqa: BLE001
            if not getattr(e, "transient", False) or i == 2:
                return {"error": str(e)[:200]}
            import time
            time.sleep(10 * (i + 1))

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

SYSTEM_V2 = """You are an expert auditor of GUI-agent trajectories on OSWorld-style desktop tasks. From partial evidence alone -- the task instruction, labeled screenshots, and the executed action history with one-line reasoning digests -- judge how completely the agent fulfilled the task. You are never told whether the task passed its programmatic checker; do not assume it did.

Procedure:
1. Read the instruction and note everything a strict grader would check, including implicit requirements: exact file name and location, the file actually saved, formatting, ordering, exact values.
2. Examine every screenshot. Frames are numbered and labeled with the step they follow; later frames show later state.
3. Walk the action history against the frames. Screenshots outrank the agent's words: a verification command that was typed but whose output is not visible proves nothing, and the agent's own claim of success is never evidence.
4. Credit only what the frames and actions demonstrate; treat requirements you cannot see satisfied as unverified, not as done.

Completion anchors: 0-2 clearly failed or wrong direction; 3-4 major gaps, unlikely complete; 5-6 partly complete, or key requirements unverifiable from the evidence; 7-8 likely complete with minor flaws (detours, redundancy); 9-10 clean completion with visible verification of every requirement.
Subscores: efficiency 0-3 (detours, waste), grounded 0-3 (actions match on-screen state), termination 0-3 (stopped at the right moment for the right reason), confidence 0-2 (how sure you are of your completion score).

Report your grade by calling the grade tool. Keep note under 30 words."""

SYSTEM_V2REQ = SYSTEM_V2.replace(
    "Report your grade by calling the grade tool.",
    """Before scoring, decompose the instruction into 2-8 concrete requirements a strict grader would check (include the implicit ones). For each give: a short id (R1, R2, ...), the requirement text, whether it is critical (the task fails without it), its status -- satisfied / mostly_satisfied / partial / weak_evidence / not_satisfied / unverifiable -- the step numbers and frame numbers that carry your evidence (cite only steps and frames you were actually shown), and a one-line evidence description. Your overall completion score must agree with your requirement statuses.

Report the requirements and your grade together in one call of the grade tool.""")

K_FRAMES = 10

STATUS_VAL = {"satisfied": 1.0, "mostly_satisfied": 0.75, "partial": 0.5,
              "weak_evidence": 0.25, "not_satisfied": 0.0}


def derived_score(reqs):
    """Statuses -> 0-10: critical requirements weigh 2x; unverifiable ones
    leave the denominator entirely (spec: never silently counted as 0)."""
    num = den = 0.0
    crit_fail = False
    for r in reqs:
        if not isinstance(r, dict):
            continue
        w = 2.0 if r.get("critical") else 1.0
        s = STATUS_VAL.get(r.get("status"))
        if s is None:
            continue
        num += w * s
        den += w
        if r.get("critical") and r.get("status") == "not_satisfied":
            crit_fail = True
    return (round(10.0 * num / den, 2) if den else None), crit_fail


def evidence_violations(reqs, step_nums, n_frames):
    """Citations pointing at steps/frames the judge was never shown --
    hallucinated evidence, recorded rather than trusted."""
    bad = 0
    for r in reqs:
        if not isinstance(r, dict):
            continue
        for s in r.get("evidence_steps") or []:
            if not isinstance(s, int) or s not in step_nums:
                bad += 1
        for f in r.get("evidence_frames") or []:
            if not isinstance(f, int) or not 1 <= f <= n_frames:
                bad += 1
    return bad


def frames_for(td, steps):
    """K frames as (label, path): initial state, evenly spaced post-step
    shots, final. Labels let v2 judges cite frames by number; v1 ignores
    them, so its requests stay byte-identical to the shipped exam."""
    shots = [(s.num, td / s.screenshot) for s in steps if s.screenshot]
    init = td / "initial_state.png"
    if init.is_file():
        picks = [("initial state", init)]
    else:
        picks = [(f"after step {n}", p) for n, p in shots[:1]]
    if len(shots) > 1:
        idx = sorted({round(i * (len(shots) - 1) / (K_FRAMES - 2))
                      for i in range(K_FRAMES - 1)})
        picks += [(f"after step {shots[i][0]}", shots[i][1]) for i in idx]
    seen, out = set(), []
    for lbl, p in picks:
        if p.is_file() and p not in seen:
            seen.add(p)
            out.append((lbl, p))
    return out[:K_FRAMES]


def digest(steps):
    lines = []
    for s in steps:
        th = (THINK_RE.search(s.response) or [None, ""])[1]
        th = " ".join(th.split())[:90]
        lines.append(f"step {s.num}: {' | '.join(s.actions)[:120]}"
                     + (f"  // {th}" if th else ""))
    return "\n".join(lines)


def build_blocks(rubric, instr, frames, steps, dig):
    """Ordered (kind, value) blocks, backend-agnostic. v1 reproduces the
    shipped exam exactly; v2* labels every frame and fences the inputs."""
    if rubric == "v1":
        out = [("text", "Task: " + instr)]
        out += [("image", p) for _, p in frames]
        out.append(("text", f"Actions and reasoning digests ({len(steps)} "
                    f"steps):\n" + dig))
        return out, SYSTEM, GRADE_TOOL
    parts = [("text", "<task_instruction>\n" + instr + "\n</task_instruction>"
              + f"\n\n{len(frames)} screenshots follow, each labeled.")]
    for i, (lbl, p) in enumerate(frames, 1):
        parts.append(("text", f"Frame {i} ({lbl}):"))
        parts.append(("image", p))
    parts.append(("text", f"<action_history>\n({len(steps)} steps)\n" + dig
                  + "\n</action_history>\n\nGrade the trajectory now by "
                  "calling the grade tool. Screenshots outrank the agent's "
                  "claims."))
    if rubric == "v2":
        return parts, SYSTEM_V2, GRADE_TOOL
    return parts, SYSTEM_V2REQ, GRADE_TOOL_REQ


def audit(a):
    import os
    key = a.key or os.environ.get("OPENAI_API_KEY") or "EMPTY"
    cfg = None
    if a.backend == "anthropic":
        from ostg import llm
        # ppapi credentials live in the wrapper repo's .env (check.py lineage)
        llm.load_env("/mnt/d/research/os-simple-taskgen-v8/.env")
        llm.load_env("/mnt/d/research/ostg-v11.1/.env")
        cfg = {"model": a.model,
               "max_tokens": 4096 if a.rubric == "v2req" else 2048,
               "thinking": False,
               "base": os.environ.get("PPAPI_BASE_URL", "https://app-us.ppapi.ai").rstrip("/"),
               "key": os.environ.get("PPAPI_API_KEY", "")}
        if a.rubric != "v1":
            cfg["temperature"] = 0
    done = set()
    if a.out.exists():
        for line in a.out.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["domain"], r["task_id"]))
    jobs = []
    for rt in sorted(a.result_dir.glob("*/*/result.txt")):
        td = rt.parent
        domain, task_id = td.parent.name, td.name
        if (domain, task_id) in done:
            continue
        truth = traj.score(td)
        steps = traj.load_steps(td)
        if truth is None or not steps:
            continue
        jobs.append((td, domain, task_id, truth, steps))
    if a.limit:
        jobs = jobs[:a.limit]
    out_f = a.out.open("a", encoding="utf-8")
    lock = threading.Lock()
    n = [0]

    def one(job):
        td, domain, task_id, truth, steps = job
        instr = load_instruction(a.tasks, domain, task_id)
        frames = frames_for(td, steps)
        ordered, system, tool = build_blocks(a.rubric, instr, frames, steps,
                                             digest(steps))
        if a.backend == "anthropic":
            blocks = []
            for kind, val in ordered:
                if kind == "text":
                    blocks.append({"type": "text", "text": val})
                else:
                    blocks.append({"type": "image", "source":
                                   {"type": "base64", "media_type": "image/png",
                                    "data": b64(val)}})
            v = ask_anthropic(cfg, blocks, system=system, tool=tool)
        else:
            user = []
            for kind, val in ordered:
                if kind == "text":
                    user.append({"type": "text", "text": val})
                else:
                    user.append({"type": "image_url", "image_url":
                                 {"url": "data:image/png;base64," + b64(val)}})
            v = ask(a.endpoint, a.model, key,
                    [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
                    guided=tool["input_schema"] if a.rubric != "v1" else None)
        row = {"domain": domain, "task_id": task_id, "n_steps": len(steps),
               "truth": truth, "rubric": a.rubric,
               "judge_status": "error" if "error" in v else "ok",
               **{f"j_{k}": val for k, val in v.items()}}
        if a.rubric == "v2req" and isinstance(v.get("requirements"), list):
            d, crit = derived_score(v["requirements"])
            row["j_derived"] = d
            row["j_crit_fail"] = crit
            if isinstance(v.get("completion"), (int, float)) and d is not None:
                row["j_score_gap"] = round(v["completion"] - d, 2)
            row["j_evidence_violations"] = evidence_violations(
                v["requirements"], {s.num for s in steps}, len(frames))
        with lock:
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            out_f.flush()
            n[0] += 1
            brief = {k: v[k] for k in ("completion", "confidence", "note")
                     if k in v} if "error" not in v else v
            print(f"[{n[0]}] {domain}/{task_id[:8]} truth={truth} -> {brief}")

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(one, jobs))
    out_f.close()


def report(path, score_field="j_completion"):
    rows = [json.loads(l) for l in Path(path).read_text().splitlines()
            if l.strip()]
    rows = [r for r in rows
            if isinstance(r.get(score_field), (int, float))
            and not isinstance(r.get(score_field), bool)]
    if not rows:
        print("no scored rows")
        return
    ok = [r[score_field] for r in rows if r["truth"] == 1.0]
    ko = [r[score_field] for r in rows if r["truth"] != 1.0]
    med = lambda v: sorted(v)[len(v) // 2] if v else float("nan")
    print(f"score field: {score_field}")
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
            (r[score_field], r["truth"] == 1.0))
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
    ap.add_argument("--score-field", default="j_completion")
    ap.add_argument("--backend", choices=("qwen", "anthropic"), default="qwen")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--rubric", choices=("v1", "v2", "v2req"), default="v1")
    a = ap.parse_args(argv)
    if a.report:
        report(a.report, a.score_field)
        return 0
    if not a.result_dir or not a.tasks:
        ap.error("RESULT_DIR and --tasks required for audit mode")
    audit(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
