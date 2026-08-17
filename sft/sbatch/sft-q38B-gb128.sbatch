#!/bin/bash
#SBATCH --job-name=sft-q38B-gb128
#SBATCH --account=video
#SBATCH --partition=gpu-h200
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --gpus=8
#SBATCH --cpus-per-gpu=8
#SBATCH --mem=600G
#SBATCH --time=08:00:00
#SBATCH --output=/gpfs/scrubbed/jy050706/sft/sft_q38B_gb128_%j.out
# Arm B-gb128: same B corpus (v11-100 + v11-500, 312 trajs / 5,659 samples),
# OpenWebRL's optimization regime (paper A.5, verified 2026-08-16): global
# batch 128 across 8 data-parallel workers (here 8x H200, per-device 1 x
# accum 16), cosine LR with 10% warmup, 3 epochs -> ~44 optimizer steps per
# epoch, ~133 total (vs sft-q38B's 2,124 at global batch 8, warmup 0.05).
# Question under test: does the optimization regime change the SFT delta on
# OUR corpus, holding data constant. lr/loss/render all unchanged from B.
umask 077
set -x
B=/gpfs/scrubbed/jy050706/sft
DS1=$B/data/q38e3B-v11100
DS2=$B/data/q38e3B-v11500
export PATH="$HOME/.local/bin:$PATH"
cd $B/runcwd && source $B/venv/bin/activate
export CUDA_HOME=$B/cuda13 PATH="$B/cuda13/bin:$PATH"
export LD_LIBRARY_PATH="$B/cuda13/lib64:$B/cuda13/lib:${LD_LIBRARY_PATH:-}"
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
export WANDB_NOTES="q38 teacher, B=v11100+v11500, 3ep, OpenWebRL regime: global batch 128 (8xH200 x accum16), cosine warmup 0.1"
PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True' \
IMAGE_MAX_TOKEN_NUM=2048 \
NPROC_PER_NODE=8 \
swift sft \
  --model $B/models/Qwen3.5-4B \
  --dataset $DS1/train_swift.jsonl $DS2/train_swift.jsonl \
  --enable_channel_loss true \
  --tuner_type full --loss_scale last_round --gradient_accumulation_steps 16 \
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
echo "EXIT_q38e3B_gb128 $?"
