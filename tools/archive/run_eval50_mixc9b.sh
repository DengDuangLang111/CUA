#!/bin/bash
# run_eval50_mixc9b.sh -- 臂 C(9B,纯 v16)的 eval-50。
#
# 2026-08-31 建,照抄 run_eval50_mixb4b.sh,只换权重/端口/占位作业。
#
# ⚠ 这是 **9B**。分数只能对着 **9B 基座**读,不能跟 4B 各臂并排比
#   (CHECKPOINTS.md 对 a2 臂的同款警告)。语料是**纯 v16**(v16-main +
#   v16-pilot,554 条),没有任何 v11 —— 它是臂 A/B 的"不掺旧数据"对照。
#
# 为什么单独一个脚本而不是往 run_eval50_stock.sh 加 ARM:
# 那个脚本自己提交 serve、自己挑 checkpoint、臂之间用 PREV/PJOB 首尾相接成链。
# 本次三样都不成立 —— serve 已经手工起在 Klone 的**占位作业**里(不是它认识的
# serve-chain-* 作业),权重是从 Tillicum 传过来的固定目录,而且这一臂不接在
# 任何链上。硬塞进去要动它的 serve_up/gate 两处核心逻辑,风险大于收益。
#
# 与已发布的十几个臂的口径差异,只有一处,是**故意的**:
#   --image_max 10 --fold_size 1
# 语料 build 时就定死了 img10/fold1(build.py --image-max 10 --fold-size 1),
# 而 eval-50 的默认是 20 图。训练窗口与评测窗口必须一致(build.py 自己的
# help 原文:"Training and eval must use the SAME value"),否则测的是
# 窗口错配而不是模型。08-29 图窗试点也把 i10 定为甜点(81.8 vs 锚 69.8)。
#
# 其余全部对齐既有口径:stock 模板、冻结 50 题、ms50、t1.0/top_p0.95、
# max_tokens 81920、num_envs 3、OSTG_TYPE_NO_SPLIT=1(kC 起的合并语义)。
#
# 超时用 1800 不是 600:A100 80GB PCIe 比 H200 慢,600s 在长生成上会让
# openai 客户端整步重试,表现为任务卡死而服务端健康(L40S 那次的原病)。
set -u
ARM=mixc9b
MN=mixC-9b-stock
JOBID=39187994                    # 占位作业 dxg_w18,serve 跑在它的空闲 A100 上
NODE=g3083
RPORT=8042                        # 远端 vLLM 端口
PORT=18042                        # 本地隧道端口
W=/gscratch/cse/jy050706/sft/models/mixC-9b-e627

CTL=/mnt/d/research/osworld-verified-control
LOG=$CTL/logs/eval50_$ARM.log
mkdir -p $CTL/logs
exec >>$LOG 2>&1
cd /mnt/d/research/OSWorld

KS=$HOME/.ssh/cm/klone-login
KH=jy050706@klone.hyak.uw.edu
KSSH="ssh -n -S $KS -o ControlMaster=no -o BatchMode=yes $KH"
C=/mnt/d/research/OSWorld/evaluation_examples
META=$C/verified_eval50_nonproxy.json
RES=/mnt/d/research/OSWorld/results_generated/qwen35-9b-sft   # 9B 组,不是 4B 组:dashboard 按父目录分组

KEY=$($KSSH "cat /gscratch/cse/jy050706/.vllm_api_key")
R=$(ls -dt $RES/eval50-$ARM-* 2>/dev/null | head -1)
[ -n "$R" ] || R=$RES/eval50-$ARM-$(date +%Y%m%d)
mkdir -p "$R"; TAG=$(basename "$R")
echo "[$(date '+%F %T')] === $ARM -> $R"

up(){ [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $KEY" \
        http://127.0.0.1:$PORT/v1/models)" = "200" ]; }
scored(){ find "$1" -name result.txt 2>/dev/null | wc -l; }
stop_eval(){ for p in $(ps -eo pid,args | grep "run_multienv_qwen" | grep "$TAG" | grep -v grep | awk '{print $1}'); do kill $p 2>/dev/null; done
  sleep 10
  for p in $(ps -eo pid,args | grep "run_multienv_qwen" | grep "$TAG" | grep -v grep | awk '{print $1}'); do kill -9 $p 2>/dev/null; done; }

