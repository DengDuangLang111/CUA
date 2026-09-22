#!/bin/bash
# run_eval50_bhqs.sh -- Bhqs-2 (rev2 curation) arm, keepthink, 3 VMs.
# LAST in the chain (moved 2026-08-17: its training cannot schedule before
# the Aug-18 maintenance window, so arms with existing weights go first). Single variable vs Bs: the corpus. Retargeted
# from Bhqs-1 (user call 2026-08-17: keep its training, drop its eval)
# because rev2 fixed the gate that had removed ~36 clean trajectories.
# Log file and DONE marker keep their names so the LoRA link holds.
set -u
CTL=/mnt/d/research/osworld-verified-control
LOG=$CTL/logs/eval50_bhqs.log
exec >>$LOG 2>&1
cd /mnt/d/research/OSWorld; set -a; . ./.env; set +a
SSHT="ssh -n -S $HOME/.ssh/cm/qwen36-tillicum-login -o ControlMaster=no -o BatchMode=yes jy050706@tillicum-login02.hyak.uw.edu"
MODEL=q38Bhqs2t-gb64
PORT=18020
TAG=eval50-bhqs2tkeep-20260817
C=/mnt/d/research/OSWorld/evaluation_examples
META=$C/verified_eval50_nonproxy.json
R=/mnt/d/research/OSWorld/results_generated/qwen35-4b-sft/$TAG
up(){ [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $OPENAI_API_KEY" http://127.0.0.1:$PORT/v1/models)" = "200" ]; }

stop_eval(){
  pkill -f "run_multienv_qwen.*$TAG" 2>/dev/null
  for i in $(seq 1 30); do pgrep -f "run_multienv_qwen.*$TAG" >/dev/null || break; sleep 2; done
  pkill -9 -f "run_multienv_qwen.*$TAG" 2>/dev/null
  echo "[$(date '+%F %T')] eval runner stopped"
}

# Gate: previous arm in the chain must be finished.
for i in $(seq 1 2880); do
  grep -q "EVAL50_LEANSTOCK_DONE" $CTL/logs/eval50_lean_stock.log 2>/dev/null && break
  sleep 30
done
grep -q "EVAL50_LEANSTOCK_DONE" $CTL/logs/eval50_lean_stock.log 2>/dev/null || { echo "[$(date '+%F %T')] FATAL: gate EVAL50_LEANSTOCK_DONE never fired"; exit 1; }
# Gate: the checkpoint this arm needs.
for i in $(seq 1 480); do
  $SSHT 'ls -d /gpfs/scrubbed/jy050706/sft/out/q38Bhqs2t-gb64/v*/checkpoint-* >/dev/null 2>&1' && break
  sleep 60
done
$SSHT 'ls -d /gpfs/scrubbed/jy050706/sft/out/q38Bhqs2t-gb64/v*/checkpoint-* >/dev/null 2>&1' || { echo "[$(date '+%F %T')] FATAL: checkpoint missing"; exit 1; }
# Retire the previous serve, bring up ours.
$SSHT "scancel -n eval4bls -u jy050706" 2>/dev/null
JID=$($SSHT "sbatch --parsable /gpfs/scrubbed/jy050706/qwen-serve/serve-chain-4b-bhqs.sbatch" 2>/dev/null | tr -dc 0-9)
echo "[$(date '+%F %T')] serve job $JID (serve-chain-4b-bhqs.sbatch)"
JOB=eval4bhq LPORT=$PORT RPORT=$((PORT-10000)) setsid nohup $CTL/tunnel_qwen36_auto.sh > $HOME/tunnel_eval4bhq.log 2>&1 < /dev/null &
for i in $(seq 1 720); do up && break; sleep 20; done
up || { echo "[$(date '+%F %T')] FATAL: endpoint never came up"; exit 1; }
echo "[$(date '+%F %T')] endpoint UP"

for TRY in 1 2 3; do
  N=$(find $R -name result.txt 2>/dev/null | wc -l)
  T=$(python3 -c "import json;print(sum(len(v) for v in json.load(open('$META')).values()))")
  [ "$N" -ge "$T" ] && { echo "[$(date '+%F %T')] complete $N/$T"; break; }
  up || { echo "[$(date '+%F %T')] endpoint down at $N/$T, waiting"; for i in $(seq 1 240); do up && break; sleep 30; done; }
  up || { echo "[$(date '+%F %T')] FATAL: endpoint never came back"; exit 1; }
  echo "[$(date '+%F %T')] pass $TRY at $N/$T (3 envs)"
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
echo "[$(date '+%F %T')] === eval50 eval50-bhqskeep-20260817 RESULT: $(find $R -name result.txt -exec cat {} \; 2>/dev/null | sort | uniq -c | tr '\n' ' ')"
echo "EVAL50_BHQS_DONE"
