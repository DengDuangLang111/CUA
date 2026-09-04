#!/usr/bin/env python3
"""Task-balanced loss weighting for the mixbtf corpus (route A, per-message loss_scale).

Problem: each trajectory (task) is expanded to one training sample per step, so a
50-step task contributes 50x the loss weight of a 1-step task; the longest 20% of
tasks carry ~39% of the loss (Gini 0.32). We rebalance so every TASK contributes
equal total loss weight, WITHOUT touching swift internals: swift's loss_scale reads
a per-assistant-message `loss_scale` float (seq2seq base.py `_inner_call`), applied
as the per-token weight on the last-round response when `--is_binary_loss_scale false`.

Weight: w_i = c / N_T(i), where N_T = #samples (steps) of the sample's trajectory,
and c is chosen so the TOKEN-WEIGHTED mean of w equals 1 -- i.e. Sum(w_i * tok_i) =
Sum(tok_i). swift's loss denominator is the (unweighted) labeled-token count
(`num_items_in_batch = (labels!=-100).sum()`, seq2seq_trainer.py:198), so the total
loss magnitude is preserved and the effective LR is unchanged. Only the RELATIVE
per-task weighting changes -> clean single variable vs the mixbtf9b baseline.

trajid = parent dir of the images (…/images/<trajid>/obs_NNN.png). loss_scale is
written on messages[-1] (the single assistant turn per sample). Images are NOT
copied; the new jsonl reuses the original absolute image paths.

Run on Tillicum:  venv/bin/python3 make-taskw-weights.py
Reads  /gpfs/scrubbed/jy050706/sft/data/mixbtf-{v16-main,v16-pilot,v11new-500,v11new-all}/train_swift_abs.jsonl
Writes /gpfs/scrubbed/jy050706/sft/data/mixbtf-taskw-<same>/train_swift_abs.jsonl
"""
import json, os, sys, hashlib, collections
import numpy as np
from transformers import AutoTokenizer

BASE = "/gpfs/scrubbed/jy050706/sft"
MODEL = f"{BASE}/models/Qwen3.5-9B"
PARTS = ["v16-main", "v16-pilot", "v11new-500", "v11new-all"]
SELF_HASH = hashlib.md5(open(__file__, "rb").read()).hexdigest()
print(f"[make-taskw-weights] code md5={SELF_HASH}")

tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)

def trajid_of(sample):
    imgs = sample.get("images", [])
    if not imgs:
        return None
    return os.path.basename(os.path.dirname(imgs[0]))

# ---- pass 1: collect trajectory step counts N_T and per-sample loss-token counts ----
rows = []            # (part, raw_line_dict, trajid, tok_i)
N = collections.Counter()
for part in PARTS:
    fp = f"{BASE}/data/mixbtf-{part}/train_swift_abs.jsonl"
    for line in open(fp, encoding="utf-8"):
        if not line.strip():
            continue
        d = json.loads(line)
        tid = trajid_of(d)
        assert tid, f"no images / trajid in a sample of {part}"
        assert d["messages"][-1]["role"] == "assistant", "last message must be the assistant action"
        ti = len(tok(d["messages"][-1]["content"], add_special_tokens=False).input_ids)
        rows.append((part, d, tid, ti))
        N[tid] += 1

n_traj = len(N)
n_samp = len(rows)
sum_tok = sum(ti for *_, ti in rows)
sum_tok_over_N = sum(ti / N[tid] for _, _, tid, ti in rows)
c = sum_tok / sum_tok_over_N          # makes token-weighted mean(w) == 1

# ---- pass 2: write weighted jsonl ----
open_files = {}
per_traj_wsum = collections.Counter()
w_all = []
for part, d, tid, ti in rows:
    w = c / N[tid]
    d["messages"][-1]["loss_scale"] = w
    out = f"{BASE}/data/mixbtf-taskw-{part}"
    os.makedirs(out, exist_ok=True)
    if part not in open_files:
        open_files[part] = open(f"{out}/train_swift_abs.jsonl", "w", encoding="utf-8")
    open_files[part].write(json.dumps(d, ensure_ascii=False) + "\n")
    per_traj_wsum[tid] += w
    w_all.append(w)
for f in open_files.values():
    f.close()

# ---- report ----
w_all = np.array(w_all)
tok_wmean = float(np.average(w_all, weights=[ti for *_, ti in rows]))
samp_mean = float(w_all.mean())
tw = np.array(list(per_traj_wsum.values()))   # each trajectory's total sample-weight (should be ~c, constant)
print(f"trajectories={n_traj}  samples={n_samp}  c={c:.4f}  (mean steps={n_samp/n_traj:.2f})")
print(f"per-sample w: min={w_all.min():.4f} p50={np.percentile(w_all,50):.4f} p90={np.percentile(w_all,90):.4f} max={w_all.max():.4f}")
print(f"CHECK token-weighted mean(w) = {tok_wmean:.4f}  (target 1.0 -> loss magnitude preserved)")
print(f"CHECK sample mean(w)         = {samp_mean:.4f}")
print(f"CHECK per-trajectory weight-sum: min={tw.min():.4f} max={tw.max():.4f} std={tw.std():.4f}  (should all == c={c:.4f})")
print(f"longest task (50 steps) per-step w = {c/50:.4f}  vs shortest (1 step) = {c/1:.4f}")
print("OUT dirs: " + ", ".join(f"mixbtf-taskw-{p}" for p in PARTS))
