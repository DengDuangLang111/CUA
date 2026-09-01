#!/bin/bash
# chain_eval_lr.sh -- 四个学习率变体的 eval-100,串行。
#
# 2026-09-01 建。与 chain_eval_rest.sh 并行存在,但**互相让路**:两条链都
# 在闸里等对方,3 台 VM 一次只喂一臂。
#
# 与 chain_eval_rest 的结构差异,都是被现实逼出来的:
#
# 1) **serve 由本链现起,不由 prep 起。** 上一版 prep 在起 serve 那一步挂死
#    13 小时:ssh 里 `setsid srun ... &` 的后台进程一直持着 SSH 通道,ssh 等
#    EOF 等不到,写 READY 的那行永远执行不到。现在 prep 只推权重+写标记,
#    serve 归本链管,prep 里不再有任何后台远程进程。
#
# 2) **四臂共用一个占位作业(39306243/g3085)。** 六个占位里五个已被前五臂的
#    serve 占着,只剩这一个。所以每臂开跑前先 scancel 掉该占位上的旧 job
#    step(上一臂的 serve),再起自己的 —— 一张 A100 装不下两个 9B。
#    用 scancel 步骤号而不是 pkill:本项目 pkill -f 自匹配自杀过五次。
#
# 3) 全部跑 eval100(用户 2026-09-01 定)。四臂都是 9B,结果进 qwen35-9b-sft。
set -u
CTL=/mnt/d/research/osworld-verified-control
LOG=$CTL/logs/chain_eval_lr.log
mkdir -p $CTL/logs
exec >>$LOG 2>&1
cd /mnt/d/research/OSWorld
KS=$HOME/.ssh/cm/klone-login
KH=jy050706@klone.hyak.uw.edu
KSSH="ssh -n -S $KS -o ControlMaster=no -o BatchMode=yes $KH"
KB=/gscratch/cse/jy050706
PH=39306243          # 唯一空闲的占位作业(g3085)
NODE=g3085
RPORT=8046
PORT=18046
C=/mnt/d/research/OSWorld/evaluation_examples
META=$C/verified_eval100_nonproxy.json
GRP=qwen35-9b-sft
KEY=$($KSSH "cat $KB/.vllm_api_key")
echo "=========== [$(date '+%F %T')] lr 变体 eval 链启动 ==========="

# arm|语料说明|配方说明
ARMS="
lr2e5|v16 + v11new (866 traj / 18,576 samples)|Qwen3.5-9B full FT, lr 2e-5, gb 64, 1 epoch, wd 0.1, beta2 0.95, img10/fold1
lr2e5gb128|v16 + v11new (866 traj / 18,576 samples)|Qwen3.5-9B full FT, lr 2e-5, gb 128 (accum 16), 1 epoch, wd 0.1, beta2 0.95, img10/fold1
lr1e5|v16 + v11new (866 traj / 18,576 samples)|Qwen3.5-9B full FT, lr 1e-5, gb 64, 1 epoch, wd 0.1, beta2 0.95, img10/fold1
lr1e5b999|v16 + v11new (866 traj / 18,576 samples)|Qwen3.5-9B full FT, lr 1e-5, gb 64, 1 epoch, wd 0.0, beta2 0.999, img10/fold1
"

up(){ [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $KEY" \
        http://127.0.0.1:$PORT/v1/models)" = "200" ]; }

# 必须按**行**读。`for row in $ARMS` 是按任意空白分词的,而表格里的语料说明
# 含空格(v16-main + v16-pilot ...),于是第一行之后每个空格碎片都被当成一行,
# 臂名变成 "+" —— 2026-09-01 01:48 实测到这个症状。
while IFS= read -r row; do
  [ -z "$row" ] && continue
  case "$row" in *"|"*) : ;; *) continue;; esac
  ARM=$(echo $row|cut -d'|' -f1); CORP=$(echo $row|cut -d'|' -f2); RECIPE=$(echo $row|cut -d'|' -f3)
  MN=$ARM-stock
  echo "--- [$(date '+%F %T')] $ARM ---"

  # 1) 等 prep_lr 把权重推好并写下标记(标记内容 = 权重绝对路径)
  W=""
  for i in $(seq 1 2880); do
    W=$($KSSH "cat $KB/READY_$ARM 2>/dev/null" | tr -d ' \r\n')
    [ -n "$W" ] && break
    sleep 30
  done
  [ -n "$W" ] || { echo "[$(date '+%F %T')] $ARM 24h 没等到 READY,跳过"; continue; }
  echo "[$(date '+%F %T')] $ARM 权重=$W"

  # 2) 等 3 台 VM。看 runner + 另一条链,只看 runner 会在两趟重试之间误判。
  for i in $(seq 1 5760); do
    ps -eo args | grep -q "[r]un_multienv_qwen"  && { sleep 30; continue; }
    ps -eo args | grep -q "[c]hain_eval_rest"    && { sleep 30; continue; }
    break
  done
  echo "[$(date '+%F %T')] $ARM VM 空出来了"; sleep 20

  # 3) 腾占位:先杀掉该占位上的旧 job step(上一臂的 serve)。一张 A100 装不下两个 9B。
  OLD=$($KSSH "squeue -s -j $PH -h -o %i 2>/dev/null" | tr -d ' ')
  if [ -n "$OLD" ]; then
    echo "[$(date '+%F %T')] 释放占位 $PH 上的旧 step: $OLD"
    for s in $OLD; do $KSSH "scancel $s"; done
    sleep 25
  fi

  # 4) 起本臂的 serve
  cat > /tmp/launch_$ARM.sh <<EOS
