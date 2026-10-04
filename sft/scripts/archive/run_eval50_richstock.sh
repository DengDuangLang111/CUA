#!/bin/bash
# run_eval50_richstock.sh -- rich arm under OSWorld-Verified DEFAULT serving:
# official chat template (history <think> stripped at render), current-step
# thinking on, client upstream-identical (sends history think; template
# discards). Same weights as eval50-richrich, so the pair isolates the
# eval-time effect of history-think visibility. Canonical run location:
# WSL /mnt/d/research/osworld-verified-control/ (this CUA copy = version
# control). Autonomous handover: waits for leankeep's DONE marker, cancels
# the lean serve, brings up the official-template serve + tunnel, runs 2 VMs.
set -u
CTL=/mnt/d/research/osworld-verified-control
LOG=$CTL/logs/eval50_richstock.log
exec >>$LOG 2>&1
cd /mnt/d/research/OSWorld; set -a; . ./.env; set +a
SSHT="ssh -n -S $HOME/.ssh/cm/qwen36-tillicum-login -o ControlMaster=no -o BatchMode=yes jy050706@tillicum-login02.hyak.uw.edu"
MODEL=q38e3-rich450-stock
PORT=18015
TAG=eval50-richstock-20260816
C=/mnt/d/research/OSWorld/evaluation_examples
META=$C/verified_eval50_nonproxy.json
R=/mnt/d/research/OSWorld/results_generated/qwen35-4b-sft/$TAG
mkdir -p $R
up(){ [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $OPENAI_API_KEY" http://127.0.0.1:$PORT/v1/models)" = "200" ]; }

stop_eval(){
  pkill -f "run_multienv_qwen.*$TAG" 2>/dev/null
  for i in $(seq 1 30); do pgrep -f "run_multienv_qwen.*$TAG" >/dev/null || break; sleep 2; done
  pkill -9 -f "run_multienv_qwen.*$TAG" 2>/dev/null
  echo "[$(date '+%F %T')] eval runner stopped (docker wipe skipped: rollout shares the daemon)"
}

# Gate: leankeep must be fully done before we take its 2 VMs.
for i in $(seq 1 720); do
  grep -q "EVAL50_LEANKEEP_DONE" $CTL/logs/eval50_leankeep.log 2>/dev/null && break
  sleep 30
done
grep -q "EVAL50_LEANKEEP_DONE" $CTL/logs/eval50_leankeep.log 2>/dev/null || \
  { echo "[$(date '+%F %T')] FATAL: leankeep never finished (6h gate)"; exit 1; }
echo "[$(date '+%F %T')] leankeep done -> releasing its serve, starting rich/stock"
$SSHT "scancel -n eval4bl -u jy050706" 2>/dev/null
JID=$($SSHT "sbatch --parsable /gpfs/scrubbed/jy050706/qwen-serve/serve-chain-4b-rich-official.sbatch" 2>/dev/null | tr -dc 0-9)
echo "[$(date '+%F %T')] rich/stock serve job $JID"
JOB=eval4bro LPORT=$PORT RPORT=8015 setsid nohup $CTL/tunnel_qwen36_auto.sh > $HOME/tunnel_4bro.log 2>&1 < /dev/null &
for i in $(seq 1 120); do up && break; sleep 20; done
up || { echo "[$(date '+%F %T')] FATAL: rich/stock endpoint never came up"; exit 1; }
echo "[$(date '+%F %T')] rich/stock endpoint UP"

cat > $R/MODEL_BOUNDARY.json <<JSON
{"model":"Qwen3.5-4B SFT arm rich (job 232347), checkpoint-450 (3-epoch endpoint)",
 "served_model_name":"q38e3-rich450-stock","precision":"BF16 weights, fp8 kv-cache",
 "chat_template":"model built-in (OFFICIAL; strips history <think> at render)",
 "preserve_thinking":"client sends history think (upstream-identical); template discards",
 "cell":"rich/stock -- OSWorld-Verified DEFAULT serving; pairs with rich/rich to isolate history-think visibility at eval time",
 "sampling":{"temperature":1.0,"top_p":0.95,"top_k":20,"min_p":0.0,"presence_penalty":0.0,
             "repetition_penalty":1.0,"profile":"official general thinking; temp/top_p from client, rest from serve override"},
 "max_steps":50,"sleep_after_execution":3,"num_envs":2,
 "tasks":"verified_eval50_nonproxy.json (frozen stratified sample, seed 20260815)",
 "harness":"UNMODIFIED upstream behaviour; no OSTG_* env vars. Only delta vs richrich: serve-side template."}
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
    --sleep_after_execution 3 --enable_thinking --preserve_thinking --num_envs 2 --simple_path \
    --screen_width 1920 --screen_height 1080 \
    --test_config_base_dir $C --test_all_meta_path $META --result_dir $R
  stop_eval
done
echo "[$(date '+%F %T')] === eval50 rich/stock RESULT: $(find $R -name result.txt -exec cat {} \; 2>/dev/null | sort | uniq -c | tr '\n' ' ')"
echo "EVAL50_RICHSTOCK_DONE"
