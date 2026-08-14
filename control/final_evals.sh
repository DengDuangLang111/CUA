#!/bin/bash
# Tier-3 eval of the FINAL checkpoint of each training run -- one arm at a time.
#
# Replaces ckpt_pipeline.sh, which evaluated every epoch-boundary checkpoint. A
# 5-epoch run is evaluated at 5 epochs and a 3-epoch run at 3 epochs, because an
# epoch-k snapshot of a longer run is not a k-epoch model: the cosine schedule
# spans the run's TOTAL steps, so ep5's epoch-3 snapshot still sits at 38% of
# peak LR while e3's is annealed to 0. Comparing snapshots to annealed products
# measures the schedule, not the epochs.
#
# NOT started automatically. It takes all 3 VMs, and those belong to the v11-500
# rollout until that finishes. Launch by hand:
#   setsid nohup /mnt/d/research/osworld-verified-control/final_evals.sh &
set -u
CTL=/mnt/d/research/osworld-verified-control
LOG=$CTL/logs/final_evals.log
exec >>$LOG 2>&1
B=/gpfs/scrubbed/jy050706
SSHT="ssh -S $HOME/.ssh/cm/qwen36-tillicum-login -o ControlMaster=no -o BatchMode=yes jy050706@tillicum-login02.hyak.uw.edu"

# arm : final step (161 steps/epoch on abs-pilot3's 1288 samples at eff. batch 8)
ARMS="ep5pt:805 ep5np:805 more3:483 more3np:483"

echo "[$(date '+%F %T')] final-checkpoint evals: $ARMS"
# Wait for every sft-* training to leave the queue.
for i in $(seq 1 900); do
  N=$($SSHT "squeue -u jy050706 -h -o %j | grep -c '^sft-'" 2>/dev/null)
  [ "${N:-1}" = "0" ] && break
  [ $((i % 20)) = 1 ] && echo "[$(date '+%F %T')] $N training job(s) still running"
  sleep 60
done
echo "[$(date '+%F %T')] trainings done"

for SPEC in $ARMS; do
  ARM=${SPEC%%:*}; STEP=${SPEC##*:}
  CK=$($SSHT "ls -d $B/sft/out/$ARM/v*/checkpoint-$STEP 2>/dev/null | head -1")
  if [ -z "$CK" ]; then
    # A run that stopped early still deserves a number; take its last checkpoint
    # and SAY SO, rather than silently skipping the arm.
    CK=$($SSHT "ls -dv $B/sft/out/$ARM/v*/checkpoint-* 2>/dev/null | tail -1")
    [ -z "$CK" ] && { echo "[$(date '+%F %T')] $ARM: no checkpoint at all — SKIPPED"; continue; }
    echo "[$(date '+%F %T')] $ARM: checkpoint-$STEP missing, falling back to $(basename $CK) — NOT the full schedule"
  fi
  TAG="q35-$ARM-final"
  echo "[$(date '+%F %T')] === $TAG  ($CK)"
  $SSHT "sed -e 's|^CK=.*|CK=$CK|' -e 's|--served-model-name [a-z0-9.-]*|--served-model-name $TAG|' \
         $B/qwen-serve/serve-q-e1.sbatch > $B/qwen-serve/serve-q-$TAG.sbatch" 2>/dev/null
  $CTL/run_arm.sh "$TAG" "$B/qwen-serve/serve-q-$TAG.sbatch" "$TAG" 18010
  R=/mnt/d/research/OSWorld/results_generated/$TAG/valpanel-a1
  echo "[$(date '+%F %T')] === $TAG RESULT: $(find $R -name result.txt -exec cat {} \; 2>/dev/null | sort | uniq -c | tr '\n' ' ')"
done
echo "[$(date '+%F %T')] FINAL_EVALS_DONE"
