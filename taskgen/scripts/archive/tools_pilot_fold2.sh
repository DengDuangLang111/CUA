#!/bin/bash
# tools_pilot_fold2.sh -- E-cell append (08-29 user order): teacher at the ANCHOR
# window (20fold10 defaults) with reasoning effort medium (OSTG_REASONING_EFFORT
# via chat_template_kwargs; anchor + entire teacher lineage ran template-default
# xhigh). vs archived t38 69.8% isolates thinking effort. Chained as a separate
# launcher because editing a RUNNING bash script corrupts it.
set -u
cd /mnt/d/research/osworld-verified-control
export OSTG_TYPE_NO_SPLIT=1
exec >>logs/pilot_fold2.log 2>&1
echo "[pilot2] launcher up $(date)"
while pgrep -f "tools_pilot_fold[.]sh" >/dev/null || pgrep -f "taskgen[.]control" >/dev/null || pgrep -f "run_multienv_qwen" >/dev/null; do sleep 60; done
echo "[pilot2] pilot1 finished, starting t38med $(date)"
./run_eval50_stock.sh t38med
echo "[pilot2] t38med done rc=$? $(date)"
SSHT="ssh -n -S $HOME/.ssh/cm/qwen36-tillicum-login -o ControlMaster=no -o BatchMode=yes jy050706@tillicum-login02.hyak.uw.edu"
NOW=$($SSHT "squeue -u jy050706 -h -n eval38h20 -o %i" 2>/dev/null | tr -dc 0-9)
if [ -n "$NOW" ] && [ "$NOW" != "266158" ]; then
  $SSHT "scancel $NOW" && echo "[pilot2] scancelled our serve $NOW"
elif [ -n "$NOW" ]; then
  echo "[pilot2] serve $NOW is the pre-pilot one -- left running"
fi
echo "[pilot2] ALL-PILOT2-DONE $(date)"
