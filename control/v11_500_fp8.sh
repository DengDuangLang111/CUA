#!/bin/bash
# Switch the teacher serve from BF16 to FP8 and resume the v11-500 rollout on 3 VMs.
#
# FP8 is 1.39-1.51x faster on the A/B (logs/fp8_ab.log, 1/8/20 images per request),
# same weights family, official Qwen quantization, identical served-model-name --
# so --model and the result dir are unchanged and the campaign simply continues.
# The precision change is recorded in PRECISION_BOUNDARY.json inside the result
# dir: everything before it was BF16 (121 tasks, 32 passed).
#
# Supervised on purpose: the serve self-chains at its 12 h wall onto a new node,
# so the runner must survive the endpoint going away and coming back somewhere
# else. It relaunches until every task in the manifest has a result.txt.
set -u
CTL=/mnt/d/research/osworld-verified-control
LOG=$CTL/logs/v11_500_fp8.log
exec >>$LOG 2>&1
B=/gpfs/scrubbed/jy050706
SSHT="ssh -S $HOME/.ssh/cm/qwen36-tillicum-login -o ControlMaster=no -o BatchMode=yes jy050706@tillicum-login02.hyak.uw.edu"
RES=/mnt/d/research/OSWorld/results_generated/qwen36-27b-bf16-local/v11-500-ms100-think-nopreserve-20260813
CORPUS=/mnt/d/research/os-simple-taskgen-v8/out/runs/v11-500-final
cd /mnt/d/research/OSWorld || exit 1
set -a; . ./.env; set +a

# Verbatim from valpanel_driver.sh, which is what produced the first 121.
TEACHER_ARGS="--provider_name docker --path_to_vm /mnt/d/research/OSWorld/docker_vm_data/Ubuntu.qcow2 --headless --observation_type screenshot --action_space pyautogui --model qwen36-27b-bf16-local --base_url http://127.0.0.1:18001/v1 --temperature 0.6 --top_p 0.95 --max_tokens 81920 --max_steps 100 --sleep_after_execution 1 --enable_thinking --num_envs 3 --simple_path --screen_width 1920 --screen_height 1080 --test_config_base_dir $CORPUS --test_all_meta_path $CORPUS/manifest.json --result_dir $RES"

up(){ [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $OPENAI_API_KEY" http://127.0.0.1:18001/v1/models)" = "200" ]; }
ndone(){ find $RES -name result.txt 2>/dev/null | wc -l; }
ntotal(){ python3 -c "import json;print(sum(len(v) for v in json.load(open('$CORPUS/manifest.json')).values()))"; }
stop_runner(){ pkill -f run_multienv_qwen 2>/dev/null
  for i in $(seq 1 30); do pgrep -f run_multienv_qwen >/dev/null || break; sleep 2; done
  pkill -9 -f run_multienv_qwen 2>/dev/null
  # a bare pkill leaks the containers; that is what starved the box to 4 GB once
  docker rm -f $(docker ps -aq) >/dev/null 2>&1
  for i in $(seq 1 60); do [ -z "$(docker ps -q)" ] && break; sleep 5; done; }

TOT=$(ntotal)
echo "[$(date '+%F %T')] === BF16 -> FP8 switch, resuming v11-500 at $(ndone)/$TOT"

stop_runner
# One serve at a time. The BF16 teacher (job name 'eval') has ~1 h of wall left
# anyway; taking it down now is what frees :18001 for the FP8 job.
echo "[$(date '+%F %T')] cancelling BF16 teacher serve(s)"
# squeue's own --name filter is an EXACT match, so this cannot reach evalfp8 or
# any sft-* training job. Deliberately not an awk/grep pattern: a '$' anchor has
# to survive Mac shell -> ssh -> wsl -> ssh -> remote shell, and it does not.
$SSHT "squeue -u jy050706 -h -n eval -o %i | xargs -r scancel" 2>/dev/null
pkill -f "tunnel_qwen36_auto" 2>/dev/null
sleep 10

JID=$($SSHT "sbatch --parsable $B/qwen-serve/serve-chain-36-fp8.sbatch" 2>/dev/null | tr -dc 0-9)
echo "[$(date '+%F %T')] FP8 serve job $JID (self-chaining, job name evalfp8)"
JOB=evalfp8 LPORT=18001 RPORT=8000 setsid nohup $CTL/tunnel_qwen36_auto.sh \
  > $CTL/logs/tunnel_v11_500_fp8.log 2>&1 < /dev/null &

for i in $(seq 1 120); do
  up && break
  if $SSHT "grep -q 'Address already in use' $B/qwen-serve/serve36fp8_$JID.out 2>/dev/null"; then
    echo "[$(date '+%F %T')] PORT COLLISION on the serve node — aborting"; exit 1; fi
  sleep 20
done
up || { echo "[$(date '+%F %T')] FP8 endpoint never came up"; exit 1; }
echo "[$(date '+%F %T')] FP8 endpoint UP on :18001"

# Supervise. Each pass runs until the runner exits; the runner itself skips any
# task that already has a result.txt, so a restart costs nothing but a VM boot.
while :; do
  N=$(ndone)
  [ "$N" -ge "$TOT" ] && { echo "[$(date '+%F %T')] V11_500_COMPLETE $N/$TOT"; break; }
  if ! up; then
    echo "[$(date '+%F %T')] endpoint down at $N/$TOT — waiting for the serve chain to land"
    stop_runner
    for i in $(seq 1 240); do up && break; sleep 30; done
    up || { echo "[$(date '+%F %T')] serve gone for 2 h, giving up at $N/$TOT"; break; }
    echo "[$(date '+%F %T')] endpoint back, resuming"
  fi
  echo "[$(date '+%F %T')] runner pass starting at $N/$TOT"
  OSTG_WAIT_BREAK=10 OSTG_LOOP_LOG=12 \
    .venv/bin/python scripts/python/run_multienv_qwen.py $TEACHER_ARGS \
    >> $CTL/logs/rollout444_fp8.log 2>&1
  echo "[$(date '+%F %T')] runner pass ended at $(ndone)/$TOT"
  stop_runner
  sleep 20
done
echo "[$(date '+%F %T')] V11_500_FP8_DRIVER_DONE $(ndone)/$TOT"
