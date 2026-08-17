#!/bin/bash
# arb_stream.sh -- arbitrate disagreements WHILE the judge sweep is still
# running (user directive 2026-08-17: "v2req跑着,过程跑完的就立刻审核").
# arb.py is resume-safe (it skips trajectories already in --out), so each
# pass only picks up rows the sweep added since the last one. When the
# sweep process disappears, one final pass sweeps the tail.
#
#   POOL=v11500 \
#   RESULT_DIR=/mnt/d/research/OSWorld/results_generated/qwen38-27b-local/v11-500-t1ms50-20260814 \
#   TASKS=/mnt/d/research/os-simple-taskgen-v8/out/runs/v11-500-final \
#   QWEN=out/trajaudit2req_v11500_qwen.jsonl OPUS=out/trajaudit_v11500_opus.jsonl \
#   bash ostg/sft/tools/arb_stream.sh
#
# WATCH  = the judge output path whose writer process gates the loop
#          (defaults to $QWEN); INTERVAL seconds between passes (300).
# Run it from a foreground driver that holds its ssh session open --
# nohup + a transient ssh gets the orphan killed by WSL before it starts.
set -u
: "${POOL:?set POOL, e.g. v11500}"
: "${RESULT_DIR:?}"; : "${TASKS:?}"; : "${QWEN:?}"
OPUS=${OPUS:-}
OUT=${OUT:-out/arb_${POOL}.jsonl}
WATCH=${WATCH:-$QWEN}
INTERVAL=${INTERVAL:-300}
WORKERS=${WORKERS:-3}
P=${P:-/mnt/d/research/OSWorld/.venv/bin/python}

pass_once(){
  ARGS=(-m ostg.sft.arb "$RESULT_DIR" --tasks "$TASKS" --qwen "$QWEN"
        --workers "$WORKERS" --out "$OUT")
  [ -n "$OPUS" ] && ARGS+=(--opus "$OPUS")
  "$P" "${ARGS[@]}"
}

echo "[$(date '+%F %T')] arb_stream: pool=$POOL watching writer of $WATCH"
while pgrep -f "trajaudit.*$(basename "$WATCH")" > /dev/null; do
  pass_once
  echo "[$(date '+%F %T')] pass done, $(wc -l < "$OUT" 2>/dev/null || echo 0) ruled; sleeping ${INTERVAL}s"
  sleep "$INTERVAL"
done
echo "[$(date '+%F %T')] sweep finished; final pass"
pass_once
echo "[$(date '+%F %T')] arb_stream done: $(wc -l < "$OUT" 2>/dev/null || echo 0) ruled"
echo "ARB_STREAM_DONE_${POOL}"
