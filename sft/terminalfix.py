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

What this writes: one row per trajectory saying how its ending is repaired.
Only the FINAL step's target is ever touched; everything earlier is untouched,
so the causal chain is intact and the images are reused.

Three paths, least intervention first (`mode` in each row):

  already-terminate  The ending is already an explicit terminate(success).
                     54 of 376 were. Leave it completely alone -- the row
                     carries `response: null` and build skips it. Replacing
                     these with a synthetic ending was a regression.
  append             A prose ending that is complete: keep the teacher's own
                     words verbatim and add only the missing tool call. The
                     trajectory already stopped here (the harness scores an
                     absent tool call as DONE) and the checker passed the
                     state, so the sole defect is that stopping was implicit.
                     246 of 376.
  rewrite            The ending cannot be reused -- it calls the user, ends on
                     a real action, trips looks_infeasible_response, or the
                     tail was truncated so this step was never an ending. Only
                     here does the teacher write a new turn.

The written turn keeps the natural shape: `<think>` reasoning, then a visible
statement, then the tool call, appended DETERMINISTICALLY. Every one of the 68
endings the teacher produced with a real terminate call has that visible
statement, as do 75% of all other targets; an earlier version emitted nothing
visible and made the terminal step the only turn in the corpus with its shape.
The teacher's text is task-specific rather than a fixed template, because
hundreds of byte-identical responses would teach the sentence, not the
decision.

Tail handling (--tail-policy):
  last-only   rewrite the final step, leave any trailing WAITs as they are
  truncate    also drop trailing steps that did no work (a WAIT, or no
              screenshot delta) and put the terminate at the step where the
              work actually stopped -- so the corpus stops when the task is
              done rather than when the episode ran out of patience
  auto        truncate only where a real stall exists (>=2 dead trailing
              steps), last-only otherwise. The default: 88% of trajectories
              have no stall and do not need their tail touched.
`traj.tail_run` already truncates a trailing run of >=5 identical steps at
build time; this is the finer-grained version aimed at 1-4 step stalls.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ostg.sft import traj
from ostg.sft.stepaudit import anthropic_cfg, ask, b64, load_instruction

SYSTEM = """You are writing the final assistant turn of a completed GUI-agent trajectory.

The task has been verified as done. You are given the task, the screen as it looks at the final step, and the actions that led here. Write the two parts of that turn:

1. `thinking` -- the agent's own private check before it stops: what it looked at to be sure the requested state exists. First person, present tense.
2. `statement` -- what the agent says out loud to the user: that the task is done, and the concrete evidence for it. Name the file that is listed, the value in the cell, the setting that reads as expected. If the screen shows a verification the agent itself ran (a listing, a printed value), cite it.

Rules: each part at most 60 words. No preamble, no restating the instruction, no tool call (one is appended for you). Concrete nouns from this task. Never say the task is impossible, infeasible, or cannot be completed -- it has already been verified as done, and those words are parsed by the harness as a failure signal."""

REASON_TOOL = {
    "name": "justify",
    "description": "Report the agent's final turn: private check, then what it tells the user.",
    "input_schema": {
        "type": "object",
        "properties": {
            "thinking": {"type": "string"},
            "statement": {"type": "string"},
        },
        "required": ["thinking", "statement"],
    },
}

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


def compose_response(thinking, statement):
    """The natural shape of a teacher ending: private reasoning, then the
    conclusion said out loud, then the terminate call.

    Measured on this corpus: all 68 endings the teacher produced with a real
    terminate call have a visible statement between </think> and <tool_call>,
    and so do 75% of every other target. The first version put the whole
    justification inside <think> and emitted nothing visible, which made the
    terminal step the only turn in the corpus with that shape -- and the
    failure being repaired here is precisely that the student copies the
    teacher's terminal STYLE.
    """
    thinking = " ".join((thinking or "").split())
    statement = " ".join((statement or "").split())
    if not statement:
        statement = "The task is complete: the requested state is present on screen."
    if not thinking:
        thinking = "The screen shows the requested state, so the task is done."
    return "<think>\n%s\n</think>\n\n%s%s" % (thinking, statement, TERMINATE_CALL)


def append_terminate(response):
    """Keep a prose ending exactly as the teacher wrote it, add the missing
    action. The trajectory already ended here -- the harness scored the absent
    tool call as DONE and the checker passed the state -- so the only thing
    wrong with this turn is that stopping was implicit."""
    return response.rstrip() + TERMINATE_CALL