cd $KB && setsid srun --overlap --jobid=$PH bash $KB/serve_inner_generic.sh "$W" "$MN" $RPORT \
  </dev/null > $KB/srv_${ARM}_inner.log 2>&1 &
sleep 8
head -3 $KB/srv_${ARM}_inner.log
EOS
  ssh -S "$KS" -o ControlMaster=no -o BatchMode=yes "$KH" 'bash -s' < /tmp/launch_$ARM.sh
  ssh -S "$KS" -O cancel -L $PORT:$NODE:$RPORT "$KH" 2>/dev/null
  ssh -S "$KS" -O forward -L $PORT:$NODE:$RPORT "$KH"
  for i in $(seq 1 120); do up && break; sleep 20; done
  up || { echo "[$(date '+%F %T')] $ARM FATAL: 端点没起来"; continue; }

  # 5) 服务端自报加载了什么。名字对不等于权重对 —— 这一条是路径校验。
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

  R=$(ls -dt /mnt/d/research/OSWorld/results_generated/$GRP/eval50-$ARM-* 2>/dev/null | head -1)
  [ -n "$R" ] || R=/mnt/d/research/OSWorld/results_generated/$GRP/eval50-$ARM-$(date +%Y%m%d)
  mkdir -p "$R"; TAG=$(basename "$R")

  python3 - "$R/MODEL_BOUNDARY.json" "$ARM" "$MN" "$ROOT" "$CORP" "$RECIPE" <<'PY'
