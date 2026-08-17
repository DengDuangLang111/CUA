"""Checker-vs-judge arbitration on disagreement trajectories.

    python -m ostg.sft.arb RESULT_DIR --tasks TASKS_DIR \
        --qwen out/trajaudit_X.jsonl --opus out/trajaudit_X_opus.jsonl \
        [--out out/arb_X.jsonl] [--model claude-opus-5] [--workers 2]

The blind exam (trajaudit) surfaced trajectories where both judges call a
checker-failed run complete (verification theater OR a checker bug -- can't
tell from blind evidence), and passes the judges score low (checker
leniency suspects). This module is the assisted second stage (user approved
2026-08-17): a strong model WITH extended thinking sees what the blind
judges never did -- the checker's own evaluator config and its verdict --
plus the same frames/actions, and rules on who is wrong. Blindness is
preserved where it matters (the exam) and spent where it pays (the audit
of the disagreement set). Output is metadata: a checker-defect shortlist
and a judge-failure-mode inventory, never an automatic filter.

Disagreement selection (from the joined exam rows):
    fp    truth!=1  and (qwen>=8 or opus>=7)   judge(s) fooled, or checker
                                               too strict
    fn    truth==1  and (qwen<=5 or opus<=5)   checker leniency suspect
    duel  |qwen-opus| >= 4                     judges contradict each other
"""
import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ostg.sft import traj
from ostg.sft.stepaudit import b64
from ostg.sft.trajaudit import frames_for, digest

ARB_TOOL = {
    "name": "arbitrate",
    "description": "Report the arbitration verdict.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": [
                "checker_right_judge_fooled",
                "checker_bug_lenient",
                "checker_bug_strict",
                "ambiguous"]},
            "what_checker_verifies": {"type": "string"},
            "judge_miss": {"type": "string"},
            "checker_flaw": {"type": "string"},
            "decisive_evidence": {"type": "string"},
            "confidence": {"type": "integer", "minimum": 0, "maximum": 2},
            "note": {"type": "string"},
        },
        "required": ["verdict", "what_checker_verifies", "judge_miss",
                     "checker_flaw", "decisive_evidence", "confidence",
                     "note"],
    },
}

SYSTEM = """You are the arbiter in a disagreement between two automatic evaluations of a GUI-agent trajectory on an OSWorld-style desktop task.

A programmatic checker scored this trajectory, and independently, blind LLM judges graded it from screenshots and the action history without seeing the checker. They disagree with the checker, or with each other. Decide who is right. Unlike the blind judges, you ARE shown the checker's evaluator config and its verdict.

Weigh three hypotheses:
1. checker_right_judge_fooled -- the checker is correct and the judges were misled: the trajectory looks complete, but something the checker verifies is not actually satisfied (a save that never landed, wrong file name or location, wrong value, the agent's self-verification checked the wrong thing).
2. checker_bug_lenient -- the checker passed work that does not satisfy the instruction: its config under-specifies what the instruction demands (order, exact values, formatting it never checks).
3. checker_bug_strict -- the checker failed work a strict human grader would accept: broken or over-rigid config (wrong expected value, brittle getter, checks state the task never promised).
Choose ambiguous only when the evidence genuinely cannot decide.

Rules of evidence: screenshots outrank every textual claim, including the agent's own verification output when its result is not visible in a frame. The checker config tells you exactly WHAT was checked -- line it up against the instruction (is the check complete?) and against the frames (is the checked thing visibly satisfied?).

Report via the arbitrate tool: verdict, what the checker actually verifies (one line), what the blind judges missed (or "" if nothing), the checker's flaw (or "" if none), the decisive evidence, confidence 0-2, and a note under 40 words."""

# --- protocol v2: stage A derives independently, stage B is told the verdict.
# Splitting the call is the only real isolation -- inside one prompt the model
# sees everything at once, so "reason before you look" cannot be enforced.

AUDIT_TOOL = {
    "name": "audit",
    "description": "Report the independent pre-verdict audit.",
    "input_schema": {
        "type": "object",
        "properties": {
            "checks": {
                "type": "array", "minItems": 1, "maxItems": 12,
                "items": {"type": "object", "properties": {
                    "what": {"type": "string"},
                    "in_instruction": {"type": "string", "enum": [
                        "required", "implied", "not_required"]},
                    "observed": {"type": "string", "enum": [
                        "satisfied", "not_satisfied", "cannot_tell"]},
                    "evidence": {"type": "string"}},
                    "required": ["what", "in_instruction", "observed",
                                 "evidence"]}},
            "missing_checks": {"type": "string"},
            "predicted_outcome": {"type": "string", "enum": [
                "should_pass", "should_fail", "cannot_tell"]},
            "config_readable": {"type": "boolean"},
            "note": {"type": "string"},
        },
        "required": ["checks", "missing_checks", "predicted_outcome",
                     "config_readable", "note"],
    },
}