def sha(p):
    try:
        return hashlib.md5(Path(p).read_bytes()).hexdigest()
    except OSError:
        return None


NOOP = ("WAIT", "DONE", "FAIL")


def is_noop(action):
    """True when this action executed nothing on the screen.

    WAIT/DONE/FAIL are the harness's own sentinels; `screenshot` is undeclared
    upstream (actions.py logs it and lets it fall through to the WAIT
    fallback), so it also executes nothing.
    """
    a = (action or "").strip()
    return (not a) or a in NOOP or a.lower().startswith("screenshot")


def stalled_tail(td, steps, max_look=10):
    """Trailing steps that did no work: steps that executed NOTHING, or whose
    screenshot is identical to the previous step's.

    A step counts as dead only when EVERY one of its actions is a no-op. The
    first version tested `any(a == "WAIT")`, which condemned the agent's most
    common idiom -- click, then wait for the UI -- as if it were idling. The
    backward walk then ate whole trajectories: one 11-step trajectory was cut
    to 2. Measured over the 33 truncations that shipped in Bhqs-2-terminal,
    that single test condemned 41 productive steps, against 56 correctly
    condemned by "did nothing at all" and 10 by an unchanged screen; 13
    trajectories lost 109 real actions (SFT_DATA.md).

    The screenshot test is sound as written: traj.py records the screenshot
    taken AFTER a step's last action, so an unchanged screen indicts that
    step's own actions, not the previous step's. Its residual blind spot --
    work that changes no pixels, e.g. a background file write -- is covered by
    the hard gate in decide_keep_to, not here.

    Screen stagnation of exactly 1 is NORMAL (the terminal step is a stop, so
    it changes nothing), which is why the count starts from the step BEFORE
    the last one.
    """
    if len(steps) < 2:
        return 0
    n = 0
    body = steps[:-1]                       # exclude the terminal step
    shas = {}
    for s in body[-max_look:]:
        shas[s.num] = sha(td / s.screenshot) if s.screenshot else None
    for i in range(len(body) - 1, 0, -1):
        s = body[i]
        dead = bool(s.actions) and all(is_noop(a) for a in s.actions)
        same = (shas.get(s.num) is not None
                and shas.get(s.num) == shas.get(body[i - 1].num))
        if dead or same:
            n += 1
        else:
            break
    return n


def decide_keep_to(td, steps, tail_policy, stall_min):
    """Where to put the terminate -> (keep_to, stalled, gate).

    The heuristic above proposes a cut; this gate decides whether we are
    allowed to take it. The checker approved the state at the FINAL step, so
    truncating is only provably safe when the screen we stop on is byte-
    identical to the screen the checker scored. Anything else -- including a
    stall the heuristic called dead but that actually changed the screen --
    falls back to last-only. A heuristic may be wrong; the gate may not.
    """
    keep_to, gate = len(steps), "none"
    stalled = stalled_tail(td, steps)
    if tail_policy == "truncate" and stalled:
        keep_to = max(1, len(steps) - stalled)
    elif tail_policy == "auto" and stalled >= stall_min:
        keep_to = max(1, len(steps) - stalled)
    if keep_to < len(steps):
        stop_shot = steps[keep_to - 1].screenshot
        end_shot = steps[-1].screenshot
        a = sha(td / stop_shot) if stop_shot else None
        b = sha(td / end_shot) if end_shot else None
        if not (a and b and a == b):
            keep_to, gate = len(steps), "reverted"
        else:
            gate = "verified"
    return keep_to, stalled, gate


# How a trajectory's ending is repaired. Least intervention that fixes it.
KEEP = "already-terminate"   # nothing to do; no row is written for these
APPEND = "append"            # teacher's own words kept, terminate call added
REWRITE = "rewrite"          # the ending cannot be reused; teacher writes one

_VISIBLE_STRIP = (re.compile(r"<think>.*?</think>", re.S),
                  re.compile(r"<tool_call>.*?</tool_call>", re.S))
# "I'll now open...", not "Let me know if..." (a closing) or "Now if..." (an
# explanation). Measured over 259 prose endings: the narrow form flags none,
# the loose form flagged 13 and every one was a false positive.
_CONTINUES = re.compile(r"^(let me (?!know)|i'?ll now|i will now|next[,:] i|"
                        r"now i (?:will|'ll|need|should))", re.I)


