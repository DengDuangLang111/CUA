#!/bin/bash
# Pause v11-500 -> tier-3 the two finished 3-epoch arms -> resume v11-500.
#
# NOT final_evals.sh: that one blocks until no sft-* job is queued, and ep5pt /
# ep5np / sft-fast are still running, so it would wait ~10 h. This is scoped to
# the two arms that are actually done.
#
# Both are checkpoint-483 = 3 epochs x 161 steps, fully annealed -- the products,
# not mid-schedule snapshots.
set -u
CTL=/mnt/d/research/osworld-verified-control
LOG=$CTL/logs/eval_more3_pair.log
exec >>$LOG 2>&1
B=/gpfs/scrubbed/jy050706
SSHT="ssh -S $HOME/.ssh/cm/qwen36-tillicum-login -o ControlMaster=no -o BatchMode=yes jy050706@tillicum-login02.hyak.uw.edu"
RES=/mnt/d/research/OSWorld/results_generated

echo "[$(date '+%F %T')] === pausing v11-500 to free the 3 VMs"
# Kill the SUPERVISOR first. Killing only the runner makes the supervisor
# relaunch it, and then eval and rollout fight over the VMs.
pkill -f v11_500_fp8.sh 2>/dev/null
sleep 3
pkill -f run_multienv_qwen 2>/dev/null
for i in $(seq 1 30); do pgrep -f run_multienv_qwen >/dev/null || break; sleep 2; done
pkill -9 -f run_multienv_qwen 2>/dev/null
# A bare pkill leaks the containers; that is what starved the box to 4 GB once.
docker rm -f $(docker ps -aq) >/dev/null 2>&1
for i in $(seq 1 60); do [ -z "$(docker ps -q)" ] && break; sleep 5; done
D=$RES/qwen36-27b-bf16-local/v11-500-ms100-think-nopreserve-20260813
echo "[$(date '+%F %T')] v11-500 paused at $(find $D -name result.txt | wc -l)/444; VMs free ($(docker ps -q | wc -l) containers)"

for ARM in more3 more3np; do
  CK=$($SSHT "ls -d $B/sft/out/$ARM/v*/checkpoint-483 2>/dev/null | head -1")
  if [ -z "$CK" ]; then echo "[$(date '+%F %T')] $ARM: no checkpoint-483 -- SKIPPED"; continue; fi
  TAG="q35-$ARM-final"
  echo "[$(date '+%F %T')] === $TAG  ($CK)"
  $SSHT "sed -e 's|^CK=.*|CK=$CK|' -e 's|--served-model-name [a-z0-9.-]*|--served-model-name $TAG|' \
         $B/qwen-serve/serve-q-e1.sbatch > $B/qwen-serve/serve-q-$TAG.sbatch" 2>/dev/null
  $CTL/run_arm.sh "$TAG" "$B/qwen-serve/serve-q-$TAG.sbatch" "$TAG" 18010
  R=$RES/$TAG/valpanel-a1
  echo "[$(date '+%F %T')] === $TAG RESULT: $(find $R -name result.txt -exec cat {} \; 2>/dev/null | sort | uniq -c | tr '\n' ' ')"
done

echo "[$(date '+%F %T')] === both arms evaluated; resuming v11-500"
pkill -f run_multienv_qwen 2>/dev/null
docker rm -f $(docker ps -aq) >/dev/null 2>&1
for i in $(seq 1 60); do [ -z "$(docker ps -q)" ] && break; sleep 5; done
setsid nohup $CTL/v11_500_fp8.sh > /dev/null 2>&1 < /dev/null &
sleep 10
echo "[$(date '+%F %T')] v11-500 supervisor restarted (pid $(pgrep -f v11_500_fp8.sh | head -1))"
echo "EVAL_MORE3_PAIR_DONE"
