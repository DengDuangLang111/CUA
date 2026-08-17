"""Three-list curation from judge + arbitration + step-audit sidecars.

    python -m ostg.sft.curate --traj J1.jsonl [--traj J2.jsonl ...] \
        [--arb arb.jsonl ...] [--step S1.jsonl ...] \
        --out-prefix out/curate_v11500 [--min-conf 1]

Joins the metadata sidecars and emits four lists plus a report -- raw
trajectories are never touched:

    <prefix>_rescue.jsonl  checker-FAILED trajs the arbiter ruled
                           checker_bug_strict (confidence >= --min-conf):
                           candidate additions to the corpus (冤案赎回).
    <prefix>_drop.jsonl    checker-PASSED trajs the arbiter ruled
                           checker_bug_lenient: convicted fake passes,
                           candidate removals.
    <prefix>_tier1.jsonl   clean keeps -- passed the checker, no flags
                           from any judge or step audit.
    <prefix>_tier2.jsonl   passed the checker but flagged (requirement
                           flaws / weak terminal step / unrefuted judge
                           doubt): feed to `arb --targets`, never dropped
                           on suspicion alone.
    <prefix>_report.json   counts, flag inventory, per-domain breakdown.

Authority rule (user 2026-08-17): 判官提名,仲裁定罪 -- only an
arbitration verdict moves a trajectory across the checker's line; judge
scores and step flags alone can only place a pass into tier2. An
arbitration verdict of checker_right on a flagged pass clears the judge
doubt it examined (the flag drops), because the 6/6 record so far says
trajectory-level judge doubt against a pass is judge error.
"""
import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

# Two kinds of non-satisfied requirement, and they mean opposite things
# (2026-08-17, from reading the rejected trajectories): HARD is a defect
# the evidence shows -- the step was not done. SOFT is the judge admitting
# it cannot see (a file written to disk, a property set in a dialog that
# closed). Filtering on SOFT does not remove bad data, it removes tasks
# whose completion is invisible in screenshots -- which is precisely the
# office-app half of the corpus. Only HARD blocks tier1.
HARD_REQ = {"not_satisfied", "partial"}
SOFT_REQ = {"weak_evidence", "unverifiable"}
BAD_REQ = HARD_REQ | SOFT_REQ
JUDGE_LOW = 5

# A step that types a command without running it looks like a no-op to a
# per-step judge, but the next step presses Enter -- 27 of 67 flagged steps
# are this pattern. Deterministic look-ahead, no re-judging.
EXEC_NEXT = re.compile(r'press\(\s*["\'](return|enter|kp_enter)'
                       r'|hotkey\([^)]*["\'](return|enter)'
                       r'|(typewrite|write)\([^)]*\\n', re.I)


def rows(path):
    for line in Path(path).read_text().splitlines():
        if line.strip():
            yield json.loads(line)


