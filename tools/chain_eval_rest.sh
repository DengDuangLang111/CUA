#!/bin/bash
# chain_eval_rest.sh -- 剩下三臂(mixb9b / mixa9b / mixa4b)的 eval-50,串行。
#
# 2026-08-31 建。为什么拆成两段跑在两台机器上:
#   推权重必须从 tillicum-login02 发起(到 Klone 的 klone.sock 只在那台,
#   login01 连不过去);跑 eval 必须在 WSL(3 台 Docker VM 在那)。
#   两边靠 Klone 上的 READY_<arm> 标记对接 —— 内容是权重绝对路径,
#   本脚本拿它做 vLLM root 断言,所以标记同时是"就绪信号"和"该服务什么"。
#   login02 那一半 = /gpfs/scrubbed/jy050706/sft/prep_evals.sh
#
# 顺序按用户指定:B-9B -> A-9B -> A-4B。三台 VM 是硬瓶颈,只能串行。
#
# 口径与 mixb4b/mixc9b 完全一致,包括那个故意的
# --image_max 10 --fold_size 1(语料 build 时就是 img10/fold1)。
set -u
CTL=/mnt/d/research/osworld-verified-control
LOG=$CTL/logs/chain_eval_rest.log
mkdir -p $CTL/logs
exec >>$LOG 2>&1
cd /mnt/d/research/OSWorld
KS=$HOME/.ssh/cm/klone-login
KH=jy050706@klone.hyak.uw.edu
KSSH="ssh -n -S $KS -o ControlMaster=no -o BatchMode=yes $KH"
KB=/gscratch/cse/jy050706
C=/mnt/d/research/OSWorld/evaluation_examples
KEY=$($KSSH "cat $KB/.vllm_api_key")
echo "=========== [$(date '+%F %T')] eval 链启动 ==========="

# arm|远端端口|本地端口|serve节点|结果组|题面板|权重(- = 等 READY 标记)|语料说明|配方说明
#
# 顺序(用户 2026-08-31 定):
#   1 mixb4b50b  冻结 100 的**另一半**(2026-08-15 封存至今没跑过、没进过任何
#                决策的预注册样本外集)。同一份权重、同一个 serve(g3084:8041,
#                占位作业 39187993),不传权重不起服务 —— 所以排最前,它能立刻跑。
#   2..5         **全部改跑 eval100**(= eval50 ∪ eval50b,已逐题核验相等)。
#                代价:每臂题数翻倍,9B 一臂约 5-6 小时。
ARMS="
mixb4b50b|8041|18041|g3084|qwen35-4b-sft|verified_eval50b_nonproxy.json|/gscratch/cse/jy050706/sft/models/mixB-4b-e873|v16-main + v16-pilot + v11new-500 + v11new-all (866 traj / 18,576 samples)|Qwen3.5-4B full FT, lr 3e-6, gb 64, 3 ep, img10/fold1 -- SAME weights as mixb4b, HELD-OUT half of the frozen 100
mixc9b|8042|18042|g3083|qwen35-9b-sft|verified_eval100_nonproxy.json|/gscratch/cse/jy050706/sft/models/mixC-9b-e627|v16-main + v16-pilot ONLY (554 traj / 13,372 samples) -- NO v11 at all|Qwen3.5-9B full FT, lr 3e-6, gb 64, 3 ep, img10/fold1, checkpoint-627
mixb9b|8043|18043|g3085|qwen35-9b-sft|verified_eval100_nonproxy.json|-|v16-main + v16-pilot + v11new-500 + v11new-all (866 traj / 18,576 samples)|Qwen3.5-9B full FT, lr 3e-6, gb 64, 3 ep, img10/fold1
mixa9b|8045|18045|g3082|qwen35-9b-sft|verified_eval100_nonproxy.json|-|v16-main + v16-pilot + q38-Bhqs2t-r5nocapimg10-v11100/-v11500 (914 traj / 19,846 samples)|Qwen3.5-9B full FT, lr 3e-6, gb 64, 3 ep, img10/fold1 (resumed from ckpt-311 after a g012 GPU fault)
mixa4b|8044|18044|g3087|qwen35-4b-sft|verified_eval100_nonproxy.json|-|v16-main + v16-pilot + q38-Bhqs2t-r5nocapimg10-v11100/-v11500 (914 traj / 19,846 samples)|Qwen3.5-4B full FT, lr 3e-6, gb 64, 3 ep, img10/fold1
"

