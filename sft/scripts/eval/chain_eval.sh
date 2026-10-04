#!/bin/bash
# chain_eval.sh -- 参数化 eval 链。2026-09-09 由 9 份逐臂复制的 chain_eval_*.sh 合并而成:
# 它们两两只差 6-8 行(头注释 / LOG 路径 / 一行臂表),机制逐字同(见 sft/scripts/archive/README.md)。
# 机制正文与 chain_eval_btf.sh(tools/archive/)逐字节相同,只把臂表与日志名改成参数。
#
# 用法(在 WSL,$CTL 下运行;仓库里的这份是版本化镜像,见 docs/RUNTIME_MIRRORS.md):
#   bash chain_eval.sh <arms.tsv> [label]
#   arms.tsv  每行一个臂,'|' 分隔 10 列(第 10 列可省;'#' 开头与空行忽略):
#     arm|远端端口|本地端口|serve节点|结果组|题面板|权重(- = 等 READY 标记)|语料说明|配方说明|[XWIN 推理窗口]
#     XWIN 不写 = "--image_max 10 --fold_size 1"(现行标准);a2/a7 协议写 "--image_max 20 --fold_size 10"。
#   label     缺省 = 文件名(不含 .tsv);决定日志 $CTL/logs/chain_eval_<label>.log。
#   臂名用 sft/armname.py 生成的规范名:结果目录 eval50-<arm>-<日期>、MODEL_BOUNDARY.json、看板键都用它。
#
# 为什么拆成两段跑在两台机器上(2026-08-31):
#   推权重必须从 tillicum-login02 发起(到 Klone 的 klone.sock 只在那台,login01 连不过去);
#   跑 eval 必须在 WSL(3 台 Docker VM 在那)。两边靠 Klone 上的 READY_<arm> 标记对接 ——
#   内容是权重绝对路径,本脚本拿它做 vLLM root 断言,所以标记同时是"就绪信号"和"该服务什么"。
#   login02 那一半 = /gpfs/scrubbed/jy050706/sft/prep_evals.sh
# 三台 VM 是硬瓶颈,只能串行。口径与 mixb4b/mixc9b 完全一致,包括那个故意的
# --image_max 10 --fold_size 1(语料 build 时就是 img10/fold1)。
set -u
ARMS_FILE=${1:?usage: chain_eval.sh <arms.tsv> [label]}
LABEL=${2:-$(basename "$ARMS_FILE" .tsv)}
CTL=/mnt/d/research/osworld-verified-control
LOG=$CTL/logs/chain_eval_$LABEL.log
mkdir -p $CTL/logs
exec >>$LOG 2>&1
cd /mnt/d/research/OSWorld
KS=$HOME/.ssh/cm/klone-login
KH=jy050706@klone.hyak.uw.edu
KSSH="ssh -n -S $KS -o ControlMaster=no -o BatchMode=yes $KH"
KB=/gscratch/cse/jy050706
C=/mnt/d/research/OSWorld/evaluation_examples
KEY=$($KSSH "cat $KB/.vllm_api_key")
echo "=========== [$(date '+%F %T')] eval 链启动 ($LABEL <- $ARMS_FILE) ==========="

