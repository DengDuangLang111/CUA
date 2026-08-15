#!/bin/bash
#SBATCH --job-name=sft-q38lean
#SBATCH --account=video
#SBATCH --partition=gpu-h200
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --gpus=1
#SBATCH --cpus-per-gpu=8
#SBATCH --mem=220G
#SBATCH --time=09:00:00
#SBATCH --output=/gpfs/scrubbed/jy050706/sft/sft_q38lean_%j.out
# Arm A: teacher = Qwen3.8-27B on v11-100 (69 perfect trajectories, zero
# filter losses). Recipe = e3 UNCHANGED (3 epochs, preserve_thinking true,
# lr 1e-5, last-round loss); the only variable vs every q35-* arm is the DATA.
# No val split by user decision -- evaluation is verified_eval50_nonproxy.
umask 077
set -x
B=/gpfs/scrubbed/jy050706/sft
DS=$B/data/q38-v11100
export PATH="$HOME/.local/bin:$PATH"
cd $B/runcwd && source $B/venv/bin/activate
export CUDA_HOME=$B/cuda13 PATH="$B/cuda13/bin:$PATH"
export LD_LIBRARY_PATH="$B/cuda13/lib64:$B/cuda13/lib:${LD_LIBRARY_PATH:-}"
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
print(f"preflight: {tot} image refs, {bad} unresolved")
sys.exit(1 if bad else 0)
PY
REPORT=none; RUN_NAME=q38e3-lean-${SLURM_JOB_ID}
if [ -f "$B/wandb.env" ]; then set +x; source "$B/wandb.env"; set -x
  export WANDB_PROJECT="${WANDB_PROJECT:-cua-sft}"; REPORT=wandb; fi
export WANDB_NOTES="q38 teacher, v11-100, 69 trajs, 3ep, preserve_thinking=false"
PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True' \
IMAGE_MAX_TOKEN_NUM=2048 \
NPROC_PER_NODE=1 \
swift sft \
  --model $B/models/Qwen3.5-4B \
  --dataset $DS/train_swift.jsonl \
  --enable_channel_loss true \
  --tuner_type full --loss_scale last_round --gradient_accumulation_steps 8 \
  --preserve_thinking false \
  --attn_impl sdpa --deepspeed zero2_offload \
  --torch_dtype bfloat16 \
  --num_train_epochs 3 --per_device_train_batch_size 1 \
  --learning_rate 1e-5 --warmup_ratio 0.05 \
  --max_length 65536 --gradient_checkpointing true \
  --save_steps 150 --save_total_limit 4 \
  --logging_steps 4 \
  --report_to $REPORT --run_name $RUN_NAME \
  --output_dir $B/out/q38e3-lean
echo "EXIT_q38e3_lean $?"
