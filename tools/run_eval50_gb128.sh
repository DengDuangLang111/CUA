#!/bin/bash
# run_eval50_gb128.sh -- B-gb128 arm (global batch 128, OpenWebRL regime)
# under keepthink serving, 3 VMs (user directive 2026-08-17: gb128 evals
# first with all VMs; rerun2 pauses and resumes later). Canonical run
# location: WSL osworld-verified-control/ (this CUA copy = version control).
# Gates: richstock eval DONE + gb128 final checkpoint exists on Tillicum.
# Then: pause rerun2, cancel the rich-official serve, bring up the gb128
# serve + tunnel (18016->8016), run the frozen eval-50 with num_envs 3.
set -u
CTL=/mnt/d/research/osworld-verified-control
LOG=$CTL/logs/eval50_gb128.log
exec >>$LOG 2>&1
cd /mnt/d/research/OSWorld; set -a; . ./.env; set +a
SSHT="ssh -n -S $HOME/.ssh/cm/qwen36-tillicum-login -o ControlMaster=no -o BatchMode=yes jy050706@tillicum-login02.hyak.uw.edu"
MODEL=q38e3B-gb128
PORT=18016
TAG=eval50-gb128keep-20260817
C=/mnt/d/research/OSWorld/evaluation_examples
META=$C/verified_eval50_nonproxy.json
R=/mnt/d/research/OSWorld/results_generated/qwen35-4b-sft/$TAG
mkdir -p $R
up(){ [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $OPENAI_API_KEY" http://127.0.0.1:$PORT/v1/models)" = "200" ]; }

stop_eval(){
  pkill -f "run_multienv_qwen.*$TAG" 2>/dev/null
  for i in $(seq 1 30); do pgrep -f "run_multienv_qwen.*$TAG" >/dev/null || break; sleep 2; done
  pkill -9 -f "run_multienv_qwen.*$TAG" 2>/dev/null
  echo "[$(date '+%F %T')] eval runner stopped"
}

# Gate 1: richstock must be fully done (its 2 VMs + the serve slot free up).
for i in $(seq 1 720); do
  grep -q "EVAL50_RICHSTOCK_DONE" $CTL/logs/eval50_richstock.log 2>/dev/null && break
  sleep 30
done
grep -q "EVAL50_RICHSTOCK_DONE" $CTL/logs/eval50_richstock.log 2>/dev/null || \
  { echo "[$(date '+%F %T')] FATAL: richstock never finished (6h gate)"; exit 1; }
# Gate 2: gb128 final checkpoint on Tillicum (training 235513, ~05:30).
for i in $(seq 1 240); do
  $SSHT 'ls -d /gpfs/scrubbed/jy050706/sft/out/q38e3B-gb128/v*/checkpoint-* >/dev/null 2>&1' && break
  sleep 60
done
$SSHT 'ls -d /gpfs/scrubbed/jy050706/sft/out/q38e3B-gb128/v*/checkpoint-* >/dev/null 2>&1' || \
  { echo "[$(date '+%F %T')] FATAL: gb128 checkpoint never appeared (4h gate)"; exit 1; }

# User directive: gb128 eval gets all 3 VMs -- pause rerun2 (driver first,
# then runner; results persist, unfinished tasks resume on a later relaunch).
N2=$(find /mnt/d/research/OSWorld/results_generated/qwen38-27b-local/v11-100-t1-rerun2-20260816 -name result.txt 2>/dev/null | wc -l)
echo "[$(date '+%F %T')] pausing rerun2 at $N2/100 (resume later)"
pkill -f "run100r2.sh" 2>/dev/null
pkill -f "run_multienv_qwen.*v11-100-t1-rerun2" 2>/dev/null
sleep 5; pkill -9 -f "run_multienv_qwen.*v11-100-t1-rerun2" 2>/dev/null

$SSHT "scancel -n eval4bro -u jy050706" 2>/dev/null
JID=$($SSHT "sbatch --parsable /gpfs/scrubbed/jy050706/qwen-serve/serve-chain-4b-gb128.sbatch" 2>/dev/null | tr -dc 0-9)
echo "[$(date '+%F %T')] gb128 serve job $JID"
JOB=eval4bg LPORT=$PORT RPORT=8016 setsid nohup $CTL/tunnel_qwen36_auto.sh > $HOME/tunnel_4bg.log 2>&1 < /dev/null &
for i in $(seq 1 120); do up && break; sleep 20; done
up || { echo "[$(date '+%F %T')] FATAL: gb128 endpoint never came up"; exit 1; }
echo "[$(date '+%F %T')] gb128 endpoint UP"

cat > $R/MODEL_BOUNDARY.json <<JSON
{"model":"Qwen3.5-4B SFT arm B-gb128 (job 235513): B corpus (v11-100+500, 312 trajs/5,659 samples), global batch 128 = 16xH200 x accum 8, 3ep, cosine warmup 0.1 -- OpenWebRL optimization regime",
 "served_model_name":"q38e3B-gb128","precision":"BF16 weights, fp8 kv-cache",
 "chat_template":"qwen35_4b_keepthink.jinja (same as richrich/leankeep/basekeep)",
 "preserve_thinking":true,"cell":"gb128/keepthink -- optimization-regime lever vs richrich(3ep,gb8)+B corpus",
 "sampling":{"temperature":1.0,"top_p":0.95,"top_k":20,"min_p":0.0,"presence_penalty":0.0,
             "repetition_penalty":1.0,"profile":"official general thinking; temp/top_p from client, rest from serve override"},
 "max_steps":50,"sleep_after_execution":3,"num_envs":3,
 "tasks":"verified_eval50_nonproxy.json (frozen stratified sample, seed 20260815)",
 "harness":"UNMODIFIED upstream behaviour; no OSTG_* env vars. Same serving as the keepthink column; weights are the only difference."}
JSON

for TRY in 1 2 3; do
  N=$(find $R -name result.txt 2>/dev/null | wc -l)
  T=$(python3 -c "import json;print(sum(len(v) for v in json.load(open('$META')).values()))")
  [ "$N" -ge "$T" ] && { echo "[$(date '+%F %T')] complete $N/$T"; break; }
  up || { echo "[$(date '+%F %T')] endpoint down at $N/$T, waiting"; for i in $(seq 1 240); do up && break; sleep 30; done; }
  up || { echo "[$(date '+%F %T')] FATAL: endpoint never came back"; exit 1; }
  echo "[$(date '+%F %T')] pass $TRY at $N/$T"
  OSWORLD_OPENAI_TIMEOUT=600 \
  .venv/bin/python scripts/python/run_multienv_qwen.py \
    --provider_name docker --path_to_vm /mnt/d/research/OSWorld/docker_vm_data/Ubuntu.qcow2 \
    --headless --observation_type screenshot --action_space pyautogui \
    --model $MODEL --base_url http://127.0.0.1:$PORT/v1 \
    --temperature 1.0 --top_p 0.95 --max_tokens 81920 --max_steps 50 \
    --sleep_after_execution 3 --enable_thinking --preserve_thinking --num_envs 3 --simple_path \
    --screen_width 1920 --screen_height 1080 \
    --test_config_base_dir $C --test_all_meta_path $META --result_dir $R
  stop_eval
done
echo "[$(date '+%F %T')] === eval50 gb128/keepthink RESULT: $(find $R -name result.txt -exec cat {} \; 2>/dev/null | sort | uniq -c | tr '\n' ' ')"
echo "EVAL50_GB128_DONE"
