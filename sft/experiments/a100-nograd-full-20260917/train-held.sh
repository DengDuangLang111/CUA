#!/bin/bash
# ARM: 9b-full-r5+v16save143.tf-ml65k-vnograd
# Run as a step of the user's existing single-node, four-A100 allocation.
set -euo pipefail
umask 077
B=/gscratch/cse/jy050706/sft
DEPLOY=$B/experiments/a100-nograd-full-20260917
DS=$B/data/r5-v16save143-tf
LOCAL=/tmp/jy050706-a100-length-20260917
ARM=9b-full-r5+v16save143.tf-ml65k-vnograd
OUT=/gscratch/krishna/jy050706/out/$ARM/train20260917-klone1x4
NNODES=1 NPROC_PER_NODE=4
# Explicit torchrun below owns process creation; Swift CLI must not launch it again.
export -n NNODES NPROC_PER_NODE
[[ "$SLURM_JOB_ID" == 40253867 && "$SLURM_STEP_NUM_NODES" == 1 && "$SLURM_GPUS_ON_NODE" == 4 ]] || exit 1
[[ ! -e "$OUT" ]] || { echo "Refusing to overwrite $OUT" >&2; exit 1; }
if nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | awk '$1>1024 {bad=1} END {exit !bad}'; then
    echo 'GPU already in use; aborting' >&2
    exit 1
fi
mkdir -p "$OUT" "$LOCAL/cache" "$LOCAL/triton" "$LOCAL/extensions"
if [[ ! -f "$LOCAL/sft-train.sif" ]]; then cp "$B/../sif/sft-train.sif" "$LOCAL/sft-train.sif"; fi
if [[ ! -d "$LOCAL/Qwen3.5-9B" ]]; then cp -a "$B/models/Qwen3.5-9B" "$LOCAL/"; fi
apptainer exec --nv \
    --bind /gscratch/cse/jy050706:/gscratch/cse/jy050706 \
    --bind "$B/data:/gpfs/scrubbed/jy050706/sft/data" \
    "$LOCAL/sft-train.sif" /opt/venv/bin/python "$DEPLOY/preflight.py"
cp "$DS/manifest.json" "$OUT/CORPUS_MANIFEST.json"
cp "$DEPLOY/deployment.json" "$OUT/DEPLOYMENT.json"
cp "$DEPLOY/train-held.sh" "$DEPLOY/sitecustomize.py" "$OUT/"
printf '%s\n' "job=$SLURM_JOB_ID step=$SLURM_STEP_ID node=$(hostname -s) arm=$ARM" | tee "$OUT/SLURM_STEP.txt"
nvidia-smi --query-gpu=timestamp,index,memory.used,utilization.gpu --format=csv -l 60 > "$OUT/gpu.csv" &
MON=$!
trap 'kill "$MON" 2>/dev/null || true' EXIT
set +e
apptainer exec --nv \
    --bind /gscratch/cse/jy050706:/gscratch/cse/jy050706 \
    --bind /gscratch/krishna/jy050706:/gscratch/krishna/jy050706 \
    --bind "$B/data:/gpfs/scrubbed/jy050706/sft/data" \
    --env HF_HOME="$LOCAL/hf" --env HF_HUB_OFFLINE=1 \
    --env XDG_CACHE_HOME="$LOCAL/cache" --env TRITON_CACHE_DIR="$LOCAL/triton" \
    --env TORCH_EXTENSIONS_DIR="$LOCAL/extensions" --env OMP_NUM_THREADS=4 \
    --env IMAGE_MAX_TOKEN_NUM=2048 --env NCCL_P2P_DISABLE=1 \
    --env PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    --env PYTHONPATH="$DEPLOY" --env FROZEN_VISION_NO_GRAD=1 \
    "$LOCAL/sft-train.sif" \
    /opt/venv/bin/torchrun --standalone --nnodes=1 --nproc_per_node=4 /opt/venv/bin/swift sft \
    --model "$LOCAL/Qwen3.5-9B" --model_type qwen3_5 --template qwen3_5 \
    --dataset "$DS/train_swift_abs.jsonl" --split_dataset_ratio 0 \
    --enable_channel_loss true --tuner_type full --loss_scale last_round \
    --freeze_vit true --freeze_aligner true --preserve_thinking true \
    --attn_impl sdpa --deepspeed zero2_offload --torch_dtype bfloat16 \
    --num_train_epochs 3 --per_device_train_batch_size 1 --gradient_accumulation_steps 16 \
    --learning_rate 3e-6 --lr_scheduler_type cosine --warmup_ratio 0.1 \
    --weight_decay 0.0 --adam_beta1 0.9 --adam_beta2 0.999 --adam_epsilon 1e-8 \
    --seed 42 --data_seed 42 --max_length 65536 --gradient_checkpointing true \
    --dataloader_num_workers 0 --dataset_num_proc 1 \
    --save_strategy steps --save_steps 159 --save_total_limit 3 --logging_steps 1 \
    --report_to none --run_name "$ARM-klone1x4-$SLURM_JOB_ID" --output_dir "$OUT" > "$OUT/train.log" 2>&1
RC=$?
set -e
echo "$RC" > "$OUT/exit_code.txt"
echo "TRAIN_EXIT=$RC OUT=$OUT"
exit "$RC"
