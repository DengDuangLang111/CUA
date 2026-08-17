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
import sys


def verify(out_dir):
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
    uniq_shared = sorted(set(shared))
    print("verify: %d samples, %d image refs, %d missing-or-empty, "
          "%d image dirs shared across tasks, %d trajectories missing their "
          "terminal step"
          % (samples, refs, len(bad), len(uniq_shared), len(no_done)))
    for name, slug, path in bad[:50]:
        print("  BAD %s %s -> %s" % (name, slug, path))
    for d, a, b in uniq_shared[:20]:
        print("  SHARED-IMAGE-DIR %s claimed by %s and %s" % (d, a, b))
    for k in no_done[:20]:
        print("  TERMINAL-STEP-MISSING %s/%s" % k)
    return 1 if (bad or uniq_shared or no_done) else 0


if __name__ == "__main__":
    sys.exit(verify(sys.argv[1]))
