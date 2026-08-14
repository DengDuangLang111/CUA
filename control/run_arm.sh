#!/bin/bash
# run_arm.sh <name> <sbatch> <model-name> <port> [wait-marker-file] [wait-marker]
# One arm: wait (optional) -> serve -> 9 tasks -> tear down. Explicit paths only.
set -u
NAME=$1; SB=$2; MODEL=$3; PORT=$4; WFILE=${5:-}; WMARK=${6:-}
CTL=/mnt/d/research/osworld-verified-control
LOG=$CTL/logs/arm_$NAME.log
exec >>$LOG 2>&1
cd /mnt/d/research/OSWorld
set -a; . ./.env; set +a
SSHT="ssh -S $HOME/.ssh/cm/qwen36-tillicum-login -o ControlMaster=no -o BatchMode=yes jy050706@tillicum-login02.hyak.uw.edu"
RES=/mnt/d/research/OSWorld/results_generated/$NAME
up(){ [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $OPENAI_API_KEY" http://127.0.0.1:$1/v1/models)" = "200" ]; }
stop_runner(){ pkill -f run_multienv_qwen 2>/dev/null
  for i in $(seq 1 30); do pgrep -f run_multienv_qwen >/dev/null || break; sleep 2; done
  pkill -9 -f run_multienv_qwen 2>/dev/null
  docker rm -f $(docker ps -aq) >/dev/null 2>&1
  for i in $(seq 1 30); do [ -z "$(docker ps -q)" ] && break; sleep 5; done; }
if [ -n "$WFILE" ]; then
  echo "[$(date '+%F %T')] $NAME waiting for '$WMARK' in $WFILE"
  for i in $(seq 1 720); do grep -q "$WMARK" "$WFILE" 2>/dev/null && break; sleep 60; done
  grep -q "$WMARK" "$WFILE" 2>/dev/null || { echo "[$(date '+%F %T')] $NAME: wait timed out"; exit 1; }
fi
echo "[$(date '+%F %T')] $NAME: only one serve at a time — cancelling any stray eval serve"
$SSHT "squeue -u jy050706 -h -t RUNNING -o '%i %j' | awk '/eval35/{print \$1}' | xargs -r scancel" 2>/dev/null
sleep 5
JID=$($SSHT "sbatch --parsable $SB" 2>/dev/null | tr -dc 0-9)
echo "[$(date '+%F %T')] $NAME: serve job $JID"
JOB=$($SSHT "squeue -j $JID -h -o %j" 2>/dev/null)
JOB=$JOB LPORT=$PORT RPORT=8000 setsid nohup $CTL/tunnel_qwen36_auto.sh > $CTL/logs/tunnel_$NAME.log 2>&1 < /dev/null &
for i in $(seq 1 120); do
  up $PORT && break
  if $SSHT "grep -q 'Address already in use' /gpfs/scrubbed/jy050706/qwen-serve/*_$JID.out 2>/dev/null"; then
    echo "[$(date '+%F %T')] $NAME: PORT COLLISION on the serve node — aborting"; exit 1; fi
  sleep 20
done
up $PORT || { echo "[$(date '+%F %T')] $NAME: endpoint never came up"; exit 1; }
stop_runner
for TRY in 1 2 3; do
  N=$(find $RES/valpanel-a1 -name result.txt 2>/dev/null | wc -l); [ "$N" -ge 9 ] && break
  up $PORT || break
  echo "[$(date '+%F %T')] $NAME: rollout try $TRY (have $N/9)"
  env ${DIALECT:+OSTG_PARAM_DIALECT=inline} OSTG_WAIT_BREAK=10 OSTG_LOOP_LOG=12 \
  .venv/bin/python scripts/python/run_multienv_qwen.py \
    --provider_name docker --path_to_vm /mnt/d/research/OSWorld/docker_vm_data/Ubuntu.qcow2 \
    --headless --observation_type screenshot --action_space pyautogui \
    --model $MODEL --base_url http://127.0.0.1:$PORT/v1 \
    --temperature 0.6 --top_p 0.95 --max_tokens 81920 --max_steps 50 \
    --sleep_after_execution 1 --enable_thinking --num_envs 3 --simple_path \
    --screen_width 1920 --screen_height 1080 \
    --test_config_base_dir /mnt/d/research/OSWorld/eval_valpanel_tasks \
    --test_all_meta_path /mnt/d/research/OSWorld/eval_valpanel_tasks/manifest.json \
    --result_dir $RES/valpanel-a1
  stop_runner
done
echo "[$(date '+%F %T')] ARM_${NAME}_DONE: $(find $RES/valpanel-a1 -name result.txt -exec cat {} \; 2>/dev/null | sort | uniq -c | tr '\n' ' ')"
$SSHT "scancel $JID" 2>/dev/null
