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

SSHT="ssh -n -S $HOME/.ssh/cm/qwen36-tillicum-login -o ControlMaster=no -o BatchMode=yes jy050706@tillicum-login02.hyak.uw.edu"
ready_train(){  # $1 slurm job name, $2 out-dir glob: job gone AND endpoint epoch >= 2.99
  [ -z "$($SSHT "squeue -u jy050706 -h -n $1 -o %i" 2>/dev/null | tr -dc 0-9)" ] || return 1
  local ep
  ep=$($SSHT "/gpfs/scrubbed/jy050706/qwen-serve/pick_ckpt.sh \"$2\" endpoint" 2>&1 \
      | grep -o "epoch=[0-9.]*" | cut -d= -f2 | tail -1)
  awk -v e="${ep:-0}" "BEGIN{exit !(e>=2.99)}"
}
train_gate(){  # $1 arm, $2 job, $3 dir glob; up to 12h; returns 1 on timeout (caller skips)
  local i
  for i in $(seq 1 720); do ready_train "$2" "$3" && return 0; sleep 60; done
  return 1
}

log "chain start (resume-safe)"
PREV=bsstock
for arm in kE kD15 t38 vlbase img3 img3h3 kEh3 nocap vlsft gb128 kG vl20 kEh1 baseh1 nocapt0 img1 vlnocapnp nocapnp2 nocap50b base50b np1e6; do
  if alive "$arm"; then
    log "adopt $arm: already in flight"
  elif complete "$arm"; then
    log "skip $arm: already complete"
  else
    log "waiting for $PREV before starting $arm"
    wait_for "$PREV" || { log "FATAL: $PREV never finished in 24h"; exit 1; }
    GJOB=""; GDIR=""
    case "$arm" in
      nocap) GJOB=sft-q38Bhqs2t-lr3e6-nocap; GDIR="/gpfs/scrubbed/jy050706/sft/out/q38Bhqs2t-lr3e6-nocap/v*" ;;
      vlsft) GJOB=sft-q3vl-r5vl-lr3e6;  GDIR="/gpfs/scrubbed/jy050706/sft/out/q3vl-r5vl-lr3e6/v*" ;;
      img3)  GJOB=sft-q38Bhqs2t-img3;   GDIR="/gpfs/scrubbed/jy050706/sft/out/q38Bhqs2t-img3-lr3e6/v*" ;;
      gb128) GJOB=sft-vl3pic-gb128-lr1e5; GDIR="/gpfs/scrubbed/jy050706/sft/out/vl3pic-gb128-lr1e5/v*" ;;
      vl20)  GJOB=sft-vl20pic-lr1e5;       GDIR="/gpfs/scrubbed/jy050706/sft/out/vl20pic-lr1e5/v*" ;;
      nocapnp)   GJOB=eval4b-np;               GDIR="/gpfs/scrubbed/jy050706/sft/out/q38Bhqs2t-nocapnp/v*" ;;  # 16-rank rerun 249689; opaque queue name per user rule. pick_ckpt spans v0+v1 by epoch, so v0 ckpt-204 (2.00) cannot satisfy the >=2.99 gate
      img1)      GJOB=sft-q38Bhqs2t-img1;      GDIR="/gpfs/scrubbed/jy050706/sft/out/q38Bhqs2t-img1-lr3e6/v*" ;;
      vlnocapnp) GJOB=sft-vlnocapnp-lr3e6;      GDIR="/gpfs/scrubbed/jy050706/sft/out/vlnocapnp-lr3e6/v*" ;;
      np1e6)     GJOB=eval4b-n1r;              GDIR="/gpfs/scrubbed/jy050706/sft/out/q38Bhqs2t-np1e6/v*" ;;  # opaque name per user rule 08-19; GJOB tracks the RESUME job 250344 after the first attempt died at epoch 2.36 on an NVLink fault. pick_ckpt spans v0+v1 by epoch, so the >=2.99 gate can only be satisfied by the resume writing checkpoint-303 into v1
    esac
    if [ -n "$GJOB" ]; then
      if ! train_gate "$arm" "$GJOB" "$GDIR"; then
        log "SKIP $arm: training incomplete after 12h gate ($GJOB still queued or endpoint epoch < 2.99); run manually later"
        PREV=$arm; continue
      fi
      log "$arm weights gate passed (training done, endpoint epoch >= 2.99)"
    fi
    log "starting $arm (OSTG_TYPE_NO_SPLIT=1)"
    OSTG_TYPE_NO_SPLIT=1 setsid nohup ./run_eval50_stock.sh "$arm" > /dev/null 2>&1 < /dev/null &
    sleep 10
  fi
  PREV=$arm
done
log "chain done (tail arm np1e6, the LR left-flank sample; scancel eval4bnp1 after)"
