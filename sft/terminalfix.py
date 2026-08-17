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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ostg.sft import traj
from ostg.sft.stepaudit import anthropic_cfg, ask, b64, load_instruction

SYSTEM = """You are writing the final assistant turn of a completed GUI-agent trajectory.

The task has been verified as done. You are given the task, the screen as it looks at the final step, and the actions that led here. Write ONLY the short justification the agent should give before it stops: name the concrete evidence on screen that the requested state exists -- the file that is listed, the value in the cell, the setting that reads as expected.

Rules: at most 60 words. No preamble, no restating the instruction, no markdown, no tool call (one is appended for you). Present tense, concrete nouns from this task. If the screen shows a verification the agent itself ran (a listing, a printed value), cite that."""

REASON_TOOL = {
    "name": "justify",
    "description": "Report the short justification for stopping.",
    "input_schema": {
        "type": "object",
        "properties": {"justification": {"type": "string"}},
        "required": ["justification"],
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

    An empty justification is also stale regardless of the cut: it means the
    teacher call failed and canonical_response substituted the canned
    sentence, so a re-run should retry it rather than bake the fallback in.
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
        failed = not (row.get("reason") or "").strip()
        if moved or failed:
            stale.append({"key": key_of(row), "was": row.get("keep_to"),
                          "now": new_keep, "gate": gate,
                          "why": "cut moved" if moved else "no justification"})
        else:
            row["tail_gate"] = gate
            kept.append(row)
    return kept, stale


def render_prompt(tasks_dir, domain, task_id, steps, keep_to, image_path):
    """The teacher sees the task, what was done, and the screen it stops on."""
    instr = load_instruction(tasks_dir, domain, task_id)
    digest = "\n".join("step %d: %s" % (s.num, " | ".join(s.actions)[:110])
                       for s in steps[:keep_to])
    return instr, digest, b64(image_path)


def ask_anthropic(cfg, instr, digest, image_b64, retries=3):
    """-> (justification, error).

    The error is returned rather than swallowed. A failed call used to come
    back as an empty string, which canonical_response silently turned into the
    canned fallback sentence -- so a misconfigured model id produced a corpus
    full of identical endings and nothing anywhere said so.
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
                    return blk["input"].get("justification", ""), None
                if blk.get("type") == "text":
                    text += blk.get("text") or ""
            # Occasionally the model answers in prose instead of calling the
            # tool. Its prose IS the justification we asked for, so use it --
            # falling through to the canned sentence would discard a good
            # answer over a formatting miss.
            if text.strip():
                return text.strip(), None
            return "", "no tool_use and no text in reply"
        except Exception as e:                               # noqa: BLE001
            err = "%s: %s" % (type(e).__name__, str(e)[:160])
            if not getattr(e, "transient", False) or attempt == retries - 1:
                return "", err
            time.sleep(8 * (attempt + 1))
    return "", "retries exhausted"


def ask_qwen(endpoint, model, key, effort, instr, digest, image_b64):
    """-> (justification, error). See ask_anthropic on why errors surface."""
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": "Task: " + instr},
                {"type": "text", "text": "Actions so far:\n" + digest},
                {"type": "text", "text": "Final screen:"},
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + image_b64}}]}]
    v = ask(endpoint, model, key, msgs, effort=effort)
    if not isinstance(v, dict):
        return "", "unexpected reply type %s" % type(v).__name__
    # ask() returns {"error": raw} when the reply is not JSON -- the normal
    # case here, because we asked for prose, not a JSON object.
    text = v.get("reason") or str(v.get("error") or "")
    return text, None if text else "empty reply"


def canonicalise(key, args, cfg, api_key):
    """One trajectory -> its replacement final turn, or None if unusable."""
    domain, task_id = key
    td = args.result_dir / domain / task_id
    steps = traj.load_steps(td)
    if not steps:
        return None
    keep_to, stalled, gate = decide_keep_to(td, steps, args.tail_policy,
                                            args.stall_min)
    last = steps[keep_to - 1]
    fallback = td / (steps[keep_to - 2].screenshot if keep_to > 1
                     else "initial_state.png")
    screen = td / last.screenshot if last.screenshot else fallback
    if not screen.is_file():
        return None
    instr, digest, img = render_prompt(args.tasks, domain, task_id, steps,
                                       keep_to, screen)
    if args.backend == "anthropic":
        reason, err = ask_anthropic(cfg, instr, digest, img)
    else:
        reason, err = ask_qwen(args.endpoint, args.model, api_key, args.effort,
                               instr, digest, img)
    reason = " ".join(str(reason or "").split())[:600]
    row = {"domain": domain, "task_id": task_id, "orig_steps": len(steps),
           "keep_to": keep_to, "stalled_tail": stalled, "tail_gate": gate,
           "tail_policy": args.tail_policy, "reason": reason,
           "response": canonical_response(reason)}
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

    lock = threading.Lock()
    written, failed = [0], [0]

    def run(key):
        row = canonicalise(key, a, cfg, api_key)
        if row is None:
            return
        with lock:
            with a.out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            written[0] += 1
            if row.get("teacher_error"):
                failed[0] += 1
            print("[%d] %s/%s keep_to=%d/%d stall=%d gate=%s :: %s"
                  % (written[0], row["domain"], row["task_id"][:8],
                     row["keep_to"], row["orig_steps"], row["stalled_tail"],
                     row["tail_gate"],
                     row.get("teacher_error") or row["reason"][:60]))

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(run, todo))
    print("wrote %d rows, %d with a failed teacher call" % (written[0],
                                                            failed[0]))
    return 1 if failed[0] and failed[0] == written[0] else 0


if __name__ == "__main__":
    raise SystemExit(main())
