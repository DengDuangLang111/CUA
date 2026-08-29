#!/bin/bash
# G-cell (08-29 user order): teacher/ev10i@480, completes the count x resolution
# 2x2. Runs after fold3 (t38i5). fold3's cleanup scancels the whole serve chain,
# so this arm's driver will submit a fresh serve (~10 min load) -- accepted.
set -u
cd /mnt/d/research/osworld-verified-control
export OSTG_TYPE_NO_SPLIT=1
exec >>logs/pilot_fold4.log 2>&1
echo "[pilot4] launcher up $(date)"
while pgrep -f "tools_pilot_fold3[.]sh" >/dev/null || pgrep -f "taskgen[.]control" >/dev/null || pgrep -f "run_multienv_qwen" >/dev/null; do sleep 60; done
echo "[pilot4] fold3 finished, starting t38i10px $(date)"
./run_eval50_stock.sh t38i10px
echo "[pilot4] t38i10px done rc=$? $(date)"
SSHT="ssh -n -S $HOME/.ssh/cm/qwen36-tillicum-login -o ControlMaster=no -o BatchMode=yes jy050706@tillicum-login02.hyak.uw.edu"
$SSHT "scancel -n eval38h20 -u jy050706" && echo "[pilot4] scancelled all eval38h20"
echo "[pilot4] ALL-PILOT4-DONE $(date)"
