#!/bin/bash
#SBATCH --job-name=vt-b9l
#SBATCH --account=video
#SBATCH --partition=gpu-h200
#SBATCH --qos=normal
#SBATCH --nodes=4
#SBATCH --gpus-per-node=2
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=400G
#SBATCH --time=1-00:00:00
#SBATCH --exclude=g006,g012,g018
#SBATCH --output=/gpfs/scrubbed/jy050706/sft/mixB_9b_lr1e5_%j.out
# 臂 B 的高学习率单轮变体 —— lr 2e-5 / 1 epoch(2026-08-31 加,用户点名)
#
# 与 mixB-9b.sbatch 的四处差别(全部由用户点名):
#   learning_rate   3e-6  -> 1e-5   (3.3x)
#   num_train_epochs   3  -> 1
#   adam_beta2     0.999  -> 0.95
#   weight_decay     0.0  -> 0.1
# 语料、拓扑、图窗、loss_scale、accum、max_length 全部不动,
# 所以它跟原臂 B 是同一份数据上的**配方对照**,不是新语料。
#
# 这四处是自洽的一套:大 lr 配短二阶动量窗口(beta2 0.95 的有效窗口约 20 步,
# 0.999 约 1000 步)让二阶矩跟得上快速变化的梯度尺度;wd 0.1 压住大步长下的
# 权重漂移。GPT-3 / LLaMA 系列用的就是 beta2 0.95 + wd 0.1 这一组。
# 注意 HF Trainer 的 weight_decay 不施加在 bias 和 LayerNorm 权重上(默认分组)。
#
# 这一版把学习率阶梯补齐。同语料、同 1 epoch、同 beta2/wd 下:
#   3e-6  = 原臂 B 的 lr(但那臂是 3 epoch,不是单变量对照)
#   1e-5  = **本臂**;也正是 OpenWebRL 发布配方用的 lr
#   2e-5  = mixB-9b-lr2e5-1ep.sbatch
# 与 2e-5 那版是**严格单变量对照**:只有 learning_rate 不同,accum 仍是 8。
# 梯度裁剪走 HF 默认 max_grad_norm=1.0(deepspeed 里 gradient_clipping=auto
# 由它填)。注意裁剪不会抵消 lr:它把梯度归一化到范数 1,步长仍然是 lr x 1,
# 所以 lr 之比就是步长之比。
#
# 独立 OUT(out/mixB-9b-lr2e5-1ep),不与 3e-6 的产物同目录,免得评测时取错点。
# 291 步(18,576/64 上取整);save_steps 97,一轮存 3 个点。
# --exclude:g006/g012 各崩过一次(mha_graph.execute + cudaErrorContained),
# g018 已 DOWN+DRAIN。排掉不改训练语义,只是躲开坏节点。

# 臂 B —— v16 新数据 + v11 新 rollout(08-29 i10x 重跑)
#
# 语料 = v16 判官准入 554 条 + v11 新批(i10x 重跑) 312 条 = 866 条轨迹
# 图窗 img10 / fold_size 1 —— 这是**建语料时**定死的(build.py --image-max 10
# --fold-size 1),sbatch 里没有对应参数,只有 IMAGE_MAX_TOKEN_NUM=2048 是训练侧。
#
# 拓扑 4 节点 × 2 卡 × accum 8 = 全局 batch 64,与臂 A 完全同形。
#   4B @ img10 峰值  89.66 GiB (64.1%)
#   9B @ img10 峰值 115.80 GiB (82.8%)   ← 余 24 GiB
# 曾试过 2 节点 × 8 卡(实测更省显存、墙钟约减半),但它要求两个节点各 8 张全空,
# 集群里同时满足的节点常常只有一个,反而排不上队 —— 2026-08-30 实测排在
# Resources/Priority 上不动。4x2 只要每节点 2 张空即可,秒上。
#
# 两臂的唯一变量是 v11 用哪一批 rollout;v16 那 554 条两臂共用。
umask 077
set -x
B=/gpfs/scrubbed/jy050706/sft

# ---- 语料(按 ship 时的目录名填;每份都要有 train_swift_abs.jsonl(图片是 /gpfs 绝对路径)) --------------
DS_V16MAIN=$B/data/v16-main
DS_V16PILOT=$B/data/v16-pilot
DS_V11NEW500=$B/data/v11new-500
DS_V11NEWALL=$B/data/v11new-all
DSLIST="$DS_V16MAIN $DS_V16PILOT $DS_V11NEW500 $DS_V11NEWALL"

