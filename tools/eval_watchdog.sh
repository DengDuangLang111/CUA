#!/bin/bash
# eval_watchdog.sh -- unstick eval runners that OSWorld leaves hanging.
#
# Failure mode (diagnosed 2026-08-17 on gb64o): a step's screenshot comes back
# None while the VM is mid-restart -> the task raises TypeError and exits
# WITHOUT writing result.txt -> OSWorld's cleanup tries to stop the recording
# against a container that is already gone -> ConnectionResetError -> and its
# retry loop has NO bound, so the env process spins forever. The runner never
# exits, so the driver's retry loop never advances and the whole eval chain
# stalls. Seen on the same two long multi_apps tasks in two different arms
# (5bc63fb9, 7f35355e): 397 and 224 accumulated steps against a 50-step cap.
#
# This watches every live eval run dir and kills a runner whose newest traj
# write is older than STALE_MIN. The driver's own loop then restarts it with
# fresh VMs -- no harness patch, so eval comparability is untouched.
#
# GRACE_MIN exists because the first version could not tell "hung" from "has
# not started yet": it tested `find -name traj.jsonl -newermt -15min` and an
# empty result also means the run has written NOTHING yet. Booting three VMs
# and waiting for the serve endpoint takes longer than that, so every eval was
# killed at startup, in a loop -- lorakeep and leanstock both died with 0/50 on
# 2026-08-17 before anyone noticed. The 15-minute threshold had been justified
# on the largest gap BETWEEN completed tasks (487s over 6168 gaps), a
# measurement that never covered startup.
#
# So: a runner is only ever killed once it has been alive longer than
# GRACE_MIN. Past that, no traj write in STALE_MIN still means hung.
#
#     STALE_MIN=15 GRACE_MIN=35 bash tools/eval_watchdog.sh
set -u
R=${R:-/mnt/d/research/OSWorld/results_generated/qwen35-4b-sft}
STALE_MIN=${STALE_MIN:-15}
GRACE_MIN=${GRACE_MIN:-35}   # never kill a runner younger than this
SLEEP=${SLEEP:-120}
LOG=${LOG:-/mnt/d/research/osworld-verified-control/logs/eval_watchdog.log}
echo "[$(date '+%F %T')] watchdog up: stale>${STALE_MIN}min, grace ${GRACE_MIN}min, poll ${SLEEP}s" >> $LOG
while true; do
  for tag in $(pgrep -af run_multienv_qwen | grep -o 'eval50-[a-z0-9]*-[0-9]*' | sort -u); do
    d=$R/$tag
    [ -d "$d" ] || continue
    # Youngest runner process for this tag, in seconds alive. A runner still
    # inside its startup window is never a hang, however quiet the dir is.
    age=$(pgrep -f "run_multienv_qwen.*$tag" | xargs -r ps -o etimes= -p 2>/dev/null \
          | tr -d ' ' | sort -n | tail -1)
    [ -n "${age:-}" ] || continue
    if [ "$age" -lt $((GRACE_MIN * 60)) ]; then continue; fi
    newest=$(find "$d" -name traj.jsonl -newermt "-${STALE_MIN} minutes" 2>/dev/null | head -1)
    if [ -z "$newest" ]; then
      n=$(find "$d" -name result.txt 2>/dev/null | wc -l)
      echo "[$(date '+%F %T')] STALE $tag ($n done, alive ${age}s, no traj write in ${STALE_MIN}min) -> killing runner" >> $LOG
      pkill -f "run_multienv_qwen.*$tag"
      sleep 20
      pkill -9 -f "run_multienv_qwen.*$tag" 2>/dev/null
    fi
  done
  sleep $SLEEP
done