for row in $ARMS; do
  [ -z "$row" ] && continue
  ARM=$(echo  $row | cut -d'|' -f1); RPORT=$(echo $row | cut -d'|' -f2)
  PORT=$(echo $row | cut -d'|' -f3); NODE=$(echo  $row | cut -d'|' -f4)
  GRP=$(echo  $row | cut -d'|' -f5); METAF=$(echo $row | cut -d'|' -f6)
  WFIX=$(echo $row | cut -d'|' -f7); CORP=$(echo  $row | cut -d'|' -f8)
  RECIPE=$(echo $row | cut -d'|' -f9)
  META=$C/$METAF
  MN=$ARM-stock
  [ "$ARM" = "mixb4b50b" ] && MN=mixB-4b-stock   # 复用同一个 serve,服务名是它注册的那个
  echo "--- [$(date '+%F %T')] $ARM ---"

  # 1) 权重来源:WFIX 写死的直接用(复用别人已在跑的 serve);写 "-" 的
  #    等 login02 那一半推完权重、拉起 serve、写下 READY 标记(最多 24h)。
  if [ "$WFIX" != "-" ]; then
    W=$WFIX; echo "[$(date '+%F %T')] $ARM 复用已在跑的 serve,权重=$W"
  else
    W=""
    for i in $(seq 1 2880); do
      W=$($KSSH "cat $KB/READY_$ARM 2>/dev/null" | tr -d ' \r\n')
      [ -n "$W" ] && break
      sleep 30
    done
    [ -n "$W" ] || { echo "[$(date '+%F %T')] $ARM 24h 内没等到 READY,跳过"; continue; }
    echo "[$(date '+%F %T')] $ARM READY,权重=$W"
  fi

  # 2) 等 3 台 VM。必须同时看 runner 和其他 driver:只看 runner 会在前一臂
  #    两趟之间的空隙误判成"跑完了",两个 eval 各开 3 台 = 6 台,撞 22GB 红线。
  for i in $(seq 1 2880); do
    ps -eo args | grep -q "[r]un_multienv_qwen"   && { sleep 30; continue; }
    ps -eo args | grep -q "[r]un_eval50_mixb4b"   && { sleep 30; continue; }
    break
  done
  echo "[$(date '+%F %T')] $ARM VM 空出来了"; sleep 20

  R=$(ls -dt /mnt/d/research/OSWorld/results_generated/$GRP/eval50-$ARM-* 2>/dev/null | head -1)
  [ -n "$R" ] || R=/mnt/d/research/OSWorld/results_generated/$GRP/eval50-$ARM-$(date +%Y%m%d)
  mkdir -p "$R"; TAG=$(basename "$R")

  up(){ [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $KEY" \
          http://127.0.0.1:$PORT/v1/models)" = "200" ]; }
  ssh -S "$KS" -O cancel -L $PORT:$NODE:$RPORT "$KH" 2>/dev/null
  ssh -S "$KS" -O forward -L $PORT:$NODE:$RPORT "$KH"
  for i in $(seq 1 120); do up && break; sleep 20; done
  up || { echo "[$(date '+%F %T')] $ARM FATAL: 端点没起来"; continue; }

  # 3) 服务端自报加载了什么。名字对不等于权重对——这一条是路径校验。
  ROOT=$(curl -s -H "Authorization: Bearer $KEY" http://127.0.0.1:$PORT/v1/models \
         | python3 -c "import json,sys;print(json.load(sys.stdin)['data'][0].get('root',''))")
  echo "[$(date '+%F %T')] $ARM endpoint UP; vLLM reports root=$ROOT"
  [ "$ROOT" = "$W" ] || { echo "[$(date '+%F %T')] $ARM FATAL: 服务的是 $ROOT,不是 $W"; continue; }

  python3 - "$R/MODEL_BOUNDARY.json" "$ARM" "$MN" "$ROOT" "$CORP" "$RECIPE" "$METAF" <<'PY'