SYSTEM_A = """You are auditing one GUI-agent trajectory on an OSWorld-style desktop task, together with the programmatic checker written for that task. You are NOT told the checker's verdict, and you must not guess at it from tone: derive everything yourself.

Do two independent things:
1. Read the checker code and enumerate what it actually verifies, one entry per check. For each, say whether the task instruction requires it (required), leaves it implied (implied), or never asks for it (not_required) -- a check on something the instruction never specifies is how a checker becomes wrong.
2. Read the screenshots and action history and say, per check, whether the evidence shows it satisfied, not satisfied, or cannot be told from the available evidence. Screenshots outrank every textual claim, including the agent's own verification commands whose output is not visible in a frame.

Also state any requirement the instruction makes that the checker does NOT verify, and your predicted outcome from your own reading alone.

Report via the audit tool."""

SYSTEM_B = SYSTEM + """

You have already audited this trajectory independently, before seeing any verdict; your own findings are included below. Now you are shown the checker's verdict and the blind judges' scores. Reconcile them.

If your final verdict contradicts what your own pre-verdict audit predicted, you must say why in reversal_reason -- new evidence you had missed, or a check you had misread. "The checker says so" is not a reason. If your audit still stands, leave reversal_reason empty.

Use ambiguous when two or more checks came back cannot_tell, or when the checker's faithfulness is doubtful and no frame settles it; in that case what_would_settle_it must name the single observation that would decide it."""

SYSTEM_ADV = """You are the checker's defence counsel. A programmatic checker FAILED this GUI-agent trajectory, and a reviewer then ruled the checker itself is buggy -- that the agent did the task and the checker is wrong. That ruling is about to promote this trajectory into training data, so it must survive an adversarial test.

Your job is to argue the opposite: find the reason the CHECKER IS RIGHT. Read its code line by line and look for a requirement the reviewer glossed over -- a file path, a name, an ordering, a value, a format, a clause of the instruction the agent only appeared to satisfy. Screenshots showing a plausible end state are not proof; a command typed without visible output is not proof; the agent's own claim of success is never proof.

Rule out the easy escapes: "the checker is over-strict" is only true if the thing it checks is genuinely absent from the instruction, explicitly and implicitly. If the instruction implies it, the checker is entitled to check it.

Only if you honestly cannot mount that argument should you concede that the reviewer was right. Report via the defend tool: verdict 'checker_defensible' when you found a real reason the checker is right (the rescue should be REVOKED), 'rescue_survives' when the reviewer's ruling withstands your attack, 'unclear' only when the code itself is unreadable or the evidence is absent. Give your strongest argument either way, and cite the checker line or instruction clause it rests on."""

DEFEND_TOOL = {
    "name": "defend",
    "description": "Report the adversarial re-check of a rescue.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": [
                "checker_defensible", "rescue_survives", "unclear"]},
            "strongest_argument": {"type": "string"},
            "checker_line_or_clause": {"type": "string"},
            "what_reviewer_missed": {"type": "string"},
            "confidence": {"type": "integer", "minimum": 0, "maximum": 2},
        },
        "required": ["verdict", "strongest_argument",
                     "checker_line_or_clause", "what_reviewer_missed",
                     "confidence"],
    },
}

ARB_TOOL_V2 = {
    "name": ARB_TOOL["name"],
    "description": ARB_TOOL["description"],
    "input_schema": {
        "type": "object",
        "properties": {
            **ARB_TOOL["input_schema"]["properties"],
            "reversal_reason": {"type": "string"},
            "what_would_settle_it": {"type": "string"},
        },
        "required": ARB_TOOL["input_schema"]["required"]
        + ["reversal_reason", "what_would_settle_it"],
    },
}


def judge_rows(path):
    out = {}
    if not path:
        return out
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if isinstance(r.get("j_completion"), int):
            out[(r["domain"], r["task_id"])] = r
    return out


def pick_disagreements(qwen, opus):
    picks = {}
    for k in set(qwen) | set(opus):
        q = qwen.get(k, {}).get("j_completion")
        o = opus.get(k, {}).get("j_completion")
        truth = (qwen.get(k) or opus.get(k))["truth"]
        why = []
        if truth != 1.0 and ((q is not None and q >= 8)
                             or (o is not None and o >= 7)):
            why.append("fp")
        if truth == 1.0 and ((q is not None and q <= 5)
                             or (o is not None and o <= 5)):
            why.append("fn")
        if q is not None and o is not None and abs(q - o) >= 4:
            why.append("duel")
        if why:
            picks[k] = (why, q, o)
    return picks


