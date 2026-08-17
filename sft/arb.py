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


def ask_arb(cfg, blocks):
    from ostg import llm
    msgs = [{"role": "user", "content": blocks}]
    sysb = [{"type": "text", "text": SYSTEM}]
    for i in range(4):   # thinking + auto tool_choice: the call may end in
        try:             # text; retry until a tool_use block appears
            r = llm.call(msgs, sysb, cfg, tool=ARB_TOOL)
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

    def one(k):
        domain, task_id = k
        why, q, o = picks[k]
        td = a.result_dir / domain / task_id
        steps = traj.load_steps(td)
        truth = traj.score(td)
        if not steps or truth is None:
            return
        task = load_task(a.tasks, domain, task_id)
        ev = json.dumps(task.get("evaluator", {}), ensure_ascii=False)[:4000]
        jl = []
        if k in qwen:
            jl.append(f'judge A (blind): completion {qwen[k]["j_completion"]}'
                      f'/10 -- "{qwen[k].get("j_note", "")}"')
        if k in opus:
            jl.append(f'judge B (blind): completion {opus[k]["j_completion"]}'
                      f'/10 -- "{opus[k].get("j_note", "")}"')
        blocks = [{"type": "text", "text":
                   "<task_instruction>\n" + task["instruction"]
                   + "\n</task_instruction>\n\n<checker>\nverdict: "
                   + ("PASS" if truth == 1.0 else f"FAIL (score {truth})")
                   + "\nevaluator config: " + ev + "\n</checker>\n\n"
                   + "<blind_judges>\n" + "\n".join(jl) + "\n</blind_judges>"
                   + "\n\nScreenshots follow, each labeled."}]
        frames = frames_for(td, steps)
        for i, (lbl, p) in enumerate(frames, 1):
            blocks.append({"type": "text", "text": f"Frame {i} ({lbl}):"})
            blocks.append({"type": "image", "source":
                           {"type": "base64", "media_type": "image/png",
                            "data": b64(p)}})
        blocks.append({"type": "text", "text":
                       f"<action_history>\n({len(steps)} steps)\n"
                       + digest(steps) + "\n</action_history>\n\n"
                       "Arbitrate now by calling the arbitrate tool."})
        v = ask_arb(cfg, blocks)
        row = {"domain": domain, "task_id": task_id, "truth": truth,
               "why": why, "qwen": q, "opus": o,
               "judge_status": "error" if "error" in v else "ok",
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
