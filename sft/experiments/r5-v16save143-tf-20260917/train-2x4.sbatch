#!/bin/bash
#SBATCH --job-name=9b-save143tf-2x4
#SBATCH --account=video
#SBATCH --partition=gpu-h200
#SBATCH --qos=urgent
#SBATCH --nodes=2
#SBATCH --gpus-per-node=4
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=800G
#SBATCH --time=1-00:00:00
#SBATCH --exclude=g018
#SBATCH --output=/gpfs/scrubbed/jy050706/sft/save143tf_2x4_%j.out
# ARM: 9b-full-r5+v16save143.tf
# Same 505-task corpus/optimizer as 2x8; 8 ranks x batch1 x accum8 = 64.
set -euo pipefail
umask 077
B=/gpfs/scrubbed/jy050706/sft
DEPLOY=$B/deploy/r5-v16save143-tf-20260917
DS=$B/data/r5-v16save143-tf
ARM=9b-full-r5+v16save143.tf
OUT=$B/out/$ARM/train20260917-2x4
[[ ! -e "$OUT" ]] || { echo "Refusing to overwrite $OUT" >&2; exit 1; }
source "$B/venv/bin/activate"
python "$DEPLOY/preflight.py"
mkdir -p "$OUT"
cp "$DS/manifest.json" "$OUT/CORPUS_MANIFEST.json"
cp "$DEPLOY/deployment.json" "$OUT/DEPLOYMENT.json"
cp "$DEPLOY/train-2x4.sbatch" "$OUT/LAUNCH.sbatch"
export PATH="$B/venv/bin:$HOME/.local/bin:$PATH"
export CUDA_HOME="$B/cuda13" PATH="$B/cuda13/bin:$PATH"
export LD_LIBRARY_PATH="$B/cuda13/lib64:$B/cuda13/lib:${LD_LIBRARY_PATH:-}"
export NCCL_P2P_DISABLE=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export IMAGE_MAX_TOKEN_NUM=2048
export PYTHONPATH="$B/nocudnn${PYTHONPATH:+:$PYTHONPATH}"
export NNODES=2 NPROC_PER_NODE=4
[[ "$SLURM_JOB_NUM_NODES" == 2 && "$SLURM_GPUS_ON_NODE" == 4 ]] || exit 1
export MASTER_ADDR
MASTER_ADDR=$(scontrol show hostnames "$SLURM_JOB_NODELIST" | head -n1)
export MASTER_PORT=$((20000 + SLURM_JOB_ID % 9000))
export B DS OUT ARM REPORT=none RUN_NAME=$ARM-2x4-$SLURM_JOB_ID
if [[ -f "$B/wandb.env" ]]; then
    source "$B/wandb.env"
    export WANDB_PROJECT="${WANDB_PROJECT:-cua-sft}" REPORT=wandb
fi
cd "$B/runcwd"
echo "ARM=$ARM job=$SLURM_JOB_ID nodes=$SLURM_JOB_NODELIST topology=2x4 global_batch=64 samples=10142 steps=477"
srun --ntasks=2 --ntasks-per-node=1 --cpus-per-task="$SLURM_CPUS_PER_TASK" --kill-on-bad-exit=1 bash -c '
  set -euo pipefail
  export NODE_RANK=$SLURM_NODEID
  swift sft \
    --model $B/models/Qwen3.5-9B --model_type qwen3_5 --template qwen3_5 \
    --dataset $DS/train_swift_abs.jsonl \
    --enable_channel_loss true --tuner_type full --loss_scale last_round \
    --freeze_vit true --freeze_aligner true --preserve_thinking true \
    --attn_impl sdpa --deepspeed zero2_offload --torch_dtype bfloat16 \
    --num_train_epochs 3 --per_device_train_batch_size 1 --gradient_accumulation_steps 8 \
    --learning_rate 3e-6 --lr_scheduler_type cosine --warmup_ratio 0.1 \
    --weight_decay 0.0 --adam_beta1 0.9 --adam_beta2 0.999 --adam_epsilon 1e-8 \
    --seed 42 --data_seed 42 --max_length 81920 --gradient_checkpointing true \
    --save_strategy steps --save_steps 159 --save_total_limit 3 --logging_steps 1 \
    --report_to "$REPORT" --run_name "$RUN_NAME" --output_dir "$OUT"
'
echo "Completed $ARM 2x4"