import json, sys
p, arm, served, root, corpus, recipe = sys.argv[1:7]  # sys.argv[7] = 题面板文件名
json.dump({"arm": arm, "served_model_name": served, "weights_reported_by_vllm": root,
  "corpus": corpus, "train_recipe": recipe,
  "cluster": "klone gpu-a100 (NVIDIA A100 80GB PCIe, sm_80) inside a placeholder job",
  "runtime": "apptainer, vllm/vllm-openai:v0.25.1 -- same build as tillicum",
  "chat_template": "model built-in (OSWorld-Verified default); no override",
  "precision": "BF16 weights, kv-cache auto (NOT fp8: sm_80 lacks fp8)",
  "sampling": {"temperature":1.0,"top_p":0.95,"top_k":20,"min_p":0.0,
               "presence_penalty":0.0,"repetition_penalty":1.0},
  "max_steps": 50, "sleep_after_execution": 3, "num_envs": 3,
  "image_window": "--image_max 10 --fold_size 1 (MATCHES the training window; eval-50 default is 20)",
  "recording": "disabled via OSTG_NO_RECORD=1",
  "tasks": sys.argv[7],
  "harness": "OSTG_TYPE_NO_SPLIT=1 (multi-line type sent as ONE typewrite, kC-onward semantics)",
  "backbone_warning": ("9B -- compare against the 9B base, NEVER against the 4B arms"
                       if "9b" in arm else "4B")}, open(p,"w"), indent=1, ensure_ascii=False)
PY

  T=$(python3 -c "import json;print(sum(len(v) for v in json.load(open('$META')).values()))")
  for TRY in 1 2 3 4 5; do
    N=$(find "$R" -name result.txt 2>/dev/null | wc -l)
    [ "$N" -ge "$T" ] && { echo "[$(date '+%F %T')] $ARM complete $N/$T"; break; }
    up || { ssh -S "$KS" -O cancel -L $PORT:$NODE:$RPORT "$KH" 2>/dev/null
            ssh -S "$KS" -O forward -L $PORT:$NODE:$RPORT "$KH"
            for i in $(seq 1 120); do up && break; sleep 20; done; }
    up || { echo "[$(date '+%F %T')] $ARM FATAL: 端点没了"; break; }
    echo "[$(date '+%F %T')] $ARM pass $TRY at $N/$T"
    OSWORLD_OPENAI_TIMEOUT=1800 OSTG_NO_RECORD=1 OSTG_TYPE_NO_SPLIT=1 OPENAI_API_KEY="$KEY" \
    .venv/bin/python scripts/python/run_multienv_qwen.py \
      --provider_name docker --path_to_vm /mnt/d/research/OSWorld/docker_vm_data/Ubuntu.qcow2 \
      --headless --observation_type screenshot --action_space pyautogui \
      --model $MN --base_url http://127.0.0.1:$PORT/v1 \
      --temperature 1.0 --top_p 0.95 --max_tokens 81920 --max_steps 50 \
      --sleep_after_execution 3 --enable_thinking --preserve_thinking --num_envs 3 --simple_path \
      --screen_width 1920 --screen_height 1080 \
      --image_max 10 --fold_size 1 \
      --test_config_base_dir $C --test_all_meta_path $META --result_dir "$R"
    for p in $(ps -eo pid,args | grep "run_multienv_qwen" | grep "$TAG" | grep -v grep | awk '{print $1}'); do kill $p 2>/dev/null; done
    sleep 10
  done
  N=$(find "$R" -name result.txt 2>/dev/null | wc -l)
  echo "[$(date '+%F %T')] === $ARM RESULT $N/$T: $(find "$R" -name result.txt -exec cat {} \; 2>/dev/null | sort | uniq -c | tr '\n' ' ')"
done
echo "=========== [$(date '+%F %T')] eval 链结束 ==========="
