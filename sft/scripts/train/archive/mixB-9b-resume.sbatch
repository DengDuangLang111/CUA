#!/bin/bash
#SBATCH --job-name=vt-b9br
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
#SBATCH --output=/gpfs/scrubbed/jy050706/sft/mixB_9b_r_%j.out
# 臂 B(9B)续跑 —— 269047 在 step 857/873(epoch 2.944,离终点 20 分钟)
# 因 g006 的 GPU 故障中断,从 checkpoint-776 接上。
#
# 中断根因(2026-08-31 14:20:14,g006),与 A-9B 那次逐字相同:
#   [rank5] RuntimeError: Expected mha_graph.execute(...).is_good() to be true
#   [rank4] CUDA error: Invalid access of peer GPU memory over nvlink
#           or a hardware error  (cudaErrorContained)
#
# 判为节点故障而非算子/显存,依据三条:
#   (a) A-9B 上次崩在 g012、mem 121.2;换掉 g012 后**用同样的 sdpa、同样的
#       显存水位**已平安跑了 8 小时 —— 变量只有节点;
#   (b) C-9B 全程 136.7 GiB(97%)完训,比本次崩溃时的 135.6 还高,
#       显存不是致命线;
#   (c) 同分区 g018 至今 DOWN+DRAIN,理由 "GPU error : Not responding" ——
#       这批卡本来就在掉。
# 因此**不动 --attn_impl sdpa**:换算子会让本臂与 A/C 走不同数值路径。
# 只 --exclude 掉三台出过事的:g006(本次)、g012(A-9B 那次)、g018(已 drain)。
# 若换节点仍崩同样的错,才说明判断错了,那时再考虑 TORCH_CUDNN_SDPA_ENABLED=0。
#
# 剩 873-776=97 步 x 71.7 s/it 约 1.9 h,墙钟 24 h。
# --resume_only_model 默认 false = 连优化器状态和数据顺序一起恢复。

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
OUT=$B/out/mixB-9b
CKPT=$B/out/mixB-9b/v0-20260830-211404/checkpoint-776
[ -d "$CKPT/global_step776" ] || { echo "FATAL: 续跑点不完整 $CKPT"; exit 1; }
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
print(f"TOTAL_STEPS={spe*3}")
PY
)"
echo ">>> 样本 $SAMPLES | steps/epoch $STEPS_PER_EPOCH | save_steps $SAVE_STEPS | 总步 $TOTAL_STEPS"
[ -n "$SAVE_STEPS" ] || { echo "FATAL: 步数算术失败"; exit 1; }

REPORT=none; RUN_NAME=mixB-9b-resume-${SLURM_JOB_ID}
if [ -f "$B/wandb.env" ]; then set +x; source "$B/wandb.env"; set -x
  export WANDB_PROJECT="${WANDB_PROJECT:-cua-sft}"; REPORT=wandb; fi
export WANDB_NOTES="臂 B —— v16 新数据 + v11 新 rollout(08-29 i10x 重跑)。img10/fold1,4x2/accum8,global batch 64,3ep。"
export B DSLIST REPORT RUN_NAME OUT SAVE_STEPS CKPT
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
    --num_train_epochs 3 --per_device_train_batch_size 1 \
    --learning_rate 3e-6 --warmup_ratio 0.1 \
    --weight_decay 0.0 --adam_beta2 0.999 \
    --max_length 81920 --gradient_checkpointing true \
    --save_strategy steps --save_steps $SAVE_STEPS --save_total_limit 12 \
    --logging_steps 1 \
    --report_to $REPORT --run_name $RUN_NAME \
    --output_dir $OUT \
    --resume_from_checkpoint $CKPT
'
echo "EXIT_mixB_9b $?"
