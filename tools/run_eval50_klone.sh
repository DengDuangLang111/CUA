#!/bin/bash
# run_eval50_klone.sh <arm> -- run one eval-50 arm against a vLLM serve on KLONE.
#
# Same eval, same 3 WSL VMs, same stock template; only the endpoint moves. Used
# while tillicum is down for the 2026-08-18 maintenance (09:00 to 09:00, all 24
# GPU nodes). The VMs are the real bottleneck, not the GPU, so klone arms are
# serial with tillicum arms -- this waits for whatever holds the VMs first.
#
# Differences from run_eval50_stock.sh, all of them plumbing:
#   - the serve is submitted on klone (gpu-l40s, dedicated, no preemption)
#   - the node name is discovered from squeue and the tunnel is attached to the
#     live ControlMaster with -O forward, so no new login and no Duo
#   - the API key comes from klone, not from OSWorld's .env, which still points
#     at tillicum for anything running there
#
# NODE-LOCAL EVERYTHING on the serve side: see serve_l40s.sbatch. Three separate
# stalls today came from GPFS small-file traffic.
set -u
ARM="${1:?usage: run_eval50_klone.sh <arm>}"

#          weights dir under /gscratch/cse/jy050706/sft/models   served name
case "$ARM" in
  kD) W=q38Bhqs2t-gb64-e300;    MN=q38Bhqs2t-gb64   ;;   # 全量 x r5 lr1e-5
  kC) W=q38Bs-gb64-e264;        MN=q38Bs-gb64       ;;   # 全量 x Bs  (2x2 最后一格)
  kE) W=q38Bhqs2t-lr3e6-e300;   MN=q38Bhqs2t-lr3e6  ;;   # 全量 x r5 lr3e-6
  kF) W=q38Bhqs2t-loralean-e300;MN=q38Bhqs2t-loralean;;  # LoRA x r5 lean
  kG) W=q38Bhqs2t-loranp-e300;  MN=q38Bhqs2t-loranp ;;   # LoRA x r5 no-prose
  # D again at ~1 epoch. Every arm that currently beats the base was served
  # an accidental ~1-epoch checkpoint (the lexicographic picker bug), so the
  # epoch question has never been asked deliberately on a full fine-tune.
  # checkpoint-90 is epoch 0.90, the closest saved point to one epoch; named
  # for its real epoch rather than rounded, because a mislabelled checkpoint
  # already cost this project a week.
  kD1) W=q38Bhqs2t-gb64-e090;   MN=q38Bhqs2t-gb64-e090 ;;  # 全量 x r5 @e0.90
  *) echo "unknown arm: $ARM" >&2; exit 2 ;;
esac

CTL=/mnt/d/research/osworld-verified-control
LOG=$CTL/logs/eval50_$ARM.log
exec >>$LOG 2>&1
cd /mnt/d/research/OSWorld
KS=$HOME/.ssh/cm/klone-login
KH=jy050706@klone.hyak.uw.edu
KSSH="ssh -n -S $KS -o ControlMaster=no -o BatchMode=yes $KH"
BASE=/gscratch/cse/jy050706
PORT=18030
C=/mnt/d/research/OSWorld/evaluation_examples
META=$C/verified_eval50_nonproxy.json
RES=/mnt/d/research/OSWorld/results_generated/qwen35-4b-sft

R=$(ls -dt $RES/eval50-$ARM-* 2>/dev/null | head -1)
[ -n "$R" ] || R=$RES/eval50-$ARM-$(date +%Y%m%d)
mkdir -p "$R"; TAG=$(basename "$R")
echo "[$(date '+%F %T')] === $ARM ($W) -> $R"

KEY=$($KSSH "cat $BASE/.vllm_api_key")
up(){ [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $KEY" http://127.0.0.1:$PORT/v1/models)" = "200" ]; }
scored(){ find "$1" -name result.txt 2>/dev/null | wc -l; }
stop_eval(){ pkill -f "run_multienv_qwen.*$TAG" 2>/dev/null
  for i in $(seq 1 30); do pgrep -f "run_multienv_qwen.*$TAG" >/dev/null || break; sleep 2; done
  pkill -9 -f "run_multienv_qwen.*$TAG" 2>/dev/null; }

# ---- wait for whoever holds the 3 VMs ----
for i in $(seq 1 960); do
  pgrep -f "run_multienv_qwen" >/dev/null || break
  sleep 30
done
pgrep -f run_multienv_qwen >/dev/null && { echo "[$(date '+%F %T')] FATAL: VMs still busy after 8h"; exit 1; }
echo "[$(date '+%F %T')] VMs free"; sleep 20

