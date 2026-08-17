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
doubt it examined (the flag drops), because the record so far says
trajectory-level judge doubt against a pass is judge error.

WHAT BLOCKS, AND WHY THE FIRST VERSION GOT IT WRONG (rev 2, 2026-08-17)
----------------------------------------------------------------------
The first Bhqs build gated tier1 on the FREE 0-10 score (--min-score 9).
That was backwards, by our own measurements:

  * The free score does not stratify. 137 of 181 passing trajectories sat
    on 9, and INSIDE band 9 every signal we could compute (steps, derived
    score, all four subscores, difficulty, app count, citation errors)
    separated checker-passes from checker-failures by ~0.0. The judge has
    no ranking power in the region the gate operated in.
  * The requirement checklist does stratify: critical-requirement miss
    rate runs 12.4% / 6.9% / 0.2% / 0% across bands 7 / 8 / 9 / 10.
  * Consequence: of 62 removals, 39 were removed for scoring 8 instead of
    9, and 15 had a PERFECT checklist (derived 10.0). Band 8 carries a
    ~7% real-defect rate, so those 39 removals cost ~36 good trajectories
    to clear ~3 flawed ones.

So free score is now RECORDED, never gating. Blocking is evidence-based:

    hard requirement defect   status not_satisfied / partial -- the judge
                              points at a specific thing the evidence
                              shows was not done.   BLOCKS.
    arbitration conviction    checker_bug_lenient.  BLOCKS.
    soft requirement flag     weak_evidence / unverifiable -- the judge
                              saying it cannot SEE (a file on disk, a
                              dialog that closed). Records, never blocks:
                              filtering on it removes tasks whose success
                              is invisible in screenshots, i.e. the
                              office half of the corpus.
    weak terminal step        step-level doubt. tier2 (send to arb), stays
                              in the corpus until arbitration convicts.
    judge_low on a pass       tier2 only. Every such case we arbitrated
                              came back "judge was wrong".

