#!/bin/bash
# F-cell append (08-29 user order): teacher img5 fold1 -- lower-boundary probe.
# Runs after pilot2 (t38med). Final cleanup scancels ALL eval38h20 jobs
# (running + the self-chain's pending afterany successors) -- by then the
# pre-pilot serve 266158 is past its wall, so nothing we kill predates us.
set -u
cd /mnt/d/research/osworld-verified-control
export OSTG_TYPE_NO_SPLIT=1
exec >>logs/pilot_fold3.log 2>&1
echo "[pilot3] launcher up $(date)"
while pgrep -f "tools_pilot_fold2[.]sh" >/dev/null || pgrep -f "taskgen[.]control" >/dev/null || pgrep -f "run_multienv_qwen" >/dev/null; do sleep 60; done
echo "[pilot3] pilot2 finished, starting t38i5 $(date)"
./run_eval50_stock.sh t38i5
echo "[pilot3] t38i5 done rc=$? $(date)"
SSHT="ssh -n -S $HOME/.ssh/cm/qwen36-tillicum-login -o ControlMaster=no -o BatchMode=yes jy050706@tillicum-login02.hyak.uw.edu"
$SSHT "scancel -n eval38h20 -u jy050706" && echo "[pilot3] scancelled all eval38h20 (incl pending chain successors)"
echo "[pilot3] ALL-PILOT3-DONE $(date)"
