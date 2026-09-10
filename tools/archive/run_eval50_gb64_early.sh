#!/bin/bash
# run_eval50_gb64_early.sh -- gb64o (3ep, checkpoint-267) eval, EARLY START
# variant (user order 2026-08-17: "分一个vm开始跑64o"). Differences from
# run_eval50_gb128.sh: no Gate-1 wait; does NOT scancel the ep2 serve
# (its 2 marathon tasks still need it); phase A runs num_envs 1 alongside
# ep2's last tasks (VM budget 2+1=3), flips to num_envs 3 the moment the
# ep2 driver logs its DONE marker. Same serve/tunnel/result_dir as the
# retired gated driver, so results are one continuous run.
set -u
CTL=/mnt/d/research/osworld-verified-control
LOG=$CTL/logs/eval50_gb64_early.log
exec >>$LOG 2>&1
cd /mnt/d/research/OSWorld; set -a; . ./.env; set +a
SSHT="ssh -n -S $HOME/.ssh/cm/qwen36-tillicum-login -o ControlMaster=no -o BatchMode=yes jy050706@tillicum-login02.hyak.uw.edu"
MODEL=q38e3B-gb64o
PORT=18016
TAG=eval50-gb64keep-20260817
C=/mnt/d/research/OSWorld/evaluation_examples
META=$C/verified_eval50_nonproxy.json
R=/mnt/d/research/OSWorld/results_generated/qwen35-4b-sft/$TAG
EP2LOG=$CTL/logs/eval50_gb128ep2.log
mkdir -p $R
up(){ [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $OPENAI_API_KEY" http://127.0.0.1:$PORT/v1/models)" = "200" ]; }

stop_eval(){
  pkill -f "run_multienv_qwen.*$TAG" 2>/dev/null
  for i in $(seq 1 30); do pgrep -f "run_multienv_qwen.*$TAG" >/dev/null || break; sleep 2; done
  pkill -9 -f "run_multienv_qwen.*$TAG" 2>/dev/null
  echo "[$(date '+%F %T')] eval runner stopped"
}

run_pass(){ # $1 = num_envs
  OSWORLD_OPENAI_TIMEOUT=600 \
  .venv/bin/python scripts/python/run_multienv_qwen.py \
    --provider_name docker --path_to_vm /mnt/d/research/OSWorld/docker_vm_data/Ubuntu.qcow2 \
    --headless --observation_type screenshot --action_space pyautogui \
    --model $MODEL --base_url http://127.0.0.1:$PORT/v1 \
    --temperature 1.0 --top_p 0.95 --max_tokens 81920 --max_steps 50 \
    --sleep_after_execution 3 --enable_thinking --preserve_thinking --num_envs "$1" --simple_path \
    --screen_width 1920 --screen_height 1080 \
    --test_config_base_dir $C --test_all_meta_path $META --result_dir $R
}

# Gate: gb64o final checkpoint (should already be there).
$SSHT 'ls -d /gpfs/scrubbed/jy050706/sft/out/q38e3B-gb64o/v*/checkpoint-267 >/dev/null 2>&1' || \
  { echo "[$(date '+%F %T')] FATAL: gb64o checkpoint-267 missing"; exit 1; }

# Serve + tunnel -- WITHOUT cancelling the ep2 serve (eval4bg2 stays up).
JID=$($SSHT "sbatch --parsable /gpfs/scrubbed/jy050706/qwen-serve/serve-chain-4b-gb128.sbatch" 2>/dev/null | tr -dc 0-9)
echo "[$(date '+%F %T')] gb64o serve job $JID (ep2 serve left running)"
JOB=eval4bg LPORT=$PORT RPORT=8016 setsid nohup $CTL/tunnel_qwen36_auto.sh > $HOME/tunnel_4bg.log 2>&1 < /dev/null &
for i in $(seq 1 720); do up && break; sleep 20; done
up || { echo "[$(date '+%F %T')] FATAL: gb64o endpoint never came up"; exit 1; }
echo "[$(date '+%F %T')] gb64o endpoint UP"

cat > $R/MODEL_BOUNDARY.json <<JSON
{"model":"Qwen3.5-4B SFT arm B-gb64o: B corpus (312 trajs/5,659 samples), global batch 64 = 16xH200 x accum 4, 3ep, cosine warmup 0.1, wd 0.0, beta2 0.999 -- OpenWebRL-aligned optimizer, half-scale batch lever",
 "served_model_name":"q38e3B-gb64o","precision":"BF16 weights, fp8 kv-cache",
 "chat_template":"qwen35_4b_keepthink.jinja (same as richrich/leankeep/basekeep)",
 "preserve_thinking":true,"cell":"gb64keep -- optimization-regime lever + aligned optimizer",
 "sampling":{"temperature":1.0,"top_p":0.95,"top_k":20,"min_p":0.0,"presence_penalty":0.0,
             "repetition_penalty":1.0,"profile":"official general thinking; temp/top_p from client, rest from serve override"},
 "max_steps":50,"sleep_after_execution":3,"num_envs":"1 early overlap, then 3",
 "tasks":"verified_eval50_nonproxy.json (frozen stratified sample, seed 20260815)",
 "harness":"UNMODIFIED upstream behaviour; no OSTG_* env vars. Same serving as the keepthink column; weights are the only difference."}
JSON

# Phase A: single VM alongside ep2's marathon stragglers.
echo "[$(date '+%F %T')] phase A: num_envs 1 (ep2 still closing)"
run_pass 1 &
APID=$!
for i in $(seq 1 480); do
  grep -q "EVAL50_GB128EP2_DONE" $EP2LOG 2>/dev/null && break
  kill -0 $APID 2>/dev/null || break
  sleep 30
done
echo "[$(date '+%F %T')] ep2 done (or phase A ended); switching to 3 envs"
stop_eval
$SSHT "scancel -n eval4bg2 -u jy050706" 2>/dev/null

# Phase B: full 3-VM passes until complete (original retry loop).
for TRY in 1 2 3; do
  N=$(find $R -name result.txt 2>/dev/null | wc -l)
  T=$(python3 -c "import json;print(sum(len(v) for v in json.load(open('$META')).values()))")
  [ "$N" -ge "$T" ] && { echo "[$(date '+%F %T')] complete $N/$T"; break; }
  up || { echo "[$(date '+%F %T')] endpoint down at $N/$T, waiting"; for i in $(seq 1 240); do up && break; sleep 30; done; }
  up || { echo "[$(date '+%F %T')] FATAL: endpoint never came back"; exit 1; }
  echo "[$(date '+%F %T')] pass $TRY at $N/$T (3 envs)"
  run_pass 3
  stop_eval
done
echo "[$(date '+%F %T')] === eval50 gb64keep RESULT: $(find $R -name result.txt -exec cat {} \; 2>/dev/null | sort | uniq -c | tr '\n' ' ')"
echo "EVAL50_GB128_DONE"