# ---- 防撞自检:同一 OUT 里不许混进别的语料训出的产物 -----------------------
OUT=$B/out/mixB-9b-lr1e5-1ep
for _a in "$OUT"/*/args.json; do
  [ -e "$_a" ] || continue
  grep -q "v11new-500" "$_a" || {
    echo "FATAL: $OUT 里已有别的语料训出的产物: $_a" >&2
    echo "       换 OUT,或把旧产物移走。拒绝启动以免口径混淆。" >&2
    exit 1; }
done
mkdir -p "$OUT" && echo "$DSLIST" > "$OUT/CORPUS.txt"

export PATH="$HOME/.local/bin:$PATH"
cd $B/runcwd && source $B/venv/bin/activate
export CUDA_HOME=$B/cuda13 PATH="$B/cuda13/bin:$PATH"
export LD_LIBRARY_PATH="$B/cuda13/lib64:$B/cuda13/lib:${LD_LIBRARY_PATH:-}"
export NCCL_P2P_DISABLE=1
export PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True'
export IMAGE_MAX_TOKEN_NUM=2048

# ---- 预检:每张图逐条 stat,不通过就在烧 GPU 之前退出 -----------------------
# 不验的失败模式是**静默地只拿文本训练**,不报错(DATA_PIPELINE.md 静默失效那节)。
for DS in $DSLIST; do
python - "$DS" <<'PY' || { echo "PREFLIGHT FAILED — aborting"; exit 1; }
import json, os, sys
ds = sys.argv[1]; bad = tot = 0
for line in open(os.path.join(ds, "train_swift_abs.jsonl"), encoding="utf-8"):
    if not line.strip(): continue
    for p in json.loads(line).get("images", []):
        tot += 1
        if not os.path.isabs(p) or not os.path.exists(p):
            bad += 1
            if bad < 4: print("UNRESOLVED:", p)
print(f"preflight {ds}: {tot} image refs, {bad} unresolved")
sys.exit(1 if bad else 0)
PY
done

# ---- 步数算术:save_steps 必须整除 steps/epoch,否则 checkpoint 落不在 -------
# epoch 边界上,save_total_limit 轮转会丢早期点。算完打进日志(TRAINING.md 立规)。
eval "$(python - $DSLIST <<'PY'
import sys
n = 0
for ds in sys.argv[1:]:
    n += sum(1 for line in open(ds + "/train_swift_abs.jsonl", encoding="utf-8") if line.strip())
GB = 64                      # 8 rank x accum 8
spe = -(-n // GB)            # steps per epoch, 向上取整
for d in (3, 2, 1):          # 尽量一个 epoch 存 3 次,退而求其次
    if spe % d == 0:
        save = spe // d
        break
print(f"SAMPLES={n}")
print(f"STEPS_PER_EPOCH={spe}")
print(f"SAVE_STEPS={save}")
print(f"TOTAL_STEPS={spe}")   # 1 epoch
PY
)"
echo ">>> 样本 $SAMPLES | steps/epoch $STEPS_PER_EPOCH | save_steps $SAVE_STEPS | 总步 $TOTAL_STEPS"
[ -n "$SAVE_STEPS" ] || { echo "FATAL: 步数算术失败"; exit 1; }

REPORT=none; RUN_NAME=mixB-9b-lr1e5-1ep-${SLURM_JOB_ID}
if [ -f "$B/wandb.env" ]; then set +x; source "$B/wandb.env"; set -x
  export WANDB_PROJECT="${WANDB_PROJECT:-cua-sft}"; REPORT=wandb; fi
export WANDB_NOTES="臂 B 学习率阶梯的中档:lr 1e-5 / 1 epoch / global batch 64(4x2xaccum8)。与 lr2e-5 那版唯一差别就是学习率减半。语料同原臂 B(866 条),img10/fold1。"
export B DSLIST REPORT RUN_NAME OUT SAVE_STEPS
export MASTER_ADDR=$(scontrol show hostnames "$SLURM_JOB_NODELIST" | head -n1)
export MASTER_PORT=$((20000 + SLURM_JOB_ID % 9000))   # 写死端口在共享节点必撞
export NNODES=4 NPROC_PER_NODE=2
echo ">>> multinode: nodes=$SLURM_JOB_NODELIST master=$MASTER_ADDR port=$MASTER_PORT"
srun --ntasks=4 --ntasks-per-node=1 --kill-on-bad-exit=1 bash -c '
  export NODE_RANK=$SLURM_NODEID
  echo ">>> node $SLURM_NODEID ($(hostname)) launching NPROC=$NPROC_PER_NODE"
  DS_ARGS=""; for d in $DSLIST; do DS_ARGS="$DS_ARGS $d/train_swift_abs.jsonl"; done
  swift sft \
    --model $B/models/Qwen3.5-9B \
    --dataset $DS_ARGS \
    --enable_channel_loss true \
    --tuner_type full --loss_scale last_round --gradient_accumulation_steps 8 \
    --preserve_thinking true \
    --attn_impl sdpa --deepspeed zero2_offload \
    --torch_dtype bfloat16 \
    --num_train_epochs 1 --per_device_train_batch_size 1 \
    --learning_rate 1e-5 --warmup_ratio 0.1 \
    --weight_decay 0.1 --adam_beta2 0.95 \
    --max_length 81920 --gradient_checkpointing true \
    --save_strategy steps --save_steps $SAVE_STEPS --save_total_limit 12 \
    --logging_steps 1 \
    --report_to $REPORT --run_name $RUN_NAME \
    --output_dir $OUT
'
echo "EXIT_mixB_9b $?"
