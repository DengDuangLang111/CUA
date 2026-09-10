#!/bin/bash
# H-cell: teacher i10 fold1 + reasoning_effort medium. Gates on the GIMP
# recheck lanes (taskgen.control) releasing the VMs, then runs; fresh serve
# auto-submitted by the driver (fold4 scancelled the previous chain).
set -u
cd /mnt/d/research/osworld-verified-control
export OSTG_TYPE_NO_SPLIT=1
exec >>logs/pilot_fold5.log 2>&1
echo "[pilot5] launcher up $(date)"
while pgrep -f "taskgen[.]control" >/dev/null || pgrep -f "run_multienv_qwen" >/dev/null || pgrep -f "gimp_recheck[.]sh" >/dev/null; do sleep 60; done
echo "[pilot5] VMs free, starting t38i10med $(date)"
./run_eval50_stock.sh t38i10med
echo "[pilot5] t38i10med done rc=$? $(date)"
SSHT="ssh -n -S $HOME/.ssh/cm/qwen36-tillicum-login -o ControlMaster=no -o BatchMode=yes jy050706@tillicum-login02.hyak.uw.edu"
$SSHT "scancel -n eval38h20 -u jy050706" && echo "[pilot5] scancelled all eval38h20"
echo "[pilot5] ALL-PILOT5-DONE $(date)"
