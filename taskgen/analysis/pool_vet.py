#!/usr/bin/env python3
"""pool_vet.py -- the vetting sheet for pool-fillable gap cells.

The adversarial audit's core lesson (2026-08-20): cell counts are a selection
INDEX, not evidence -- most of v1's pool-fillable claims were regex artifacts,
and include/exclude-style checkers admit terminal-only solutions, so a task
"about" a GUI action can yield success trajectories that never demonstrate it.
Selection therefore needs, per candidate: the FULL instruction, the evaluator
in enough detail to judge whether it forces the target artifact, and any
historical teacher rollout of the same task id so pass-rate estimates start
from stock data instead of fresh GPU pilots.

This tool reuses taxonomy_tag v2 wholesale (same cells, same flags) and adds:
  - per flagged cell, every pool candidate with era, id, instruction,
    evaluator func + a compact dump of its config
  - a rollout-history index built from result.txt files under --results-root:
    each candidate reports where it was rolled and what it scored, giving
    (successes, attempts) per cell for the Beta(1,1) pass-rate prior

Usage (WSL, /tmp holds coverage_audit.py + taxonomy_tag.py):
  python3 pool_vet.py --train-instr /tmp/train_instr.json \
      --pool-glob "/mnt/d/research/os-simple-taskgen-v8/out/runs/v11*/examples/*/*.json"
"""
import argparse, json, os, subprocess, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from coverage_audit import load_corpus, funcs
from taxonomy_tag import (app_of_generated, load_osworld, load_pool, tag,
                          is_gap, ORDER)


def rollout_index(root):
    """task id -> [(run_dir, score)] from every result.txt under root."""
    try:
        out = subprocess.run(
            ["find", root, "-maxdepth", "6", "-name", "result.txt"],
            capture_output=True, text=True, timeout=600).stdout
    except Exception:
        return {}
    idx = defaultdict(list)
    for p in out.splitlines():
        tid = os.path.basename(os.path.dirname(p))
        run = p[len(root):].lstrip("/").split("/")[0:2]
        try:
            score = float(open(p).read().split()[0])
        except Exception:
            continue
        idx[tid].append(("/".join(run), score))
    return idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-instr", required=True)
    ap.add_argument("--taskgen-glob",
                    default="/mnt/d/research/os-simple-taskgen-v8/out/runs/*/examples/*/*.json")
    ap.add_argument("--pool-glob", default=None)
    ap.add_argument("--osworld-meta",
                    default="/mnt/d/research/OSWorld/evaluation_examples/test_all.json")
    ap.add_argument("--examples-root",
                    default="/mnt/d/research/OSWorld/evaluation_examples")
    ap.add_argument("--results-root",
                    default="/mnt/d/research/OSWorld/results_generated")
    a = ap.parse_args()

    tr, _slug, found, _ = load_corpus(a.train_instr, a.taskgen_glob)
    trn = tag([(app_of_generated(d), d, None) for d in found.values()])
    osw = [x for x in tag(load_osworld(a.osworld_meta, a.examples_root))
           if x[2] != "infeasible"]
    pool_raw = load_pool(a.pool_glob or a.taskgen_glob, tr)
    pool = tag(pool_raw)
    raw_by_key = {}
    for (app, d, era) in pool_raw:
        tid = d.get("id") or (d.get("ostg") or {}).get("slug") or "?"
        raw_by_key[tid] = d

    rows = {}
    for src, items in (("osw", osw), ("train", trn), ("pool", pool)):
        for app, alist, _o, _i, _e, _t in items:
            for act in alist:
                r = rows.setdefault((app, act), {"osw": 0, "train": 0, "pool": 0})
                r[src] += 1
    flagged = {k for k, v in rows.items() if is_gap(v) and v["pool"] > 0}

    idx = rollout_index(a.results_root)
    print(f"rollout 历史索引: {len(idx)} 个任务 id 有 result.txt")

    for app in ORDER:
        for (capp, act) in sorted(flagged):
            if capp != app:
                continue
            v = rows[(capp, act)]
            print(f"\n===== {app}/{act}  OSWorld {v['osw']} | 语料 {v['train']} | 池 {v['pool']}")
            for (papp, alist, _o, _i, era, tid) in pool:
                if papp != app or act not in alist:
                    continue
                d = raw_by_key.get(tid, {})
                ins = (d.get("instruction") or "").replace("\n", " ")
                ev = d.get("evaluator") or {}
                sl = (d.get("ostg") or {}).get("slug") or tid
                hist = idx.get(d.get("id") or "", [])
                hs = ("; ".join(f"{r}={s:g}" for r, s in hist[:4])
                      if hist else "无 rollout 记录")
                print(f"  - {sl}  [{era}]")
                print(f"    指令: {ins[:180]}")
                print(f"    checker: {json.dumps(funcs(ev), ensure_ascii=False)} "
                      f"{json.dumps(ev, ensure_ascii=False)[:220]}")
                print(f"    历史: {hs}")


if __name__ == "__main__":
    main()
