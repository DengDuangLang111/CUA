"""Result directories -> SFT records.

    python -m ostg.filter --results R1 [--results R2 ...] --taskroot out/tasks \
        --out out/sft.jsonl

Keeps only rollouts that scored exactly 1.0. When a task succeeded more than
once, keeps ONE: the shortest trajectory that shows no sign of bypassing the GUI.
Shortest alone is the wrong rule -- the shortest run is often the one that did
the whole job with a shell one-liner, which is exactly the behaviour a GUI agent
should not be trained on.

Diversity metadata is recovered from the task JSON's "taskgen" block, because a
result directory contains nothing about the task: no instruction, no metadata,
just result.txt / traj.jsonl / step_*.png (lib_run_single.py:44-68).
"""
import argparse
import collections
import json
import re
from pathlib import Path

# Signs the agent did the work in a shell instead of the GUI.
BYPASS = re.compile(
    r"gnome-terminal|xterm|konsole|python3?\s+-c|\bawk\b|\bsed\s+-i|\bxargs\b|"
    r"libreoffice\s+--convert-to|\bsoffice\b|>>?\s*/home/user",
    re.I,
)


def scan(results_dirs):
    """-> {task_id: [rollout, ...]} over every result directory given."""
    out = collections.defaultdict(list)
    for rd in results_dirs:
        rd = Path(rd)
        for res in sorted(rd.glob("*/*/result.txt")):
            d = res.parent
            try:
                score = float(res.read_text().strip())
            except ValueError:
                continue
            steps = read_traj(d)
            out[d.name].append({
                "task_id": d.name,
                "domain": d.parent.name,
                "run_dir": str(d),
                "score": score,
                "steps": steps,
                "n_steps": len(steps),
                "bypass_hint": any(BYPASS.search(s.get("action") or "") for s in steps),
            })
    return out


def read_traj(d):
    f = d / "traj.jsonl"
    if not f.is_file():
        return []
    rows = []
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if "step_num" not in r:  # run_multienv writes {"Error": ...} lines on a crash
            continue
        shot = r.get("screenshot_file")
        rows.append({
            "step": r["step_num"],
            "action": r.get("action"),
            "response": r.get("response"),
            "screenshot": str((d / shot).resolve()) if shot else None,
        })
    rows.sort(key=lambda x: x["step"])
    return rows


def load_meta(taskroot, domain, task_id):
    p = Path(taskroot) / "examples" / domain / (task_id + ".json")
    if not p.is_file():
        return {}
    t = json.loads(p.read_text())
    return {"instruction": t.get("instruction"), **(t.get("taskgen") or {})}


def pick(rollouts):
    """Best successful rollout: prefer no bypass hint, then fewest steps."""
    wins = [r for r in rollouts if abs(r["score"] - 1.0) < 1e-9 and r["n_steps"] > 0]
    if not wins:
        return None
    return sorted(wins, key=lambda r: (r["bypass_hint"], r["n_steps"]))[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", action="append", required=True,
                    help="a result dir (simple-path layout); repeatable for k rollouts")
    ap.add_argument("--taskroot", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("out/sft.jsonl"))
    args = ap.parse_args()

    byid = scan(args.results)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    kept, records = 0, []
    for tid, rollouts in sorted(byid.items()):
        best = pick(rollouts)
        if not best:
            continue
        meta = load_meta(args.taskroot, best["domain"], tid)
        records.append({
            "task_id": tid,
            "domain": best["domain"],
            "slug": meta.get("slug"),
            "instruction": meta.get("instruction"),
            "axes": {"artifact": meta.get("artifact"), "source": meta.get("source"),
                     "app_count": meta.get("app_count")},
            "apps": meta.get("apps"),
            "drawn_from": meta.get("drawn_from"),
            "controls": meta.get("controls"),
            "score": best["score"],
            "n_steps": best["n_steps"],
            "bypass_hint": best["bypass_hint"],
            "attempts": len(rollouts),
            "run_dir": best["run_dir"],
            "steps": best["steps"],
        })
        kept += 1

    with args.out.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ---- coverage ----------------------------------------------------------
    runs = sum(len(v) for v in byid.values())
    print("%d tasks with results, %d rollouts, %d kept -> %s" % (len(byid), runs, kept, args.out))
    if not records:
        return 0

    print("\nyield by axis")
    tried = collections.Counter()
    for tid, rollouts in byid.items():
        m = load_meta(args.taskroot, rollouts[0]["domain"], tid)
        tried[(m.get("artifact"), m.get("source"))] += 1
    won = collections.Counter((r["axes"]["artifact"], r["axes"]["source"]) for r in records)
    for cell, n in tried.most_common():
        print("  %-22s %-22s %d/%d" % (cell[0], cell[1], won.get(cell, 0), n))

    print("\nsteps: min=%d median=%d max=%d   bypass_hint on %d kept"
          % (min(r["n_steps"] for r in records),
             sorted(r["n_steps"] for r in records)[len(records) // 2],
             max(r["n_steps"] for r in records),
             sum(1 for r in records if r["bypass_hint"])))

    # Yield split by build-time control status: this is how you find out whether a
    # failed control actually predicts a dead task, instead of assuming it.
    cs = collections.Counter()
    for tid, rollouts in byid.items():
        m = load_meta(args.taskroot, rollouts[0]["domain"], tid)
        c = m.get("controls") or {}
        key = (c.get("negative"), c.get("positive"))
        cs[key] = cs[key]
    tally = collections.defaultdict(lambda: [0, 0])
    for tid, rollouts in byid.items():
        m = load_meta(args.taskroot, rollouts[0]["domain"], tid)
        c = m.get("controls") or {}
        key = "neg=%s,pos=%s" % (c.get("negative"), c.get("positive"))
        tally[key][1] += 1
        if any(abs(r["score"] - 1.0) < 1e-9 for r in rollouts):
            tally[key][0] += 1
    print("\nyield by build-time control status")
    for k, (w, t) in sorted(tally.items()):
        print("  %-28s %d/%d" % (k, w, t))

    # ---- tasks that produced nothing --------------------------------------
    man = Path(args.taskroot) / "manifest.json"
    if man.is_file():
        allids = {i for v in json.loads(man.read_text()).values() for i in v}
        missing = sorted(allids - set(byid))
        if missing:
            print("\n%d task(s) in the manifest produced NO result.txt "
                  "(crashed in the evaluator, or never ran):" % len(missing))
            for i in missing[:20]:
                print("  " + i)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