# 必须按**行**读。`for row in $ARMS` 是按任意空白分词的,而表格里的语料说明
# 含空格(v16-main + v16-pilot ...),于是第一行之后每个空格碎片都被当成一行,
# 臂名变成 "+" —— 2026-09-01 01:48 实测到这个症状。
while IFS= read -r row; do
  case "$row" in ''|'#'*) continue;; esac
  case "$row" in *"|"*) : ;; *) continue;; esac
  ARM=$(echo  $row | cut -d'|' -f1); RPORT=$(echo $row | cut -d'|' -f2)
  PORT=$(echo $row | cut -d'|' -f3); NODE=$(echo  $row | cut -d'|' -f4)
  GRP=$(echo  $row | cut -d'|' -f5); METAF=$(echo $row | cut -d'|' -f6)
  WFIX=$(echo $row | cut -d'|' -f7); CORP=$(echo  $row | cut -d'|' -f8)
  RECIPE=$(echo $row | cut -d'|' -f9)
  XWIN=$(echo   $row | cut -d'|' -f10); [ -n "$XWIN" ] || XWIN="--image_max 10 --fold_size 1"
  META=$C/$METAF
  MN=$ARM-stock
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
  # 从端点同时取 root(路径)和 id(服务名)。路径管**正确性**,名字管**一致性**。
  # 2026-09-01 的教训:mixc9b 的 serve 注册成 mixC-9b-stock,而链算出的是
  # mixc9b-stock,每次请求 404、runner 吞掉异常、100 题全部灌 0。当时只断言了
  # 路径,没断言名字。现在**直接用服务端自报的 id 当模型名**,拼写不可能再错;
  # 路径仍然硬断言。
  EP=$(curl -s -H "Authorization: Bearer $KEY" http://127.0.0.1:$PORT/v1/models)
  ROOT=$(echo "$EP" | python3 -c "import json,sys;print(json.load(sys.stdin)['data'][0].get('root',''))")
  SRVNAME=$(echo "$EP" | python3 -c "import json,sys;print(json.load(sys.stdin)['data'][0].get('id',''))")
  [ -n "$SRVNAME" ] || { echo "[$(date '+%F %T')] $ARM FATAL: 端点没报服务名"; continue; }
  if [ "$SRVNAME" != "$MN" ]; then
    echo "[$(date '+%F %T')] $ARM 服务名不一致: 端点=$SRVNAME 链算的=$MN -> 改用端点自报的"
    MN=$SRVNAME
  fi
  echo "[$(date '+%F %T')] $ARM endpoint UP; vLLM reports root=$ROOT"
  [ "$ROOT" = "$W" ] || { echo "[$(date '+%F %T')] $ARM FATAL: 服务的是 $ROOT,不是 $W"; continue; }

  python3 - "$R/MODEL_BOUNDARY.json" "$ARM" "$MN" "$ROOT" "$CORP" "$RECIPE" "$METAF" "$XWIN" <<'PY'
import json, sys
p, arm, served, root, corpus, recipe = sys.argv[1:7]  # sys.argv[7] = 题面板文件名, [8] = 推理窗口
json.dump({"arm": arm, "served_model_name": served, "weights_reported_by_vllm": root,
  "corpus": corpus, "train_recipe": recipe,
  "cluster": "klone gpu-a100 (NVIDIA A100 80GB PCIe, sm_80) inside a placeholder job",
  "runtime": "apptainer, vllm/vllm-openai:v0.25.1 -- same build as tillicum",
  "chat_template": "model built-in (OSWorld-Verified default); no override",
  "precision": "BF16 weights, kv-cache auto (NOT fp8: sm_80 lacks fp8)",
  "sampling": {"temperature":1.0,"top_p":0.95,"top_k":20,"min_p":0.0,
               "presence_penalty":0.0,"repetition_penalty":1.0},
  "max_steps": 50, "sleep_after_execution": 3, "num_envs": 3,
  "image_window": sys.argv[8] + (" (MATCHES the training window)" if "image_max 10 " in sys.argv[8] else " (WIDER than the img10/fold1 training window; a2/a7 protocol)"),
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
      $XWIN \
      --test_config_base_dir $C --test_all_meta_path $META --result_dir "$R"
    for p in $(ps -eo pid,args | grep "run_multienv_qwen" | grep "$TAG" | grep -v grep | awk '{print $1}'); do kill $p 2>/dev/null; done
    sleep 10
  done
  N=$(find "$R" -name result.txt 2>/dev/null | wc -l)
  echo "[$(date '+%F %T')] === $ARM RESULT $N/$T: $(find "$R" -name result.txt -exec cat {} \; 2>/dev/null | sort | uniq -c | tr '\n' ' ')"
done < "$ARMS_FILE"
echo "=========== $(date '+%F %T')] eval 链结束 ==========="
