#!/bin/bash
#SBATCH --job-name=sft-q38e1B
#SBATCH --account=video
#SBATCH --partition=gpu-h200
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --gpus=2
#SBATCH --cpus-per-gpu=8
#SBATCH --mem=300G
#SBATCH --time=10:00:00
#SBATCH --output=/gpfs/scrubbed/jy050706/sft/sft_q38e1B_%j.out
# Arm B, dedicated 1-epoch run: same corpus and parallelism as sft-q38B
# (v11-100 + v11-500, 312 trajs / 5,659 samples, 2x H200 DP, global batch 8);
# the ONLY delta is num_train_epochs=1, so the LR anneals to zero within one
# epoch. This is a true 1-epoch model, not the e3 run's mid-schedule ep1
# snapshot -- the pair separates "less training" from "unfinished schedule".
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
REPORT=none; RUN_NAME=q38e1B-${SLURM_JOB_ID}
if [ -f "$B/wandb.env" ]; then set +x; source "$B/wandb.env"; set -x
  export WANDB_PROJECT="${WANDB_PROJECT:-cua-sft}"; REPORT=wandb; fi
export WANDB_NOTES="q38 teacher, B=v11100+v11500, 312 trajs/5659 samples, 1ep full anneal, 2xH200 global-batch 8"
PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True' \
IMAGE_MAX_TOKEN_NUM=2048 \
NPROC_PER_NODE=2 \
swift sft \
  --model $B/models/Qwen3.5-4B \
  --dataset $DS1/train_swift.jsonl $DS2/train_swift.jsonl \
  --enable_channel_loss true \
  --tuner_type full --loss_scale last_round --gradient_accumulation_steps 4 \
  --preserve_thinking true \
  --attn_impl sdpa --deepspeed zero2_offload \
  --torch_dtype bfloat16 \
  --num_train_epochs 1 --per_device_train_batch_size 1 \
  --learning_rate 1e-5 --warmup_ratio 0.05 \
  --max_length 65536 --gradient_checkpointing true \
  --save_strategy epoch --save_total_limit 2 \
  --logging_steps 4 \
  --report_to $REPORT --run_name $RUN_NAME \
  --output_dir $B/out/q38e1B
echo "EXIT_q38e1B $?"
