"""Post-build integrity gate: every image referenced by every sample must
exist and be non-empty. Run by sft/pipeline.sh after every build; also fine
standalone:

    python -m ostg.sft.verify OUT_DIR

Exit 0 = clean. Exit 1 = at least one broken reference, all of them listed.
This is the check the training-data rule demands (row counts lie; prove the
media resolves BEFORE training), promoted from an ad-hoc audit script into the
pipeline so nobody has to re-invent it per run.
"""
import json
import os
import re
import sys


def verify(out_dir, require_terminate=False):
    bad = []
    samples = refs = 0
    # Which task owns each image dir. Existence is not enough: with a
    # slug-keyed image dir, two tasks sharing a slug silently overwrite each
    # other's screenshots and every file still exists, so the old check
    # passed a corpus whose samples pointed at another task's pixels
    # (v11-500, 3 collisions, ~29 samples -- found 2026-08-17). Any image
    # directory referenced by more than one task_id is a hard failure.
    dir_owner = {}
    shared = []
    # Terminal-step coverage. build's whole_traj_filter guarantees the raw
    # trajectory ENDED by decision (a DONE somewhere, no cap-hit), but the
    # think-cap can still quarantine the LAST step's target -- and then the
    # corpus never shows the model the moment of stopping. Checking for the
    # literal string "DONE" does not work: termination is a PARSED action
    # (a turn with no tool call), so the final response is often plain prose.
    # The checkable invariant is step coverage: max(step) must equal n_steps.
    last_step = {}
    # Terminal FORM (only checked with --require-terminate, i.e. on corpora
    # built from a terminalfix pass). Existence and coverage are not enough:
    # the harness scores "no tool call" as DONE, so a corpus can be complete
    # and still teach stopping as a negative action. These counts make the
    # ending explicit and auditable.
    term_form = {}
    for name in ("samples.jsonl", "val_samples.jsonl"):
        p = os.path.join(out_dir, name)
        if not os.path.exists(p):
            continue
        for line in open(p, encoding="utf-8"):
            if not line.strip():
                continue
            s = json.loads(line)
            samples += 1
            meta = s.get("meta") or {}
            key = (meta.get("domain"), meta.get("task_id"))
            step, n = meta.get("step") or 0, meta.get("n_steps") or 0
            seen_max, _ = last_step.get(key, (0, n))
            last_step[key] = (max(seen_max, step), n)
            prev_form = term_form.get(key)
            if prev_form is None or step >= prev_form[0]:
                term_form[key] = (step, s.get("response", ""))
            for m in s.get("messages", []):
                c = m.get("content")
                if not isinstance(c, list):
                    continue
                for part in c:
                    if part.get("type") != "image":
                        continue
                    refs += 1
                    ip = os.path.join(out_dir, part["path"])
                    if not (os.path.exists(ip) and os.path.getsize(ip) > 0):
                        bad.append((name, (s.get("meta") or {}).get("slug", "?"),
                                    part["path"]))
                    d = os.path.dirname(part["path"])
                    meta = s.get("meta") or {}
                    tid = meta.get("task_id") or meta.get("slug") or "?"
                    prev = dir_owner.setdefault(d, tid)
                    if prev != tid:
                        shared.append((d, prev, tid))
    no_done = sorted(k for k, (mx, n) in last_step.items() if n and mx < n)
    bad_form = []
    if require_terminate:
        for k, (_, resp) in sorted(term_form.items()):
            acts = re.findall(r"<parameter=action>\s*([a-z_]+)\s*</parameter>", resp)
            if not acts:
                bad_form.append((k, "no tool call (prose fallback)"))
            elif acts[-1] != "terminate":
                bad_form.append((k, "ends with %s" % acts[-1]))
            elif re.search(r"<parameter=status>\s*(fail|failure|infeasible)",
                           resp, re.I):
                bad_form.append((k, "terminate(failure)"))
    uniq_shared = sorted(set(shared))
    print("verify: %d samples, %d image refs, %d missing-or-empty, "
          "%d image dirs shared across tasks, %d trajectories missing their "
          "terminal step, %d endings not terminate(success)"
          % (samples, refs, len(bad), len(uniq_shared), len(no_done),
             len(bad_form)))
    for name, slug, path in bad[:50]:
        print("  BAD %s %s -> %s" % (name, slug, path))
    for d, a, b in uniq_shared[:20]:
        print("  SHARED-IMAGE-DIR %s claimed by %s and %s" % (d, a, b))
    for k in no_done[:20]:
        print("  TERMINAL-STEP-MISSING %s/%s" % k)
    for k, why in bad_form[:20]:
        print("  ENDING-NOT-TERMINATE %s/%s: %s" % (k[0], k[1], why))
    return 1 if (bad or uniq_shared or no_done or bad_form) else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    sys.exit(verify(args[0], "--require-terminate" in sys.argv))
