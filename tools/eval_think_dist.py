#!/usr/bin/env python3
"""eval_think_dist.py -- eval-time behaviour distributions per arm.

Measures what the model actually DID at eval, not what the corpus contained:
  * think length per step (characters -- the same unit the build-time
    --think-cap used, so the "over 2048" column is directly comparable to
    the corpus-side cap and to the earlier RESULTS 5.10 / 5.12 readings)
  * steps per task, split by win/loss
  * how each task ended (DONE / FAIL / hit the step cap) and how many DONE
    calls scored zero -- the "false success" rate that tracks score across
    every arm measured so far

Termination is read from the LAST traj.jsonl action field, never from the
step-file count: a task that calls DONE exactly at the step limit looks like
a cap-hit by file count (this inflated an earlier reading 14 -> 18).

Usage: eval_think_dist.py NAME=/path/to/eval50-dir [NAME=... ...]
"""
import json, os, re, sys, glob
import statistics as st

THINK = re.compile(r"<think>([\s\S]*?)</think>")

def pct(xs, p):
    if not xs: return 0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100.0 * (len(xs) - 1))))]

def analyse(name, D):
    think, steps_w, steps_l = [], [], []
    done = fail = cap = fd = 0
    n = 0; score = 0.0
    for td in sorted(glob.glob(os.path.join(D, "*", "*"))):
        rt, tj = os.path.join(td, "result.txt"), os.path.join(td, "traj.jsonl")
        if not (os.path.isdir(td) and os.path.exists(rt) and os.path.exists(tj)):
            continue
        try: sc = float(open(rt).read().split()[0])
        except (ValueError, IndexError): sc = 0.0
        n += 1; score += sc
        last = None; nstep = 0
        for line in open(tj, encoding="utf-8"):
            if not line.strip(): continue
            try: r = json.loads(line)
            except json.JSONDecodeError: continue
            last = r; nstep += 1
            m = THINK.search(str(r.get("response") or ""))
            if m: think.append(len(m.group(1)))
        (steps_w if sc > 0.5 else steps_l).append(nstep)
        a = str(last.get("action", "")).strip().upper() if last else ""
        if a.startswith("DONE"):
            done += 1
            if sc <= 0.5: fd += 1
        elif a.startswith("FAIL"): fail += 1
        else: cap += 1
    if not n: 
        print(f"{name}: no data"); return
    over = sum(1 for t in think if t > 2048)
    print(f"\n=== {name}   {n}/50 题  分={100*score/50:.2f}")
    print(f"  think 字符/步 (n={len(think)}): "
          f"p50={pct(think,50)}  p90={pct(think,90)}  p99={pct(think,99)}  "
          f"max={max(think)}  mean={int(st.mean(think))}")
    print(f"  超 2048 字符的步: {over}/{len(think)} ({100.0*over/len(think):.1f}%)")
    print(f"  步数: 赢 {len(steps_w)} 题 中位 {pct(steps_w,50)} 均 {st.mean(steps_w):.1f} | "
          f"输 {len(steps_l)} 题 中位 {pct(steps_l,50)} 均 {st.mean(steps_l):.1f}")
    print(f"  收尾: DONE={done} FAIL={fail} 撞上限={cap} | 假报成功={fd} "
          f"({100.0*fd/max(done,1):.0f}% 的 DONE 是假的)")

if __name__ == "__main__":
    for spec in sys.argv[1:]:
        nm, d = spec.split("=", 1)
        analyse(nm, d)
