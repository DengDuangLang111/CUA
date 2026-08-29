#!/bin/bash
# I-cell: teacher i20 slide + medium. Parks behind H (fold5) AND the GIMP
# recheck (its script pid exists from launch, so no start-race on the VMs).
set -u
cd /mnt/d/research/osworld-verified-control
export OSTG_TYPE_NO_SPLIT=1
exec >>logs/pilot_fold6.log 2>&1
echo "[pilot6] launcher up $(date)"
while pgrep -f "tools_pilot_fold5[.]sh" >/dev/null || pgrep -f "gimp_recheck2[.]sh" >/dev/null \
   || pgrep -f "run_multienv_qwen" >/dev/null || pgrep -f "taskgen[.]control" >/dev/null; do sleep 60; done
echo "[pilot6] H + recheck finished, starting t38i20med $(date)"
./run_eval50_stock.sh t38i20med
echo "[pilot6] t38i20med done rc=$? $(date)"
SSHT="ssh -n -S $HOME/.ssh/cm/qwen36-tillicum-login -o ControlMaster=no -o BatchMode=yes jy050706@tillicum-login02.hyak.uw.edu"
$SSHT "scancel -n eval38h20 -u jy050706" && echo "[pilot6] scancelled all eval38h20"
echo "[pilot6] ALL-PILOT6-DONE $(date)"