def visible_text(response):
    """What the user sees: the response minus thinking and tool calls."""
    out = response or ""
    for pat in _VISIBLE_STRIP:
        out = pat.sub("", out)
    return out.strip()


def load_parser(harness_root):
    """The harness's own parser -- termination is a parsed action, not a
    string, so classification must not guess at it."""
    if harness_root:
        sys.path.insert(0, str(harness_root))
    from mm_agents.qwen.parser import (iter_tool_call_params,
                                       looks_infeasible_response)
    return iter_tool_call_params, looks_infeasible_response


def classify_ending(response, truncated, parse, infeasible):
    """-> (mode, why). See KEEP / APPEND / REWRITE above."""
    if truncated:
        return REWRITE, "tail truncated, this step was not the ending"
    params = list(parse(response or ""))
    actions = [str(p.get("action")) for p in params if p.get("action")]
    if infeasible(response or ""):
        return REWRITE, "trips looks_infeasible_response (DONE would become FAIL)"
    if "terminate" in actions:
        status = ""
        for p in params:
            if str(p.get("action")) == "terminate":
                status = str(p.get("status") or "").lower()
        if status and status != "success":
            return REWRITE, "terminate(%s)" % status
        return KEEP, "already ends in terminate(success)"
    if "call_user" in actions:
        return REWRITE, "ends by calling the user"
    if actions:
        return REWRITE, "ends with a real action (%s)" % actions[-1]
    seen = visible_text(response)
    if not seen:
        return REWRITE, "no visible statement to keep"
    last = [s for s in re.split(r"(?<=[.!?])\s+", seen) if s.strip()]
    if last and _CONTINUES.match(last[-1].strip()):
        return REWRITE, "closing sentence announces more work"
    return APPEND, "prose ending, complete -- add the missing action"


def read_rows(path):
    if not Path(path).exists():
        return []
    return [json.loads(line) for line in Path(path).read_text().splitlines()
            if line.strip()]


def write_rows(path, rows):
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                                  for r in rows), encoding="utf-8")


def key_of(row):
    return (row["domain"], row["task_id"])


def load_target_keys(paths):
    """The trajectories to canonicalise, in order, de-duplicated."""
    keys = []
    for p in paths:
        keys.extend(key_of(r) for r in read_rows(p))
    return list(dict.fromkeys(keys))


def refresh_tails(result_dir, rows, tail_policy, stall_min):
    """Re-derive every row's cut under the current policy -> (kept, stale).

    A row whose cut still lands in the same place keeps its justification: the
    teacher wrote it for that screen and the screen has not moved. A row whose
    cut moves is stale -- its justification describes a screen we no longer
    stop on -- so it goes back to the teacher. Rewriting all of them instead
    would silently change hundreds of targets that nothing was wrong with.

    A teacher-written row with no statement is also stale regardless of the
    cut: the call failed and compose_response substituted its canned fallback,
    so a re-run should retry it rather than bake the fallback in. Rows the
    teacher never touched (already-terminate, append) are exempt from that
    test -- they have no teacher output to be missing.
    """
    kept, stale = [], []
    for row in rows:
        td = Path(result_dir) / row["domain"] / row["task_id"]
        steps = traj.load_steps(td)
        if not steps:
            kept.append(row)
            continue
        new_keep, _, gate = decide_keep_to(td, steps, tail_policy, stall_min)
        moved = new_keep != row.get("keep_to")
        blank = (row.get("mode") == REWRITE
                 and not (row.get("statement") or "").strip())
        if moved or blank:
            stale.append({"key": key_of(row), "was": row.get("keep_to"),
                          "now": new_keep, "gate": gate,
                          "why": "cut moved" if moved else "no statement"})
        else:
            row["tail_gate"] = gate
            kept.append(row)
    return kept, stale


