"""Build a worst-case memory-smoke set at any image window, by folding the
20-image corpus down to it.

Peak memory is set by the LONGEST sample, and the longest samples here are
text-dominated (the longest 14-image sample carries more text than any
20-image one), so the honest worst case is a long trajectory whose image
window is 14 -- not a trajectory that happens to stop at step 14. Fold the
oldest images out of the 20-image samples and keep every token of text,
which is what the real folding does minus its one-line summaries.

Measured with this on 2026-08-22 (9B, 4 nodes x 2 GPUs, accum 8, zero2_offload,
sdpa, gradient checkpointing, max_length 65536, IMAGE_MAX_TOKEN_NUM 2048):

    10 images   115.8 GiB   82.8% of 139.79   (a2's own training run)
    12 images   123.1 GiB   88.1%             passes, 2/2 steps, 128 rows kept
    14 images   OOM at step 0, rank7 at 137.21 GiB allocated

Note the logged number is max_memory_RESERVED at step boundaries, so the gap
between 12 and 14 is wider than the 3.65 GiB/image those two logged points
imply -- the 14-image run died on a transient allocation that no step-boundary
reading would ever have shown. Read the logged slope as a floor, not a budget.
"""
import json, os, sys

import argparse
_ap = argparse.ArgumentParser(description=__doc__)
_ap.add_argument("--keep", type=int, required=True, help="image window to fold down to")
_ap.add_argument("--n", type=int, default=128, help="how many longest samples to keep")
_ap.add_argument("--src", default="/gpfs/scrubbed/jy050706/sft/data/"
                                  "q38-Bhqs2t-r5nocap-v11500/train_swift.jsonl")
_ap.add_argument("--out", default=None)
_a = _ap.parse_args()
SRC = _a.src
KEEP, N = _a.keep, _a.n
OUT = _a.out or ("/gpfs/scrubbed/jy050706/sft/data/smoke-img%d/train_swift.jsonl" % KEEP)
TAG = "<image>"

def fold(rec, keep):
    imgs = rec.get("images") or []
    drop = len(imgs) - keep
    if drop <= 0:
        return None
    out, removed = [], 0
    for m in rec["messages"]:
        c = str(m.get("content", ""))
        while removed < drop and TAG in c:
            c = c.replace(TAG, "", 1)
            removed += 1
        m = dict(m); m["content"] = c
        out.append(m)
    r = dict(rec); r["messages"] = out; r["images"] = imgs[drop:]
    assert sum(str(m["content"]).count(TAG) for m in out) == keep, "placeholder/image mismatch"
    assert len(r["images"]) == keep
    return r

rows = []
for line in open(SRC, encoding="utf-8"):
    if not line.strip():
        continue
    rec = json.loads(line)
    r = fold(rec, KEEP)
    if r is None:
        continue
    # token proxy: 1024 per image + chars/3.2 for text
    est = KEEP * 1024 + sum(len(str(m["content"])) for m in r["messages"]) / 3.2
    rows.append((est, r))

rows.sort(key=lambda x: -x[0])
sel = rows[:N]
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as fh:
    for _, r in sel:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")

miss = sum(1 for _, r in sel for p in r["images"] if not os.path.exists(p))
print("候选(>14图)样本 %d 条,取最长 %d 条" % (len(rows), len(sel)))
print("估计 token: 最长 %d, 中位 %d, 最短 %d" % (sel[0][0], sel[len(sel)//2][0], sel[-1][0]))
print("图片引用缺失: %d (必须为 0)" % miss)
print("写出:", OUT)