# ---- serve on klone, then point the tunnel at whatever node it landed on ----
serve_up(){
  local jid node
  jid=$($KSSH "squeue -u jy050706 -h -n serve-l40s -o %i" | tr -dc 0-9 | head -c 12)
  if [ -z "$jid" ]; then
    jid=$($KSSH "cd $BASE && sbatch --parsable --export=ALL,MODEL=$BASE/sft/models/$W,NAME=$MN,PORT=8000 serve_l40s.sbatch" | tr -dc 0-9)
    echo "[$(date '+%F %T')] submitted klone serve $jid for $W"
  fi
  for i in $(seq 1 60); do
    node=$($KSSH "squeue -j $jid -h -o %N" | tr -d ' ')
    [ -n "$node" ] && [ "$node" != "(null)" ] && break
    sleep 20
  done
  [ -n "$node" ] || return 1
  echo "[$(date '+%F %T')] serve on $node -- attaching tunnel"
  ssh -S "$KS" -O cancel -L $PORT:$node:8000 "$KH" 2>/dev/null
  ssh -S "$KS" -O forward -L $PORT:$node:8000 "$KH"
}
serve_up
# startup is ~11 min: 7.6GB SIF copy to local disk, weights, compile, CUDA graphs
for i in $(seq 1 120); do up && break; sleep 20; done
up || { echo "[$(date '+%F %T')] FATAL: klone endpoint never came up"; exit 1; }

ROOT=$(curl -s -H "Authorization: Bearer $KEY" http://127.0.0.1:$PORT/v1/models \
       | python3 -c "import json,sys;print(json.load(sys.stdin)['data'][0].get('root',''))")
echo "[$(date '+%F %T')] endpoint UP; vLLM reports root=$ROOT"
python3 - "$R/MODEL_BOUNDARY.json" "$ARM" "$MN" "$ROOT" <<'PY'
import json, sys
p, arm, served, root = sys.argv[1:5]
json.dump({"arm": arm, "served_model_name": served,
  "weights_reported_by_vllm": root, "cluster": "klone gpu-l40s (NVIDIA L40S 45GiB)",
  "runtime": "apptainer, vllm/vllm-openai:v0.25.1-x86_64 -- same build as tillicum",
  "chat_template": "model built-in (OSWorld-Verified default); no override",
  "precision": "BF16 weights, fp8 kv-cache",
  "sampling": {"temperature":1.0,"top_p":0.95,"top_k":20,"min_p":0.0,
               "presence_penalty":0.0,"repetition_penalty":1.0},
  "max_steps": 50, "sleep_after_execution": 3, "num_envs": 3,
  "recording": "disabled via OSTG_NO_RECORD=1",
  "tasks": "verified_eval50_nonproxy.json (frozen stratified sample, seed 20260815)",
  "harness": "UNMODIFIED upstream behaviour"}, open(p,"w"), indent=1, ensure_ascii=False)
PY

T=$(python3 -c "import json;print(sum(len(v) for v in json.load(open('$META')).values()))")
for TRY in 1 2 3 4 5; do
  N=$(scored "$R"); [ "$N" -ge "$T" ] && { echo "[$(date '+%F %T')] complete $N/$T"; break; }
  up || { echo "[$(date '+%F %T')] endpoint down at $N/$T; re-establishing"; serve_up
          for i in $(seq 1 120); do up && break; sleep 20; done; }
  up || { echo "[$(date '+%F %T')] FATAL: endpoint gone"; exit 1; }
  echo "[$(date '+%F %T')] pass $TRY at $N/$T"
  OSWORLD_OPENAI_TIMEOUT=600 OSTG_NO_RECORD=1 OPENAI_API_KEY="$KEY" \
  .venv/bin/python scripts/python/run_multienv_qwen.py \
    --provider_name docker --path_to_vm /mnt/d/research/OSWorld/docker_vm_data/Ubuntu.qcow2 \
    --headless --observation_type screenshot --action_space pyautogui \
    --model $MN --base_url http://127.0.0.1:$PORT/v1 \
    --temperature 1.0 --top_p 0.95 --max_tokens 81920 --max_steps 50 \
    --sleep_after_execution 3 --enable_thinking --preserve_thinking --num_envs 3 --simple_path \
    --screen_width 1920 --screen_height 1080 \
    --test_config_base_dir $C --test_all_meta_path $META --result_dir "$R"
  stop_eval
done
N=$(scored "$R")
if [ "$N" -lt "$T" ]; then
  MISS=$(find "$R" -mindepth 2 -maxdepth 2 -type d '!' -exec test -e '{}/result.txt' ';' -print 2>/dev/null | sed "s|$R/||" | tr '\n' ' ')
  echo "[$(date '+%F %T')] INCOMPLETE $N/$T -- crashed: ${MISS:-none} (any remainder never started)"
fi
echo "[$(date '+%F %T')] === $ARM RESULT $N/$T: $(find "$R" -name result.txt -exec cat {} \; 2>/dev/null | sort | uniq -c | tr '\n' ' ')"
