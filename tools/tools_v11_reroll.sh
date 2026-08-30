#!/bin/bash
# tools_v11_reroll.sh -- teacher re-roll of the legacy pools at the champion
# window (i10 fold1, xhigh, lineage defaults elsewhere). User order 08-29 eve:
# legacy 544 runs LOCAL on 3 VMs while the 1796 main pool moves to AWS.
# Serve submit/reuse + tunnel + identity assert + resume passes + gap guard
# are condensed from run_eval50_stock.sh (same battle-tested shapes).
set -u
cd /mnt/d/research/OSWorld
set -a; . ./.env; set +a
CTL=/mnt/d/research/osworld-verified-control
exec >>$CTL/logs/v11_reroll.log 2>&1
SSHT="ssh -n -S $HOME/.ssh/cm/qwen36-tillicum-login -o ControlMaster=no -o BatchMode=yes jy050706@tillicum-login02.hyak.uw.edu"
echo "[reroll] up $(date)"
HAVE=$($SSHT "squeue -u jy050706 -h -n eval38h20 -o %i" 2>/dev/null | tr -dc 0-9)
if [ -z "$HAVE" ]; then
  JID=$($SSHT "sbatch --parsable /gpfs/scrubbed/jy050706/qwen-serve/serve-chain-38-i-h20.sbatch" 2>/dev/null | tr -dc 0-9)
  echo "[reroll] submitted serve $JID"
else
  echo "[reroll] reusing live serve $HAVE"
fi
JOB=eval38h20 LPORT=18020 RPORT=8000 setsid nohup $CTL/tunnel_qwen36_auto.sh > $HOME/tunnel_reroll.log 2>&1 < /dev/null &
up(){ [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $OPENAI_API_KEY" http://127.0.0.1:18020/v1/models)" = "200" ]; }
for i in $(seq 1 1440); do up && break; sleep 30; done
up || { echo "[reroll] FATAL: endpoint never up in 12h"; exit 1; }
SERVED=$(curl -s -m 10 -H "Authorization: Bearer $OPENAI_API_KEY" http://127.0.0.1:18020/v1/models | python3 -c "import json,sys
try: print(' '.join(m.get('id','') for m in (json.load(sys.stdin).get('data') or [])))
except Exception: print('')" 2>/dev/null)
case " $SERVED " in
  *" qwen38-27b-local "*) echo "[reroll] identity OK: $SERVED" ;;
  *) echo "[reroll] FATAL: port 18020 serves '$SERVED', want qwen38-27b-local"; exit 1 ;;
esac
V8=/mnt/d/research/os-simple-taskgen-v8/out/runs
run_set() {  # $1=set dir  $2=result tag  $3=expected count
  R=/mnt/d/research/OSWorld/results_generated/qwen38-27b-local/$2
  mkdir -p "$R"
  M=$(python3 -c "import json;print(sum(len(v) for v in json.load(open('$V8/$1/manifest.json')).values()))")
  echo "[reroll] $2 manifest=$M expect=$3"
  [ "$M" = "$3" ] || { echo "[reroll] FATAL: manifest count mismatch for $1"; exit 1; }
  for TRY in 1 2 3 4; do
    N=$(find "$R" -name result.txt 2>/dev/null | wc -l)
    [ "$N" -ge "$3" ] && break
    up || for i in $(seq 1 720); do up && break; sleep 30; done
    echo "[reroll] $2 pass $TRY at $N/$3 $(date)"
    ( miss=0
      while pgrep -f "run_multienv_qwen.*$2" >/dev/null 2>&1; do
        sleep 60
        if up; then miss=0; else
          miss=$((miss+1))
          [ $miss -ge 3 ] && { echo "[reroll] serve gone 3min, killing runner for resume"; pkill -f "run_multienv_qwen.*$2"; break; }
        fi
      done ) &
    G=$!
    OSWORLD_OPENAI_TIMEOUT=600 OSTG_NO_RECORD=1 OSTG_TYPE_NO_SPLIT=1 \
    .venv/bin/python scripts/python/run_multienv_qwen.py \
      --provider_name docker --path_to_vm /mnt/d/research/OSWorld/docker_vm_data/Ubuntu.qcow2 \
      --headless --observation_type screenshot --action_space pyautogui \
      --model qwen38-27b-local --base_url http://127.0.0.1:18020/v1 \
      --temperature 1.0 --top_p 0.95 --max_tokens 81920 --max_steps 50 \
      --sleep_after_execution 3 --enable_thinking --preserve_thinking --num_envs 3 --simple_path \
      --screen_width 1920 --screen_height 1080 \
      --image_max 10 --fold_size 1 \
      --test_config_base_dir $V8/$1 --test_all_meta_path $V8/$1/manifest.json \
      --result_dir "$R"
    kill $G 2>/dev/null
    pkill -f "run_multienv_qwen.*$2" 2>/dev/null; sleep 3
  done
  N=$(find "$R" -name result.txt 2>/dev/null | wc -l)
  P=$(find "$R" -name result.txt -exec awk '{print $1; exit}' {} \; 2>/dev/null | awk '{t+=$1} END{printf "%.1f", t}')
  echo "[reroll] === $2 DONE $N/$3 pass_sum=$P $(date)"
  docker ps -q --filter ancestor=happysixd/osworld-docker | xargs -r docker rm -f >/dev/null 2>&1
}
run_set v11-500-final v11-500-i10x-20260829 444
run_set v11-all      v11-all-i10x-20260829  100
echo "[reroll] ALL-REROLL-DONE $(date)"