tier2 is IN the corpus by default -- it is a work list for arbitration,
not a bin. Dropping on suspicion is exactly what the authority rule
forbids.
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
           result_dirs=(), adv_files=(), tier2_out=False):
    truth, flags = {}, defaultdict(set)
    for p in traj_files:
        for r in rows(p):
            if not isinstance(r.get("j_completion"), (int, float)):
                continue
            k = (r["domain"], r["task_id"])
            truth[k] = r["truth"]
            # Requirement flags are computed for FAILURES too: a rescue has
            # to clear the same hard-defect bar as a pass, or the corpus
            # would hold rescues to a looser standard than the trajectories
            # it already contains.
            for q in r.get("j_requirements") or []:
                if isinstance(q, dict) and q.get("status") in HARD_REQ:
                    flags[k].add(f"req_hard_{q['status']}")
            if r["truth"] != 1.0:
                continue
            if r["j_completion"] <= JUDGE_LOW:
                flags[k].add("judge_low")
            # Recorded, never blocking (see the module docstring): the
            # free score has no ranking power inside the good band. Kept
            # as a flag so tier2 work lists can still sort by it.
            if min_score and r.get("j_requirements") is not None \
                    and r["j_completion"] < min_score:
                flags[k].add(f"note_below_{min_score}")
            for q in r.get("j_requirements") or []:
                if isinstance(q, dict) and q.get("status") in SOFT_REQ:
                    flags[k].add(f"req_soft_{q['status']}")
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
    # Verdict selection used to be "later file with >= confidence wins",
    # which made the --arb argument ORDER decide the outcome and treated a
    # v1 ruling as equal to a v2 one. The adversarial pass exposed it: 8 of
    # 16 revoked rescues had a v2 ruling of checker_right that a v1 ruling
    # had silently overridden. Now: v2 outranks v1 (two-stage arbitration
    # derives its own audit before seeing the verdict, so it is the less
    # anchored protocol), and a rescue needs UNANIMITY among the rulings at
    # the top rank -- contested evidence does not enter training data.
    all_rulings = defaultdict(list)
    for p in arb_files:
        for r in rows(p):
            if r.get("judge_status") == "ok" and r.get("a_verdict"):
                c = r.get("a_confidence")
                if not isinstance(c, int) or not 0 <= c <= 2:
                    r["a_confidence"] = 0      # schema violation seen in the
                                               # wild (conf=96); do not trust
                all_rulings[(r["domain"], r["task_id"])].append(r)
    verdicts, contested = {}, set()
    for k, rs in all_rulings.items():
        top = 2 if any(r.get("protocol") == "v2" for r in rs) else 1
        cand = [r for r in rs
                if (2 if r.get("protocol") == "v2" else 1) == top]
        kinds = {r["a_verdict"] for r in cand}
        if len(kinds) > 1:
            contested.add(k)
        verdicts[k] = max(cand, key=lambda r: r.get("a_confidence", 0))

    rescue, drop, tier1, tier2 = [], [], [], []
    for k in sorted(truth):
        v = verdicts.get(k)
        base = {"domain": k[0], "task_id": k[1], "truth": truth[k]}
        if truth[k] != 1.0:
            if v and v["a_verdict"] == "checker_bug_strict" \
                    and v.get("a_confidence", 0) >= min_conf \
                    and k not in contested:
                hard = {f for f in flags.get(k, ()) if f.startswith("req_hard_")}
                if hard:
                    drop.append({**base, "flags": sorted(hard),
                                 "reason": "rescue_with_hard_defect"})
                else:
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
        # Evidence-based blocking only. weak_terminal / judge_low /
        # req_soft_* / note_below_* are work-list markers, not evictions.
        blocking = {f for f in fl if f.startswith("req_hard_")}
        if blocking:
            drop.append({**base, "conf": None, "checker_flaw": "",
                         "flags": sorted(fl), "reason": "hard_requirement_defect"})
            continue
        if fl:
            tier2.append({**base, "flags": sorted(fl),
                          "arb": v["a_verdict"] if v else None})
        else:
            tier1.append(base)
    # An adversarial pass defends the checker against each rescue ruling;
    # a rescue that the defence overturns never enters the corpus.
    revoked = set()
    for p in adv_files:
        for r in rows(p):
            if r.get("judge_status") == "ok" and \
                    r.get("d_verdict") == "checker_defensible":
                revoked.add((r["domain"], r["task_id"]))
    if revoked:
        kept = [r for r in rescue if (r["domain"], r["task_id"]) not in revoked]
        for r in rescue:
            if (r["domain"], r["task_id"]) in revoked:
                r["revoked_by_adversarial"] = True
                drop.append(r)
        rescue = kept
    return rescue, drop, tier1, tier2, flags, contested


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
                    help="RECORD-ONLY marker for passes scoring below this "
                         "(free score never gates; see module docstring)")
    ap.add_argument("--adv", type=Path, action="append", default=[],
                    help="adversarial re-check jsonl (arb --protocol adv); "
                         "rescues ruled checker_defensible are revoked")
    ap.add_argument("--corpus-includes-tier2", action="store_true",
                    help="write tier2 into <prefix>_keep.jsonl together with "
                         "tier1 (default: tier2 is a work list, and keep = "
                         "tier1 + tier2 since suspicion alone never drops)")
    a = ap.parse_args(argv)

    rescue, drop, tier1, tier2, flags, contested = curate(
        a.traj, a.arb, a.step, a.min_conf, a.min_score, a.result_dir, a.adv)
    out = {}
    # keep = what the corpus should contain on the pass side: clean plus
    # flagged-but-unconvicted. Only hard defects and arbitration
    # convictions leave.
    keep = tier1 + [{k: v for k, v in r.items() if k != "arb"} for r in tier2]
    for name, lst in (("rescue", rescue), ("drop", drop),
                      ("tier1", tier1), ("tier2", tier2), ("keep", keep)):
        p = Path(f"{a.out_prefix}_{name}.jsonl")
        p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in lst))
        out[name] = len(lst)
    flag_inv = Counter(f for s in flags.values() for f in s)
    doms = Counter(r["domain"] for r in rescue)
    report = {"counts": out, "corpus_size": len(keep) + len(rescue),
              "contested_rulings": len(contested),
              "flag_inventory": dict(flag_inv),
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
