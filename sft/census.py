"""Corpus quality census — the standard pre-build review gate.

    python -m ostg.sft.census RESULT_DIR [RESULT_DIR ...] [--max-steps 50] [--json OUT]

Counts, per result dir and in aggregate, over score==1.0 trajectories:
  cap-hit (>= max-steps) split by DONE emission; no-DONE passes; illegal
  action names (enum imported from the harness's build_internal_tools_def
  when importable — never a hand-typed copy — frozen fallback otherwise);
  WAIT-heavy trajectories (>30% of actions); grinding steps (identical runs
  >= 8, the build's own threshold); and survivors under the two
  whole-trajectory policies from PLAN-20260816:
    strict   = not cap-hit AND emitted DONE AND no illegal names
    lenient  = only cap-hit-without-DONE dropped, otherwise as strict
Report-only, exit 0 always. Counting rides ostg.sft.traj (score, load_steps,
identical_runs) so the census sees exactly what build will see.

Born 2026-08-16 after the arm-A post-mortem: quality review must be one
pipeline command, not a fresh script per occasion (user rule).
"""
import argparse
import glob
import json
import os
import re
import statistics
import sys

from ostg.sft import traj

_ACTION_RE = re.compile(r"<parameter=action>\s*([a-zA-Z_]+)\s*</parameter>")


def harness_enum():
    """traj.DECLARED is the working enum; the harness import is a live
    consistency check so drift between the two becomes loud, not silent."""
    legal = set(traj.DECLARED)
    try:
        from mm_agents.qwen.prompts import build_internal_tools_def
        blob = json.dumps(build_internal_tools_def(1920, 1080, "relative"))
        m = re.search(r'"enum": \[([^\]]+)\]', blob)
        if m:
            h = set(x.strip().strip('"') for x in m.group(1).split(","))
            if h != legal:
                print("WARNING: harness enum differs from traj.DECLARED: %s"
                      % sorted(h ^ legal))
            return legal, "DECLARED (harness-checked)"
    except Exception:
        pass
    return legal, "DECLARED (harness not importable)"


def census_dir(result_dir, legal, max_steps):
    c = dict(n=0, cap_done=0, cap_nodone=0, nodone=0, illegal_trajs=0,
             illegal_names={}, wait_heavy=0, grind_steps=0, total_steps=0,
             strict=[], lenient=[])
    for rt in sorted(glob.glob(os.path.join(result_dir, "*", "*", "result.txt"))):
        td = os.path.dirname(rt)
        if traj.score(td) != 1.0:
            continue
        steps = traj.load_steps(td)
        if not steps:
            continue
        c["n"] += 1
        ns = len(steps)
        c["total_steps"] += ns
        acts = [a for s in steps for a in s.actions]
        has_done = any(a.strip() == "DONE" for a in acts)
        cap = ns >= max_steps
        bad = set()
        for s in steps:
            for m in _ACTION_RE.finditer(getattr(s, "response", "") or ""):
                if m.group(1) not in legal:
                    bad.add(m.group(1))
        if bad:
            c["illegal_trajs"] += 1
            for b in bad:
                c["illegal_names"][b] = c["illegal_names"].get(b, 0) + 1
        if sum(1 for a in acts if a.strip() == "WAIT") > 0.3 * max(len(acts), 1):
            c["wait_heavy"] += 1
        c["grind_steps"] += len(traj.identical_runs(steps))
        if cap and has_done:
            c["cap_done"] += 1
        if cap and not has_done:
            c["cap_nodone"] += 1
        if not cap and not has_done:
            c["nodone"] += 1
        why = traj.whole_traj_reject(steps, max_steps=max_steps)
        if why is None:
            c["strict"].append(ns)
        if why is None or (why == "cap-hit" and has_done):
            c["lenient"].append(ns)
    return c


def show(name, c):
    med = statistics.median(c["strict"]) if c["strict"] else 0
    print("== %s: %d passes" % (name, c["n"]))
    print("   cap+DONE %d · cap-no-DONE %d · no-DONE %d · illegal %d %s"
          % (c["cap_done"], c["cap_nodone"], c["nodone"],
             c["illegal_trajs"], c["illegal_names"] or ""))
    print("   WAIT>30%%: %d · grinding target-drops: %d/%d steps"
          % (c["wait_heavy"], c["grind_steps"], c["total_steps"]))
    print("   strict survivors: %d trajs / %d step-samples (median %d)"
          % (len(c["strict"]), sum(c["strict"]), med))
    print("   lenient survivors: %d trajs / %d step-samples"
          % (len(c["lenient"]), sum(c["lenient"])))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--max-steps", type=int, default=50)
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)
    legal, src = harness_enum()
    print("action enum source: %s (%d names)" % (src, len(legal)))
    agg = None
    out = {}
    for d in a.dirs:
        c = census_dir(d, legal, a.max_steps)
        show(os.path.basename(d.rstrip("/")), c)
        out[d] = {k: v for k, v in c.items()}
        if agg is None:
            agg = dict(c)
        else:
            for k in ("n", "cap_done", "cap_nodone", "nodone", "illegal_trajs",
                      "wait_heavy", "grind_steps", "total_steps"):
                agg[k] += c[k]
            agg["strict"] = agg["strict"] + c["strict"]
            agg["lenient"] = agg["lenient"] + c["lenient"]
            for b, n in c["illegal_names"].items():
                agg["illegal_names"][b] = agg["illegal_names"].get(b, 0) + n
    if len(a.dirs) > 1 and agg:
        show("AGGREGATE", agg)
    if a.json_out:
        json.dump(out, open(a.json_out, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