def observation_at(td, steps, k):
    """The screen the model is CONDITIONED on when it produces step k.

    build renders step k's observation as `obs_files[k-1]`, i.e. the initial
    screenshot for k=1 and step k-1's post-action screenshot otherwise
    (build.py: `obs_files = [init] + [s.screenshot for s in steps[:-1]]`).

    The first version showed the teacher `steps[k-1].screenshot` -- the screen
    AFTER step k's own action, one frame in the future. The teacher then cited
    evidence the model cannot see at the moment it has to decide to stop, and
    the corpus taught it to assert that evidence anyway. On truncated tails the
    two frames are entirely different screens.
    """
    if k <= 1:
        p = td / "initial_state.png"
        return p if p.is_file() else None
    shot = steps[k - 2].screenshot
    return (td / shot) if shot else None


def render_prompt(tasks_dir, domain, task_id, steps, keep_to, image_path):
    """The teacher sees the task, what was done, and the screen it stops on."""
    instr = load_instruction(tasks_dir, domain, task_id)
    digest = "\n".join("step %d: %s" % (s.num, " | ".join(s.actions)[:110])
                       for s in steps[:keep_to])
    return instr, digest, b64(image_path)


def ask_anthropic(cfg, instr, digest, image_b64, retries=3):
    """-> ({thinking, statement}, error).

    The error is returned rather than swallowed. A failed call used to come
    back empty, which compose_response silently turned into its canned
    fallback -- so a misconfigured model id produced a batch of identical
    endings and nothing anywhere said so.
    """
    from ostg import llm
    blocks = [{"type": "text", "text": "Task: " + instr},
              {"type": "text", "text": "Actions so far:\n" + digest},
              {"type": "text", "text": "Final screen:"},
              {"type": "image", "source": {"type": "base64",
                                           "media_type": "image/png",
                                           "data": image_b64}}]
    for attempt in range(retries):
        try:
            r = llm.call([{"role": "user", "content": blocks}],
                         [{"type": "text", "text": SYSTEM}], cfg,
                         tool=REASON_TOOL)
            text = ""
            for blk in r.get("content", []):
                if blk.get("type") == "tool_use":
                    return blk["input"], None
                if blk.get("type") == "text":
                    text += blk.get("text") or ""
            # Occasionally the model answers in prose instead of calling the
            # tool. Its prose is a usable statement, so keep it rather than
            # discard a good answer over a formatting miss.
            if text.strip():
                return {"statement": text.strip()}, None
            return {}, "no tool_use and no text in reply"
        except Exception as e:                               # noqa: BLE001
            err = "%s: %s" % (type(e).__name__, str(e)[:160])
            if not getattr(e, "transient", False) or attempt == retries - 1:
                return {}, err
            time.sleep(8 * (attempt + 1))
    return {}, "retries exhausted"


def ask_qwen(endpoint, model, key, effort, instr, digest, image_b64):
    """-> ({thinking, statement}, error). See ask_anthropic on surfaced errors."""
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": "Task: " + instr},
                {"type": "text", "text": "Actions so far:\n" + digest},
                {"type": "text", "text": "Final screen:"},
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + image_b64}}]}]
    # guided_json constrains vLLM's reply to the schema instead of fishing a
    # blob out of free text. Without it the teacher answers in prose with
    # markdown headers ("**thinking:** ...") and both fields land in one
    # string -- observed on the first qwen run.
    v = ask(endpoint, model, key, msgs, effort=effort,
            guided=REASON_TOOL["input_schema"])
    if not isinstance(v, dict):
        return {}, "unexpected reply type %s" % type(v).__name__
    if v.get("thinking") or v.get("statement"):
        return v, None
    return {}, str(v.get("error") or "empty reply")[:160]