def load_task(tasks_dir, domain, task_id):
    p = Path(tasks_dir) / "examples" / domain / f"{task_id}.json"
    return json.loads(p.read_text(encoding="utf-8"))


def ask_arb(cfg, blocks, system=SYSTEM, tool=ARB_TOOL):
    from ostg import llm
    msgs = [{"role": "user", "content": blocks}]
    sysb = [{"type": "text", "text": system}]
    for i in range(4):   # thinking + auto tool_choice: the call may end in
        try:             # text; retry until a tool_use block appears
            r = llm.call(msgs, sysb, cfg, tool=tool)
            for blk in r.get("content", []):
                if blk.get("type") == "tool_use":
                    return blk["input"]
            err = "no tool_use"
        except Exception as e:  # noqa: BLE001
            if not getattr(e, "transient", False) or i == 3:
                return {"error": str(e)[:200]}
            err = str(e)[:80]
        if i == 3:
            return {"error": err}
        time.sleep(10 * (i + 1))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("result_dir", type=Path)
    ap.add_argument("--tasks", type=Path, required=True)
    ap.add_argument("--qwen", type=Path, default=None)
    ap.add_argument("--opus", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=Path("arb.jsonl"))
    ap.add_argument("--model", default="claude-opus-5")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--protocol", choices=("v1", "v2", "adv"), default="v1",
                    help="v1 = single call, verdict visible (frozen "
                         "baseline); v2 = independent audit call, then "
                         "reconcile with the verdict revealed")
    ap.add_argument("--prior", type=Path, action="append", default=[],
                    help="earlier arbitration jsonl(s); adv protocol attacks "
                         "their rulings")
    ap.add_argument("--targets", type=Path, default=None,
                    help="jsonl of domain/task_id rows to arbitrate even "
                         "without judge disagreement (e.g. curate tier2 / "
                         "step-audit lenient suspects)")
    a = ap.parse_args(argv)

    import os
    from ostg import llm
    llm.load_env("/mnt/d/research/os-simple-taskgen-v8/.env")
    llm.load_env("/mnt/d/research/ostg-v11.1/.env")
    cfg = {"model": a.model, "max_tokens": 8192,
           "thinking": True, "stream": True,
           "base": os.environ.get("PPAPI_BASE_URL",
                                  "https://app-us.ppapi.ai").rstrip("/"),
           "key": os.environ.get("PPAPI_API_KEY", "")}

    qwen, opus = judge_rows(a.qwen), judge_rows(a.opus)
    picks = pick_disagreements(qwen, opus)
    prior_rulings = {}
    for p in (a.prior or []):
        for line in Path(p).read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("judge_status") == "ok":
                    prior_rulings[(r["domain"], r["task_id"])] = r
    if a.targets:
        for line in a.targets.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                k = (r["domain"], r["task_id"])
                if k not in picks:
                    picks[k] = (["target"],
                                qwen.get(k, {}).get("j_completion"),
                                opus.get(k, {}).get("j_completion"))
    done = set()
    if a.out.exists():
        for line in a.out.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["domain"], r["task_id"]))
    todo = sorted(k for k in picks if k not in done)
    if a.limit:
        todo = todo[:a.limit]
    print(f"{len(picks)} disagreements, {len(todo)} to arbitrate")

    out_f = a.out.open("a", encoding="utf-8")
    lock = threading.Lock()
    n = [0]

    def evidence(td, steps, instr, ev_json, truncated):
        """Shared prompt body: instruction, checker CODE (no verdict),
        labeled frames, action history, and the final steps' full reasoning
        (the 90-char digests hide what the agent thought it was verifying)."""
        head = ("<task_instruction>\n" + instr + "\n</task_instruction>\n\n"
                "<checker_code>\n" + ev_json
                + ("\n[TRUNCATED]" if truncated else "")
                + "\n</checker_code>\n\nScreenshots follow, each labeled.")
        blocks = [{"type": "text", "text": head}]
        for i, (lbl, p) in enumerate(frames_for(td, steps), 1):
            blocks.append({"type": "text", "text": f"Frame {i} ({lbl}):"})
            blocks.append({"type": "image", "source":
                           {"type": "base64", "media_type": "image/png",
                            "data": b64(p)}})
        tail = [f"<action_history>\n({len(steps)} steps)\n" + digest(steps)
                + "\n</action_history>"]
        for s in steps[-3:]:
            tail.append(f"<step_{s.num}_reasoning>\n{s.response[:3000]}"
                        f"\n</step_{s.num}_reasoning>")
        blocks.append({"type": "text", "text": "\n\n".join(tail)})
        return blocks

    def one(k):
        domain, task_id = k
        why, q, o = picks[k]
        td = a.result_dir / domain / task_id
        steps = traj.load_steps(td)
        truth = traj.score(td)
        if not steps or truth is None:
            return
        task = load_task(a.tasks, domain, task_id)
        full = json.dumps(task.get("evaluator", {}), ensure_ascii=False)
        cap = 4000 if a.protocol == "v1" else 12000
        ev, truncated = full[:cap], len(full) > cap
        jl = []
        if k in qwen:
            jl.append(f'judge A (blind): completion {qwen[k]["j_completion"]}'
                      f'/10 -- "{qwen[k].get("j_note", "")}"')
        if k in opus:
            jl.append(f'judge B (blind): completion {opus[k]["j_completion"]}'
                      f'/10 -- "{opus[k].get("j_note", "")}"')
        verdict_txt = ("PASS" if truth == 1.0 else f"FAIL (score {truth})")
        audit = None
        if a.protocol == "adv":
            prior = (prior_rulings.get(k) or {})
            base = evidence(td, steps, task["instruction"], ev, truncated)
            v = ask_arb(cfg, base + [{"type": "text", "text":
                        "<checker_verdict>" + verdict_txt + "</checker_verdict>\n"
                        "<reviewer_ruling>\nverdict: "
                        + str(prior.get("a_verdict")) + "\nclaimed checker flaw: "
                        + str(prior.get("a_checker_flaw"))
                        + "\ndecisive evidence cited: "
                        + str(prior.get("a_decisive_evidence"))
                        + "\n</reviewer_ruling>\n\nMount your defence now by "
                        "calling the defend tool."}], SYSTEM_ADV, DEFEND_TOOL)
            row = {"domain": domain, "task_id": task_id, "truth": truth,
                   "protocol": "adv", "prior_verdict": prior.get("a_verdict"),
                   "judge_status": "error" if "error" in v else "ok",
                   **{f"d_{key}": val for key, val in v.items()}}
            with lock:
                out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                out_f.flush(); n[0] += 1
                print(f"[{n[0]}] {domain}/{task_id[:8]} -> {v.get('verdict', v)}")
            return
        if a.protocol == "v1":
            blocks = [{"type": "text", "text":
                       "<task_instruction>\n" + task["instruction"]
                       + "\n</task_instruction>\n\n<checker>\nverdict: "
                       + verdict_txt + "\nevaluator config: " + ev
                       + "\n</checker>\n\n<blind_judges>\n" + "\n".join(jl)
                       + "\n</blind_judges>\n\nScreenshots follow, each labeled."}]
            for i, (lbl, p) in enumerate(frames_for(td, steps), 1):
                blocks.append({"type": "text", "text": f"Frame {i} ({lbl}):"})
                blocks.append({"type": "image", "source":
                               {"type": "base64", "media_type": "image/png",
                                "data": b64(p)}})
            blocks.append({"type": "text", "text":
                           f"<action_history>\n({len(steps)} steps)\n"
                           + digest(steps) + "\n</action_history>\n\n"
                           "Arbitrate now by calling the arbitrate tool."})
            v = ask_arb(cfg, blocks)
        else:
            base = evidence(td, steps, task["instruction"], ev, truncated)
            audit = ask_arb(cfg, base + [{"type": "text", "text":
                            "Audit now by calling the audit tool."}],
                            SYSTEM_A, AUDIT_TOOL)
            if "error" in audit:
                v = audit
            else:
                v = ask_arb(cfg, base + [{"type": "text", "text":
                            "<your_pre_verdict_audit>\n"
                            + json.dumps(audit, ensure_ascii=False)
                            + "\n</your_pre_verdict_audit>\n\n<checker_verdict>"
                            + verdict_txt + "</checker_verdict>\n\n"
                            "<blind_judges>\n" + "\n".join(jl)
                            + "\n</blind_judges>\n\nArbitrate now by calling "
                            "the arbitrate tool."}], SYSTEM_B, ARB_TOOL_V2)
        row = {"domain": domain, "task_id": task_id, "truth": truth,
               "why": why, "qwen": q, "opus": o, "protocol": a.protocol,
               "config_truncated": truncated,
               "judge_status": "error" if "error" in v else "ok",
               **({"stage_a": audit} if audit else {}),
               **{f"a_{key}": val for key, val in v.items()}}
        with lock:
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            out_f.flush()
            n[0] += 1
            print(f"[{n[0]}] {domain}/{task_id[:8]} truth={truth} {why} -> "
                  f"{v.get('verdict', v)}")

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(one, todo))
    out_f.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
