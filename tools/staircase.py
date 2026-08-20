#!/usr/bin/env python3
"""staircase.py -- quantify the epoch-boundary loss drop ("staircase") of a
training run from its swift logging.jsonl, to test the user hypothesis
(2026-08-19): lighter staircase -> better eval. The drop at each epoch
boundary is the model recognising repeated data, i.e. a memorisation
signature. Pure file analysis: no GPU, no VM.

For each integer epoch boundary k: drop_k = mean(loss over the last ~0.15
epoch before k) - mean(loss over the first ~0.15 epoch after k); also
reported relative to the pre-boundary level. Usage:
  python3 staircase.py NAME=/path/to/logging.jsonl [more...]
"""
import json, sys

WIN = 0.15

def analyse(name, path):
    rows = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "loss" in r and "epoch" in r:
            try:
                rows.append((float(r["epoch"]), float(r["loss"])))
            except (TypeError, ValueError):
                pass
    if not rows:
        print(f"{name:14s} no train rows")
        return
    rows.sort()
    max_ep = rows[-1][0]
    drops = []
    for k in range(1, int(max_ep) + 1):
        pre = [l for e, l in rows if k - WIN <= e < k]
        post = [l for e, l in rows if k <= e <= k + WIN]
        if len(pre) >= 3 and len(post) >= 3:
            p = sum(pre) / len(pre)
            q = sum(post) / len(post)
            drops.append((k, p - q, (p - q) / p if p else 0.0))
    first = sum(l for e, l in rows[:5]) / 5
    last = sum(l for e, l in rows[-5:]) / 5
    ds = " ".join(f"ep{k}:{d:+.3f}({r:+.1%})" for k, d, r in drops)
    mean_rel = sum(r for _, _, r in drops) / len(drops) if drops else float("nan")
    print(f"{name:14s} ep={max_ep:.2f} loss {first:.3f}->{last:.3f}  drops[{ds}]  mean_rel={mean_rel:+.1%}")

if __name__ == "__main__":
    for spec in sys.argv[1:]:
        name, path = spec.split("=", 1)
        analyse(name, path)
