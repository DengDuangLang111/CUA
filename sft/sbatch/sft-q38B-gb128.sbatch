#!/bin/bash
#SBATCH --job-name=sft-q38B-gb128
#SBATCH --account=video
#SBATCH --partition=gpu-h200
#SBATCH --qos=normal
#SBATCH --nodes=2
#SBATCH --gpus-per-node=8
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=64
#SBATCH --mem=600G
#SBATCH --time=06:00:00
#SBATCH --output=/gpfs/scrubbed/jy050706/sft/sft_q38B_gb128_%j.out
# Arm B-gb128, ATTEMPT 8: 16x H200 across 2 nodes, per-device batch 1,
# accum 8 -> global batch 128 (exact OpenWebRL A.5 replication), 3 epochs.
# Why this shape: seven single-node attempts established two hard laws --
#   (1) per-device batch is pinned at 1 (one 65k-token/20-image sample's
#       activations + response-logits already sit at ~131 GiB of 139.79);
#   (2) memory grows ~250 MB per accumulated micro-batch (ms-swift external
#       last_round loss path retains per-microbatch logits until the
#       boundary; upstream issue #5230 family; invariant to ZeRO stage,
#       channel_loss, width). accum 4 proven (B jobs), accum 8 proven on
#       arm A (450 steps); accum >=16 dies at 137-139.
# So global 128 = 16 ranks x 8 accum is the only lawful factorization.
# NCCL_P2P_DISABLE kept (free, measured); cross-node traffic rides IB.
umask 077
set -x
B=/gpfs/scrubbed/jy050706/sft
DS1=$B/data/q38e3B-v11100
DS2=$B/data/q38e3B-v11500
export PATH="$HOME/.local/bin:$PATH"
cd $B/runcwd && source $B/venv/bin/activate
export CUDA_HOME=$B/cuda13 PATH="$B/cuda13/bin:$PATH"
export LD_LIBRARY_PATH="$B/cuda13/lib64:$B/cuda13/lib:${LD_LIBRARY_PATH:-}"
export NCCL_P2P_DISABLE=1
export PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True'
export IMAGE_MAX_TOKEN_NUM=2048
for DS in $DS1 $DS2; do
python - "$DS" <<'PY' || { echo "PREFLIGHT FAILED — aborting"; exit 1; }
import json, os, sys
ds = sys.argv[1]; bad = tot = 0
for line in open(os.path.join(ds, "train_swift.jsonl"), encoding="utf-8"):
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
REPORT=none; RUN_NAME=q38e3B-gb128-${SLURM_JOB_ID}
if [ -f "$B/wandb.env" ]; then set +x; source "$B/wandb.env"; set -x
  export WANDB_PROJECT="${WANDB_PROJECT:-cua-sft}"; REPORT=wandb; fi
export WANDB_NOTES="q38 teacher, B=v11100+v11500, 3ep, OpenWebRL regime: global batch 128 = 16xH200 (2 nodes) x accum 8, cosine warmup 0.1"
export B DS1 DS2 REPORT RUN_NAME
export MASTER_ADDR=$(scontrol show hostnames "$SLURM_JOB_NODELIST" | head -n1)
export MASTER_PORT=29500 NNODES=2 NPROC_PER_NODE=8
echo ">>> multinode: nodes=$SLURM_JOB_NODELIST master=$MASTER_ADDR"
srun --ntasks=2 --ntasks-per-node=1 --kill-on-bad-exit=1 bash -c '
  export NODE_RANK=$SLURM_NODEID
  echo ">>> node $SLURM_NODEID ($(hostname)) launching NPROC=8"
  swift sft \
    --model $B/models/Qwen3.5-4B \
    --dataset $DS1/train_swift.jsonl $DS2/train_swift.jsonl \
    --enable_channel_loss true \
    --tuner_type full --loss_scale last_round --gradient_accumulation_steps 8 \
    --preserve_thinking true \
    --attn_impl sdpa --deepspeed zero2_offload \
    --torch_dtype bfloat16 \
    --num_train_epochs 3 --per_device_train_batch_size 1 \
    --learning_rate 1e-5 --warmup_ratio 0.1 \
    --max_length 65536 --gradient_checkpointing true \
    --save_strategy epoch --save_total_limit 4 \
    --logging_steps 2 \
    --report_to $REPORT --run_name $RUN_NAME \
    --output_dir $B/out/q38e3B-gb128
'
echo "EXIT_q38e3B_gb128 $?"
