#!/bin/bash
#SBATCH --job-name=tmax9b-r5
#SBATCH --account=video
#SBATCH --partition=gpu-h200
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --gpus-per-node=4
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=800G
#SBATCH --time=08:00:00
#SBATCH --exclude=g018
#SBATCH --output=/gpfs/scrubbed/jy050706/sft/tmax9b_r5_%j.out
# ARM: tmax9b-full-r5-ml65k
# Same original a2 data/optimizer/length. User requested 4 H200, <=2 nodes,
# direct full training with no smoke. Four ranks x batch1 x accum16 = gb64.
set -euo pipefail
umask 077
B=/gpfs/scrubbed/jy050706/sft
DEPLOY=$B/deploy/tmax9b-r5-20260915
DS1=$B/data/q38-Bhqs2t-r5nocapimg10-v11100
DS2=$B/data/q38-Bhqs2t-r5nocapimg10-v11500
ARM=tmax9b-full-r5-ml65k
OUT=$B/out/$ARM
# Set RESUME_FROM to a complete checkpoint to restore optimizer/scheduler/RNG.
# 296948 hit its 400G host-memory limit at the step-136 save; keep GPU/math settings.
export RESUME_FROM="${RESUME_FROM:-}"
if [[ -n "$RESUME_FROM" ]]; then
    [[ "$RESUME_FROM" == "$OUT"/*/checkpoint-* && -f "$RESUME_FROM/trainer_state.json" ]] || exit 1
    TAG=$(cat "$RESUME_FROM/latest")
    [[ "$TAG" =~ ^global_step[0-9]+$ && -s "$RESUME_FROM/$TAG/mp_rank_00_model_states.pt" ]] || exit 1
    for RANK in 0 1 2 3; do
        [[ -s "$RESUME_FROM/$TAG/bf16_zero_pp_rank_${RANK}_mp_rank_00_optim_states.pt" && -s "$RESUME_FROM/rng_state_$RANK.pth" ]] || exit 1
    done
    [[ -s "$RESUME_FROM/scheduler.pt" ]] || exit 1
else
    [[ ! -e "$OUT" ]] || { echo "Refusing to overwrite $OUT" >&2; exit 1; }
fi
source "$B/venv/bin/activate"
python - "$B/models/tmax-9b-cua-init/INIT_MANIFEST.json" <<'PY'
import json,sys
m=json.load(open(sys.argv[1]))
assert m['status']=='verified' and m['language_tensors']==427 and m['visual_tensors']==333
assert m['language_revision']=='81ec54b29986d78191596d81900c0f8de2fa1b35'
PY
mkdir -p "$OUT"
if [[ -z "$RESUME_FROM" ]]; then
    cp "$DEPLOY/deployment.json" "$OUT/DEPLOYMENT.json"
    cp "$B/models/tmax-9b-cua-init/INIT_MANIFEST.json" "$OUT/INIT_MANIFEST.json"
fi
export PATH="$B/venv/bin:$HOME/.local/bin:$PATH"
export CUDA_HOME="$B/cuda13" PATH="$B/cuda13/bin:$PATH"
export LD_LIBRARY_PATH="$B/cuda13/lib64:$B/cuda13/lib:${LD_LIBRARY_PATH:-}"
export NCCL_P2P_DISABLE=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export IMAGE_MAX_TOKEN_NUM=2048
# Existing project fix: keep SDPA but disable its problematic cuDNN backend.
export PYTHONPATH="$B/nocudnn${PYTHONPATH:+:$PYTHONPATH}"
export NNODES=1 NPROC_PER_NODE=4
NNODES=$SLURM_JOB_NUM_NODES
[[ "$NNODES" == 1 || "$NNODES" == 2 ]] || exit 1
NPROC_PER_NODE=$((4 / NNODES))
[[ "$SLURM_GPUS_ON_NODE" == "$NPROC_PER_NODE" ]] || exit 1
export MASTER_ADDR
MASTER_ADDR=$(scontrol show hostnames "$SLURM_JOB_NODELIST" | head -n1)
export MASTER_PORT=$((20000 + SLURM_JOB_ID % 9000))
export B DS1 DS2 OUT ARM
export REPORT=none RUN_NAME=$ARM-$SLURM_JOB_ID
if [[ -f "$B/wandb.env" ]]; then
    source "$B/wandb.env"
    export WANDB_PROJECT="${WANDB_PROJECT:-cua-sft}" REPORT=wandb
fi
cd "$B/runcwd"
echo "ARM=$ARM job=$SLURM_JOB_ID nodes=$NNODES GPUs/node=$NPROC_PER_NODE global_batch=64 steps=306"
srun --ntasks="$NNODES" --ntasks-per-node=1 --cpus-per-task="$SLURM_CPUS_PER_TASK" --kill-on-bad-exit=1 bash -c '
  export NODE_RANK=$SLURM_NODEID
  RESUME_ARGS=()
  if [[ -n "$RESUME_FROM" ]]; then
    RESUME_ARGS=(--resume_from_checkpoint "$RESUME_FROM" --resume_only_model false)
  fi
  swift sft \
    --model $B/models/tmax-9b-cua-init --model_type qwen3_5 --template qwen3_5 \
    --dataset $DS1/train_swift.jsonl $DS2/train_swift.jsonl \
    --enable_channel_loss true --tuner_type full --loss_scale last_round \
    --freeze_vit true --freeze_aligner true --preserve_thinking true \
    --attn_impl sdpa --deepspeed zero2_offload --torch_dtype bfloat16 \
    --num_train_epochs 3 --per_device_train_batch_size 1 --gradient_accumulation_steps 16 \
    --learning_rate 3e-6 --lr_scheduler_type cosine --warmup_ratio 0.1 \
    --weight_decay 0.0 --adam_beta1 0.9 --adam_beta2 0.999 --adam_epsilon 1e-8 \
    --seed 42 --data_seed 42 --max_length 65536 --gradient_checkpointing true \
    --save_strategy steps --save_steps 34 --save_total_limit 12 --logging_steps 2 \
    --report_to "$REPORT" --run_name "$RUN_NAME" --output_dir "$OUT" "${RESUME_ARGS[@]}"
'
echo "Completed $ARM"
