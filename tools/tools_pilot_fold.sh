#!/bin/bash
# tools_pilot_fold.sh -- image-window pilot (2026-08-28 user order, rollout gate).
# Teacher on the frozen eval-50, three cells vs archived anchor A =
# eval50-t38-20260819 (h100/img20 fold10/ms50/t1.0/no-split, 69.8%):
#   B t38i10   --image_max 10 --fold_size 1     C-vs-B: image count
#   C t38i20   --image_max 20 --fold_size 1     A-vs-C: sawtooth vs slide
#   D t38px480 = C + OSTG_MAX_PIXELS=491520     C-vs-D: resolution 2040->480 tok
# Gates on the wave-2 tails chain (3-VM red line), then runs arms sequentially;
# serve submit/resubmit, tunnel, identity assert, resume all live in the driver.
set -u
cd /mnt/d/research/osworld-verified-control
export OSTG_TYPE_NO_SPLIT=1   # anchor A ran no-split (k-era protocol)
exec >>logs/pilot_fold.log 2>&1
echo "[pilot] launcher up $(date)"
while pgrep -f "tails_final[.]sh" >/dev/null || pgrep -f "taskgen[.]control" >/dev/null; do sleep 60; done
echo "[pilot] tails chain released the VMs $(date)"
SSHT="ssh -n -S $HOME/.ssh/cm/qwen36-tillicum-login -o ControlMaster=no -o BatchMode=yes jy050706@tillicum-login02.hyak.uw.edu"
PRE=$($SSHT "squeue -u jy050706 -h -n eval38h20 -o %i" 2>/dev/null | tr -dc 0-9)
echo "[pilot] pre-existing eval38h20 serve: ${PRE:-none}"
for ARM in t38i10 t38i20 t38px480; do
  echo "[pilot] === $ARM start $(date)"
  ./run_eval50_stock.sh "$ARM"
  echo "[pilot] === $ARM done rc=$? $(date)"
done
# release the serve -- but never kill a job this pilot did not (re)submit
NOW=$($SSHT "squeue -u jy050706 -h -n eval38h20 -o %i" 2>/dev/null | tr -dc 0-9)
if [ -n "$NOW" ] && [ "$NOW" != "${PRE:-x}" ]; then
  $SSHT "scancel $NOW" && echo "[pilot] scancelled our serve $NOW"
elif [ -n "$NOW" ]; then
  echo "[pilot] serve $NOW predates the pilot -- left running (not ours to kill)"
fi
echo "[pilot] ALL-PILOT-DONE $(date)"