# ---- 等着谁在占那 3 台 VM ----
# 必须同时看 **driver 和 runner** 两个进程。只看 runner 会在前一臂两趟之间
# 的空隙里误判成"已经跑完",两个 eval 同时开 3 台 VM = 6 台,撞 22GB 红线。
# 这是 run_eval50_stock.sh 抬头记录过的原病,照搬它的两进程闸。
for i in $(seq 1 960); do
  ps -eo args | grep -q "[r]un_multienv_qwen" && { sleep 30; continue; }
  ps -eo args | grep -q "[r]un_eval50_mixb4b" && { sleep 30; continue; }
  break
done
ps -eo args | grep -q "[r]un_multienv_qwen" && { echo "[$(date '+%F %T')] FATAL: 8 小时后 VM 仍被占"; exit 1; }
echo "[$(date '+%F %T')] VM 空出来了"; sleep 20

# ---- 隧道指向占位作业所在节点 ----
ssh -S "$KS" -O cancel -L $PORT:$NODE:$RPORT "$KH" 2>/dev/null
ssh -S "$KS" -O forward -L $PORT:$NODE:$RPORT "$KH"
for i in $(seq 1 90); do up && break; sleep 20; done
up || { echo "[$(date '+%F %T')] FATAL: 端点始终没起来"; exit 1; }

# ---- 服务端自报加载了什么(名字对不等于权重对,这一条是路径校验) ----
ROOT=$(curl -s -H "Authorization: Bearer $KEY" http://127.0.0.1:$PORT/v1/models \
       | python3 -c "import json,sys;print(json.load(sys.stdin)['data'][0].get('root',''))")
echo "[$(date '+%F %T')] endpoint UP; vLLM reports root=$ROOT"
[ "$ROOT" = "$W" ] || { echo "[$(date '+%F %T')] FATAL: 服务的是 $ROOT,不是 $W"; exit 1; }

python3 - "$R/MODEL_BOUNDARY.json" "$ARM" "$MN" "$ROOT" <<'PY'
import json, sys
p, arm, served, root = sys.argv[1:5]
json.dump({"arm": arm, "served_model_name": served,
  "weights_reported_by_vllm": root,
  "corpus": "v16-main + v16-pilot ONLY (554 traj / 13,372 samples) -- NO v11 at all",
  "train_recipe": "Qwen3.5-9B full FT, lr 3e-6, gb 64, 3 epochs, img10/fold1, checkpoint-627 (epoch 3.0)",
  "cluster": "klone gpu-a100 (NVIDIA A100 80GB PCIe, sm_80) inside placeholder job 39187994 on g3083",
  "runtime": "apptainer, vllm/vllm-openai:v0.25.1 -- same build as tillicum",
  "chat_template": "model built-in (OSWorld-Verified default); no override",
  "precision": "BF16 weights, kv-cache auto (NOT fp8: sm_80 lacks fp8)",
  "sampling": {"temperature":1.0,"top_p":0.95,"top_k":20,"min_p":0.0,
               "presence_penalty":0.0,"repetition_penalty":1.0},
  "max_steps": 50, "sleep_after_execution": 3, "num_envs": 3,
  "image_window": "--image_max 10 --fold_size 1 (MATCHES the training window; eval-50 default is 20)",
  "recording": "disabled via OSTG_NO_RECORD=1",
  "tasks": "verified_eval50_nonproxy.json (frozen stratified sample, seed 20260815)",
  "harness": "OSTG_TYPE_NO_SPLIT=1 (multi-line type sent as ONE typewrite, kC-onward semantics)",
  "backbone_warning": "9B -- compare against the 9B base, NEVER against the 4B arms"},
  open(p,"w"), indent=1, ensure_ascii=False)
PY

T=$(python3 -c "import json;print(sum(len(v) for v in json.load(open('$META')).values()))")
for TRY in 1 2 3 4 5; do
  N=$(scored "$R"); [ "$N" -ge "$T" ] && { echo "[$(date '+%F %T')] complete $N/$T"; break; }
  up || { echo "[$(date '+%F %T')] 端点在 $N/$T 掉了,重挂隧道"
          ssh -S "$KS" -O cancel -L $PORT:$NODE:$RPORT "$KH" 2>/dev/null
          ssh -S "$KS" -O forward -L $PORT:$NODE:$RPORT "$KH"
          for i in $(seq 1 90); do up && break; sleep 20; done; }
  up || { echo "[$(date '+%F %T')] FATAL: 端点没了"; exit 1; }
  echo "[$(date '+%F %T')] pass $TRY at $N/$T"
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
  stop_eval
done
N=$(scored "$R")
echo "[$(date '+%F %T')] === $ARM RESULT $N/$T: $(find "$R" -name result.txt -exec cat {} \; 2>/dev/null | sort | uniq -c | tr '\n' ' ')"
