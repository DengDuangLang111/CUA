#!/bin/bash
# one-shot status for the image-window pilot (B/C/D + E); consumed by the monitor
cd /mnt/d/research/osworld-verified-control
grep -a -e "\[pilot" -e FATAL -e "=== .* RESULT" -e "SERVE GONE" -e INCOMPLETE \
  logs/pilot_fold.log logs/pilot_fold2.log logs/eval50_t38i10.log logs/eval50_t38i20.log \
  logs/eval50_t38px480.log logs/eval50_t38med.log logs/pilot_fold3.log logs/eval50_t38i5.log 2>/dev/null | tail -50
for a in t38i10 t38i20 t38px480 t38med t38i5; do
  d=$(ls -dt /mnt/d/research/OSWorld/results_generated/qwen38-27b-local/eval50-$a-* 2>/dev/null | head -1)
  [ -n "$d" ] || continue
  n=$(find "$d" -name result.txt 2>/dev/null | wc -l)
  s=$(find "$d" -name result.txt -exec awk '{print $1; exit}' {} \; 2>/dev/null | awk '{t+=$1} END{printf "%.1f", t*2}')
  echo "[score] $a $n/50 running=${s:-0}%"
done
if ! pgrep -f "tools_pilot_(fold[23]?|resume)[.]sh" >/dev/null; then
  grep -aq "ALL-PILOT3-DONE" logs/pilot_fold3.log 2>/dev/null || echo "PILOT-LAUNCHER-GONE"
fi
