#!/bin/bash
#SBATCH --job-name=vt-a9br
#SBATCH --account=video
#SBATCH --partition=gpu-h200
#SBATCH --qos=normal
#SBATCH --nodes=4
#SBATCH --gpus-per-node=2
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=400G
#SBATCH --time=1-00:00:00
#SBATCH --exclude=g012
#SBATCH --output=/gpfs/scrubbed/jy050706/sft/mixA_9b_r_%j.out
# 臂 A(9B)续跑 —— 269057 在 step 443/930 因 GPU 故障中断后从 checkpoint-311 接上
#
# 中断根因(2026-08-31 06:24:49,g012):
#   [rank5] RuntimeError: Expected mha_graph.execute(...).is_good() to be true
#           —— 在 backward 的梯度重算里,cuDNN 融合注意力执行失败
#   [rank4] CUDA error: Invalid access of peer GPU memory over nvlink
#           or a hardware error  (cudaErrorContained)
# 判为硬件而非数据/配置,依据三条:
#   (a) 崩在 epoch 2 第 132 步,同一条样本 epoch 1 已成功跑过(micro-batch=1);
#   (b) 同分区 g018 已 drained,理由 "GPU error : Not responding";
#   (c) 显存 113.9/141 GiB,grad_norm 2.4-3.0,无 nan —— 不是 OOM 也不是发散。
# 因此**不动 --attn_impl sdpa**:换算子会让本臂与 B/C 用不同数值路径,毁掉三臂可比性。
# 只 --exclude=g012 躲开故障节点。若换节点仍崩同样的错,才说明判断错了,
# 那时再考虑 TORCH_CUDNN_SDPA_ENABLED=0 关掉 cuDNN 后端(并对 B/C 同步)。
#
# 剩 930-311=619 步 x 72.5 s/it 约 12.5 h,墙钟 24 h。
# --resume_only_model 保持默认 false = 连优化器状态和数据顺序一起恢复;
# load_args 在训练模式下默认 False(base_args.py:69/:102),checkpoint 里的
# args.json 不会覆盖下面的命令行,配置仍以本脚本为准。

# 臂 A —— v16 新数据 + v11 旧语料(已训过、效果已知的那 360 条)
#
# 语料 = v16 判官准入 554 条 + v11 旧批(0814 rollout) 360 条 = 914 条轨迹
# 图窗 img10 / fold_size 1 —— 这是**建语料时**定死的(build.py --image-max 10
# --fold-size 1),sbatch 里没有对应参数,只有 IMAGE_MAX_TOKEN_NUM=2048 是训练侧。
#
# 拓扑 4 节点 × 2 卡 × accum 8 = 全局 batch 64。这是 a1/a2/a3 实测过的形状:
#   4B @ img10 峰值  89.66 GiB (64.1%)
#   9B @ img10 峰值 115.80 GiB (82.8%)   ← 余 24 GiB
# 不要改成 2 节点 × 8 卡:那是 smoke 的形状,显存数字与上面不可比。
#
# 两臂的唯一变量是 v11 用哪一批 rollout;v16 那 554 条两臂共用。
umask 077
set -x
B=/gpfs/scrubbed/jy050706/sft

# ---- 语料(按 ship 时的目录名填;每份都要有 train_swift_abs.jsonl(图片是 /gpfs 绝对路径)) --------------
DS_V16MAIN=$B/data/v16-main
DS_V16PILOT=$B/data/v16-pilot
DS_V11OLD100=$B/data/q38-Bhqs2t-r5nocapimg10-v11100
DS_V11OLD500=$B/data/q38-Bhqs2t-r5nocapimg10-v11500
DSLIST="$DS_V16MAIN $DS_V16PILOT $DS_V11OLD100 $DS_V11OLD500"

# ---- 防撞自检:同一 OUT 里不许混进别的语料训出的产物 -----------------------
OUT=$B/out/mixA-9b
CKPT=$B/out/mixA-9b/v1-20260830-212630/checkpoint-311
[ -d "$CKPT/global_step311" ] || { echo "FATAL: 续跑点不完整 $CKPT"; exit 1; }
for _a in "$OUT"/*/args.json; do
  [ -e "$_a" ] || continue
  grep -q "r5nocapimg10-v11500" "$_a" || {
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

REPORT=none; RUN_NAME=mixA-9b-resume-${SLURM_JOB_ID}
if [ -f "$B/wandb.env" ]; then set +x; source "$B/wandb.env"; set -x
  export WANDB_PROJECT="${WANDB_PROJECT:-cua-sft}"; REPORT=wandb; fi
export WANDB_NOTES="臂 A —— v16 新数据 + v11 旧语料(已训过、效果已知的那 360 条)。img10/fold1,4x2/accum8,global batch 64,3ep。"
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
echo "EXIT_mixA_9b $?"
