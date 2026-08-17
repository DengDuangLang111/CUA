#!/bin/bash
# THE data-filter pipeline. One command, same for human and agent:
#
#     bash sft/pipeline.sh RESULT_DIR TASKS_DIR OUT_DIR
#
# e.g.  bash sft/pipeline.sh \
#         /mnt/d/research/OSWorld/results_generated/qwen38-27b-local/v11-100-t1-20260814 \
#         /mnt/d/research/os-simple-taskgen-v8/out/runs/v11-all \
#         /mnt/d/research/ostg-v11.1/out/sft-q38-v11100
#
# Runs on WSL from the ostg repo root (needs the OSWorld venv for mm_agents).
# Steps, fixed, no per-run decisions:
#   1. build    -- score==1.0 trajectories -> per-step samples via the agent's
#                  own context code; filters per TRAINING.md (tail_run 5,
#                  identical_runs 8, low_diversity_tail on cap-hitters,
#                  hallucinated-target drop, mp4 initial fallback for legacy runs)
#   2. verify   -- every image referenced by every sample exists and is
#                  non-empty; HARD FAIL otherwise (nothing half-broken ships)
#   3. report   -- print report.json so the drop counts are on the record
# Optional: IMAGE_CACHE=DIR hardlinks identical re-encodes from a prior build
# (derived builds: 15-45min of DrvFs image writing -> seconds).
# Optional: THINK_CAP=N drops steps whose current-target <think> exceeds N
# estimated tokens (quarantined to think_quarantine.jsonl; B-tailclean flow).
# Changing WHAT the pipeline does happens in ostg/sft/*.py through review,
# never by editing this file per run.
set -e
[ $# -eq 3 ] || { echo "usage: $0 RESULT_DIR TASKS_DIR OUT_DIR"; exit 2; }
RESULT_DIR=$1; TASKS_DIR=$2; OUT_DIR=$3
P=${OSTG_PYTHON:-/mnt/d/research/OSWorld/.venv/bin/python}
export PYTHONPATH=.:${OSWORLD_ROOT:-/mnt/d/research/OSWorld}

echo "== census (report-only pre-build gate; --tasks adds the slug gate)"
$P -m ostg.sft.census "$RESULT_DIR" --tasks "$TASKS_DIR"

echo "== build"
$P -m ostg.sft.build "$RESULT_DIR" --tasks "$TASKS_DIR" --out "$OUT_DIR" \
    --initial-fallback mp4 --whole-traj-filter ${THINK_CAP:+--think-cap $THINK_CAP} \
    ${IMAGE_CACHE:+--image-cache $IMAGE_CACHE}
echo "== verify"
$P -m ostg.sft.verify "$OUT_DIR"
echo "== to_swift"
$P -m ostg.sft.to_swift "$OUT_DIR"
echo "== report"
cat "$OUT_DIR/report.json"
echo
echo "PIPELINE OK: $OUT_DIR"