def curate(traj_files, arb_files, step_files, min_conf, min_score=0,
           result_dirs=()):
    truth, flags = {}, defaultdict(set)
    for p in traj_files:
        for r in rows(p):
            if not isinstance(r.get("j_completion"), (int, float)):
                continue
            k = (r["domain"], r["task_id"])
            truth[k] = r["truth"]
            if r["truth"] != 1.0:
                continue
            if r["j_completion"] <= JUDGE_LOW:
                flags[k].add("judge_low")
            # band anatomy (2026-08-17): 7/8 carry real defects (critical
            # requirement miss 12.4%/6.9%), 9 and 10 are equally clean
            # (0.2%/0%) and pass at the same rate -- so the meaningful cut
            # is >=9, and 10 must NOT outrank 9 (that only selects short
            # tasks: median 11 steps vs 16).
            # only on the rubric the band study measured (v2req, which
            # carries a checklist): judge scales are NOT comparable --
            # Opus's 8 sits where Qwen's 9 does, so one numeric cut across
            # both families would flag half the corpus by accident.
            if min_score and r.get("j_requirements") is not None \
                    and r["j_completion"] < min_score:
                flags[k].add(f"below_{min_score}")
            for q in r.get("j_requirements") or []:
                if isinstance(q, dict) and q.get("status") in BAD_REQ:
                    kind = "hard" if q["status"] in HARD_REQ else "soft"
                    flags[k].add(f"req_{kind}_{q['status']}")
    steps_cache = {}

    def next_action(k, num):
        """Actions of the step after `num`, "" when unknown/last."""
        if k not in steps_cache:
            from ostg.sft import traj as _t
            steps_cache[k] = []
            for rd in result_dirs:
                td = Path(rd) / k[0] / k[1]
                if td.is_dir():
                    steps_cache[k] = _t.load_steps(td)
                    break
        nxt = [s for s in steps_cache[k] if s.num > num]
        return " | ".join(nxt[0].actions) if nxt else ""

    for p in step_files:
        for r in rows(p):
            if not isinstance(r.get("j_action_grounded"), int):
                continue
            k = (r["domain"], r["task_id"])
            if r["j_action_grounded"] > 1 and r["j_outcome_intended"] > 1:
                continue
            if result_dirs and EXEC_NEXT.search(next_action(k, r["step"])):
                flags[k].add("weak_step_exempted")   # typed, run next step
                continue
            # terminal stratum steps come from checker-passed trajs only
            flags[k].add("weak_terminal" if r["step"] == r.get("n_steps")
                         else "weak_step")
    verdicts = {}
    for p in arb_files:
        for r in rows(p):
            if r.get("judge_status") != "ok":
                continue
            k = (r["domain"], r["task_id"])
            old = verdicts.get(k)
            if old is None or r.get("a_confidence", 0) >= old.get("a_confidence", 0):
                verdicts[k] = r

    rescue, drop, tier1, tier2 = [], [], [], []
    for k in sorted(truth):
        v = verdicts.get(k)
        base = {"domain": k[0], "task_id": k[1], "truth": truth[k]}
        if truth[k] != 1.0:
            if v and v["a_verdict"] == "checker_bug_strict" \
                    and v.get("a_confidence", 0) >= min_conf:
                rescue.append({**base, "conf": v["a_confidence"],
                               "checker_flaw": v.get("a_checker_flaw", "")})
            continue
        fl = set(flags.get(k, ()))
        if v:
            if v["a_verdict"] == "checker_bug_lenient" \
                    and v.get("a_confidence", 0) >= min_conf:
                drop.append({**base, "conf": v["a_confidence"],
                             "checker_flaw": v.get("a_checker_flaw", ""),
                             "flags": sorted(fl)})
                continue
            if v["a_verdict"] == "checker_right_judge_fooled":
                fl.discard("judge_low")   # doubt examined and refuted
        blocking = {f for f in fl
                    if f.startswith("req_hard_") or f == "weak_terminal"
                    or f == "judge_low" or f.startswith("below_")}
        if blocking:
            tier2.append({**base, "flags": sorted(fl),
                          "arb": v["a_verdict"] if v else None})
        else:
            tier1.append({**base, **({"soft_flags": sorted(fl)} if fl else {})})
    return rescue, drop, tier1, tier2, flags


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--traj", type=Path, action="append", required=True)
    ap.add_argument("--arb", type=Path, action="append", default=[])
    ap.add_argument("--step", type=Path, action="append", default=[])
    ap.add_argument("--out-prefix", required=True)
    ap.add_argument("--min-conf", type=int, default=1)
    ap.add_argument("--result-dir", type=Path, action="append", default=[],
                    help="rollout dirs, enables the look-ahead exemption "
                         "for typed-but-not-yet-run steps")
    ap.add_argument("--min-score", type=int, default=0,
                    help="passes scoring below this land in tier2 (band "
                         "anatomy says 9 is the meaningful cut; 0 = off)")
    a = ap.parse_args(argv)

    rescue, drop, tier1, tier2, flags = curate(a.traj, a.arb, a.step,
                                               a.min_conf, a.min_score,
                                               a.result_dir)
    out = {}
    for name, lst in (("rescue", rescue), ("drop", drop),
                      ("tier1", tier1), ("tier2", tier2)):
        p = Path(f"{a.out_prefix}_{name}.jsonl")
        p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in lst))
        out[name] = len(lst)
    flag_inv = Counter(f for s in flags.values() for f in s)
    doms = Counter(r["domain"] for r in rescue)
    report = {"counts": out, "flag_inventory": dict(flag_inv),
              "rescue_by_domain": dict(doms),
              "inputs": {"traj": [str(p) for p in a.traj],
                         "arb": [str(p) for p in a.arb],
                         "step": [str(p) for p in a.step]},
              "min_conf": a.min_conf, "min_score": a.min_score}
    Path(f"{a.out_prefix}_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
