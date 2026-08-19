#!/bin/bash
# Serial Tillicum arm chain, RESUME-SAFE (2026-08-18 lesson: a restart replayed
# the list from the top and launched a duplicate kE driver + serve while kD15
# was mid-run; killed within a minute, one 27-second serve wasted). Every arm
# is now checked before anything is launched:
#   in flight  -> adopt it as PREV and move on
#   complete   -> skip
#   otherwise  -> wait for PREV (driver AND runner both gone), then launch
# so the script can be killed and relaunched at any time without duplicating
# work. All arms run with OSTG_TYPE_NO_SPLIT=1 (collapsed multi-line type).
set -u
CTL=/mnt/d/research/osworld-verified-control
RES=/mnt/d/research/OSWorld/results_generated
cd $CTL
log(){ echo "[$(date '+%F %T')] $*" >> $CTL/logs/tillicum_chain.log; }

alive(){   # driver or runner for arm $1 still running
  pgrep -f "run_eval50_stock.sh $1\$" >/dev/null || \
  pgrep -f "run_multienv_qwen.*eval50-$1-" >/dev/null
}
complete(){  # newest result dir for arm $1 has all 50 scored
  local d
  d=$(ls -dt $RES/*/eval50-$1-* 2>/dev/null | head -1)
  [ -n "$d" ] && [ "$(find "$d" -name result.txt 2>/dev/null | wc -l)" -ge 50 ]
}
wait_for(){
  local a=$1 i
  for i in $(seq 1 1440); do alive "$a" || return 0; sleep 60; done
  return 1
}

log "chain start (resume-safe)"
PREV=bsstock
for arm in kE kD15 t38 kG kF; do
  if alive "$arm"; then
    log "adopt $arm: already in flight"
  elif complete "$arm"; then
    log "skip $arm: already complete"
  else
    log "waiting for $PREV before starting $arm"
    wait_for "$PREV" || { log "FATAL: $PREV never finished in 24h"; exit 1; }
    log "starting $arm (OSTG_TYPE_NO_SPLIT=1)"
    OSTG_TYPE_NO_SPLIT=1 setsid nohup ./run_eval50_stock.sh "$arm" > /dev/null 2>&1 < /dev/null &
    sleep 10
  fi
  PREV=$arm
done
log "chain done (kF was the last; t38 ran right after kD15 by user order)"