def canonicalise(key, args, cfg, api_key, parse, infeasible):
    """One trajectory -> the row describing how its ending is repaired.

    Every trajectory gets a row, including the ones needing no change: the
    file is then a complete record of what was decided for each. Rows with a
    null response are skipped by build.
    """
    domain, task_id = key
    td = args.result_dir / domain / task_id
    steps = traj.load_steps(td)
    if not steps:
        return None
    keep_to, stalled, gate = decide_keep_to(td, steps, args.tail_policy,
                                            args.stall_min)
    last = steps[keep_to - 1]
    row = {"domain": domain, "task_id": task_id, "orig_steps": len(steps),
           "keep_to": keep_to, "stalled_tail": stalled, "tail_gate": gate,
           "tail_policy": args.tail_policy}

    mode, why = classify_ending(last.response, keep_to < len(steps),
                                parse, infeasible)
    row["mode"], row["why"] = mode, why
    if mode == KEEP:
        row["response"] = None
        return row
    if mode == APPEND:
        row["response"] = append_terminate(last.response)
        row["statement"] = visible_text(last.response)[:600]
        return row

    screen = observation_at(td, steps, keep_to)
    if screen is None or not screen.is_file():
        return None
    instr, digest, img = render_prompt(args.tasks, domain, task_id, steps,
                                       keep_to, screen)
    if args.backend == "anthropic":
        parts, err = ask_anthropic(cfg, instr, digest, img)
    else:
        parts, err = ask_qwen(args.endpoint, args.model, api_key, args.effort,
                              instr, digest, img)
    thinking = " ".join(str(parts.get("thinking") or "").split())[:600]
    statement = " ".join(str(parts.get("statement") or "").split())[:600]
    row["thinking"], row["statement"] = thinking, statement
    # Which model wrote this ending. The trajectories are Qwen3.8's; an ending
    # written by a different model changes what the arm distils, and the only
    # place that can be recovered later is the row itself.
    row["teacher"] = "%s/%s" % (args.backend, args.model)
    row["response"] = compose_response(thinking, statement)
    if err:
        row["teacher_error"] = err
    return row


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
    ap.add_argument("--backend", choices=("qwen", "anthropic"), default="qwen",
                    help="anthropic writes the justification through ppapi -- "
                         "needed when the cluster has no free GPU for the "
                         "teacher serve, and defensible here because the "
                         "ending's style is being replaced anyway")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--tail-policy", choices=("last-only", "truncate", "auto"),
                    default="auto")
    ap.add_argument("--stall-min", type=int, default=2,
                    help="auto policy: truncate only when this many trailing "
                         "steps did no work")
    ap.add_argument("--harness", default=None,
                    help="OSWorld root, for the action parser used to decide "
                         "how each ending is repaired")
    ap.add_argument("--recompute-tails", action="store_true",
                    help="the tail policy changed: re-derive keep_to for every "
                         "row already in --out, keep the rows whose cut did "
                         "not move, and rewrite only the ones that did")
    ap.add_argument("--dry", type=int, default=0)
    a = ap.parse_args(argv)

    api_key = a.key or os.environ.get("OPENAI_API_KEY") or "EMPTY"
    cfg = anthropic_cfg(a.model) if a.backend == "anthropic" else None
    if cfg:
        cfg["max_tokens"] = 300

    todo = load_target_keys(a.targets)
    prior = read_rows(a.out)

    if a.recompute_tails and prior:
        kept, stale = refresh_tails(a.result_dir, prior, a.tail_policy,
                                    a.stall_min)
        write_rows(a.out, kept)
        prior = kept
        print("recompute: %d rows unchanged, %d stale and queued for rewrite"
              % (len(kept), len(stale)))
        for s in sorted(stale, key=lambda s: s["key"]):
            print("   %-20s %s  keep_to %s -> %s (%s, %s)"
                  % (s["key"][0], s["key"][1][:8], s["was"], s["now"],
                     s["gate"], s["why"]))
        todo = [s["key"] for s in stale] + todo

    done = {key_of(r) for r in prior}
    todo = [k for k in dict.fromkeys(todo) if k not in done]
    if a.dry:
        todo = todo[:a.dry]
    print("%d trajectories to canonicalise" % len(todo))

    parse, infeasible = load_parser(a.harness)
    lock = threading.Lock()
    written, failed, modes = [0], [0], Counter()

    def run(key):
        row = canonicalise(key, a, cfg, api_key, parse, infeasible)
        if row is None:
            return
        with lock:
            with a.out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            written[0] += 1
            modes[row["mode"]] += 1
            if row.get("teacher_error"):
                failed[0] += 1
            print("[%d] %-9s %s/%s keep_to=%d/%d gate=%s :: %s"
                  % (written[0], row["mode"], row["domain"],
                     row["task_id"][:8], row["keep_to"], row["orig_steps"],
                     row["tail_gate"],
                     row.get("teacher_error")
                     or (row.get("statement") or row["why"])[:58]))

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(run, todo))
    print("wrote %d rows %s, %d with a failed teacher call"
          % (written[0], dict(modes), failed[0]))
    return 1 if failed[0] and failed[0] == written[0] else 0


if __name__ == "__main__":
    raise SystemExit(main())