import json, sys
p, arm, served, root, corpus, recipe = sys.argv[1:7]
json.dump({"arm": arm, "served_model_name": served, "weights_reported_by_vllm": root,
  "corpus": corpus, "train_recipe": recipe,
  "cluster": "klone gpu-a100 (NVIDIA A100 80GB PCIe, sm_80) inside placeholder job 39306243 on g3085",
  "runtime": "apptainer, vllm/vllm-openai:v0.25.1 -- same build as tillicum",
  "chat_template": "model built-in (OSWorld-Verified default); no override",
  "precision": "BF16 weights, kv-cache auto (NOT fp8: sm_80 lacks fp8)",
  "sampling": {"temperature":1.0,"top_p":0.95,"top_k":20,"min_p":0.0,
               "presence_penalty":0.0,"repetition_penalty":1.0},
  "max_steps": 50, "sleep_after_execution": 3, "num_envs": 3,
  "image_window": "--image_max 10 --fold_size 1 (MATCHES the training window)",
  "recording": "disabled via OSTG_NO_RECORD=1",
  "tasks": "verified_eval100_nonproxy.json (the whole frozen 100 = eval50 + eval50b)",
  "harness": "OSTG_TYPE_NO_SPLIT=1 (multi-line type sent as ONE typewrite, kC-onward semantics)",
  "backbone_warning": "9B -- compare against the 9B base, NEVER against the 4B arms"},
  open(p,"w"), indent=1, ensure_ascii=False)
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

  # ---- 卡死看门狗(2026-09-01,一次 31 分钟的单题黑洞换来的) ----
  # 生产脚本 run_eval50_stock.sh 的看门狗只防"serve 死了"(端点连续 3 分钟不通)。
  # 它防不住这次的形态:端点 HTTP 200、runner 活着、另外两道题正常推进,**只有
  # 一道题的请求在 ssh 隧道里进了黑洞** —— 客户端那侧 socket 是 ESTAB,vLLM 那侧
  # 从没收到(serve 一直只报 Running: 2 reqs,而有 3 个 env)。客户端不停重试、
  # 不停被对端关闭,堆到 10 个 CLOSE-WAIT,而 OSWORLD_OPENAI_TIMEOUT=1800 让它
  # 每次都要空等 30 分钟。
  #
  # 所以判据必须是**单题卡死**而不是全局静默:全局最新 traj 很新(别的题在动),
  # 但某一道有 traj 无 result 的题超过 STALL_MIN 分钟没写过 —— 那道就是楔死了。
  # 杀掉 runner,外层 for TRY 循环会重起,skip-scored 跳过已出分的。
  STALL_MIN=35     # > OSWORLD_OPENAI_TIMEOUT(1800s=30min) + 余量,不误杀长生成
  ( while ps -eo args | grep -q "[r]un_multienv_qwen.*$TAG"; do
      sleep 120
      now=$(date +%s)
      # 限深:traj.jsonl 固定在 $R/<域>/<task_id>/ 第 3 层。不限深会走遍全树
      # (含每道题最多 50 张截图),而 /mnt/d 是 drvfs,元数据操作本来就慢。
      # 实测两种写法结果一致(52/52),各 0.127s;规模涨上去差距才显出来。
      newest=$(find "$R" -mindepth 3 -maxdepth 3 -name traj.jsonl -printf "%T@\n" 2>/dev/null | sort -rn | head -1 | cut -d. -f1)
      [ -z "$newest" ] && continue
      # 别的题还在动吗(全局最新 5 分钟内)
      [ $(( now - newest )) -gt 300 ] && continue
      wedged=""
      for t in $(find "$R" -mindepth 2 -maxdepth 2 -type d 2>/dev/null); do
        [ -f "$t/traj.jsonl" ] || continue
        [ -f "$t/result.txt" ] && continue
        m=$(stat -c %Y "$t/traj.jsonl" 2>/dev/null) || continue
        age=$(( (now - m) / 60 ))
        [ "$age" -ge "$STALL_MIN" ] && wedged="$wedged $(basename $t | cut -c1-8)($age min)"
      done
      if [ -n "$wedged" ]; then
        echo "[$(date '+%F %T')] $ARM 单题卡死:$wedged —— 别的题仍在动,判为隧道黑洞。杀 runner 让重试循环接管"
        ssh -S "$KS" -O cancel -L $PORT:$NODE:$RPORT "$KH" 2>/dev/null
        ssh -S "$KS" -O forward -L $PORT:$NODE:$RPORT "$KH" 2>/dev/null
        for p in $(ps -eo pid,args | grep "run_multienv_qwen" | grep "$TAG" | grep -v grep | awk '{print $1}'); do kill $p 2>/dev/null; done
        # 杀 runner 会让在飞的题以 "can only test a child process" 崩掉,而
        # **harness 会给它们写 result.txt=0** —— skip-scored 从此永远跳过,假 0 分
        # 就永久留在分数里。2026-09-01 实测:我手工杀一次污染了 2 道;翻历史发现
        # a6v(2 道)、a7(1 道)在 2026-08-23 已经中过同一招,那两个已发布的分数
        # 各含假 0。所以杀完必须自己收拾。改名不删,证据留着。
        sleep 15
        for hf in $(grep -rl "can only test a child process" "$R"/*/*/harness_error.json 2>/dev/null); do
          hd=$(dirname "$hf")
          [ -f "$hd/result.txt" ] || continue
          mv "$hd/result.txt" "$hd/result.txt.poisoned-by-watchdog-$(date +%Y%m%d%H%M)"
          mv "$hf" "$hf.poisoned-by-watchdog-$(date +%Y%m%d%H%M)"
          echo "[$(date '+%F %T')] 隔离被杀污染的假 0 分: $(basename $(dirname $hd))/$(basename $hd | cut -c1-8)"
        done
        break
      fi
    done ) &
  GUARD=$!
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
    kill $GUARD 2>/dev/null
    for p in $(ps -eo pid,args | grep "run_multienv_qwen" | grep "$TAG" | grep -v grep | awk '{print $1}'); do kill $p 2>/dev/null; done
    sleep 10
  done
  N=$(find "$R" -name result.txt 2>/dev/null | wc -l)
  echo "[$(date '+%F %T')] === $ARM RESULT $N/$T: $(find "$R" -name result.txt -exec cat {} \; 2>/dev/null | sort | uniq -c | tr '\n' ' ')"
done <<EOF
$ARMS
EOF
echo "=========== $(date '+%F %T')] lr 变体 eval 链结束 ==========="
