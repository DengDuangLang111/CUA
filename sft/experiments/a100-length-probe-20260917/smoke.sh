#!/bin/bash
# Run inside the existing 4-A100 allocation; no new allocation or full training.
set -euo pipefail
CAP=${1:?max sequence length}
CASE=${2:?unique case name}
DS=${3:-zero2_offload}
CHANNEL=${4:-true}
[[ "$CAP" =~ ^(16384|24576|32768|49152|65536|81920)$ ]] || exit 1
[[ "$CASE" =~ ^[a-z0-9_-]+$ ]] || exit 1
BASE=/gscratch/cse/jy050706/sft
PROBE=$BASE/experiments/a100-length-probe-20260917
LOCAL=/tmp/jy050706-a100-length-20260917
OUT=$PROBE/results/$CASE
[[ ! -e "$OUT" ]] || { echo "Refusing to overwrite $OUT" >&2; exit 1; }
mkdir -p "$OUT" "$LOCAL/cache" "$LOCAL/triton" "$LOCAL/extensions"
if nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | awk '$1>1024 {bad=1} END {exit !bad}'; then
    echo 'GPU already in use; refusing to overlap another GPU workload' >&2
    exit 1
fi
cp "$PROBE/smoke.sh" "$OUT/smoke.sh"
cp "$PROBE/sitecustomize.py" "$OUT/sitecustomize.py"
cp "$PROBE/top64-$CAP.jsonl" "$OUT/test_data.jsonl"
printf '%s\n' "cap=$CAP case=$CASE deepspeed=$DS channel_loss=$CHANNEL" > "$OUT/case.txt"
nvidia-smi --query-gpu=timestamp,index,memory.used,utilization.gpu --format=csv -l 5 > "$OUT/gpu.csv" &
MON=$!
trap 'kill "$MON" 2>/dev/null || true' EXIT
set +e
timeout --signal=TERM --kill-after=60 2400 apptainer exec --nv \
    --bind /gscratch/cse/jy050706:/gscratch/cse/jy050706 \
    --bind "$BASE/data:/gpfs/scrubbed/jy050706/sft/data" \
    --env HF_HOME="$LOCAL/hf" --env HF_HUB_OFFLINE=1 \
    --env XDG_CACHE_HOME="$LOCAL/cache" --env TRITON_CACHE_DIR="$LOCAL/triton" \
    --env TORCH_EXTENSIONS_DIR="$LOCAL/extensions" --env OMP_NUM_THREADS=4 \
    --env IMAGE_MAX_TOKEN_NUM=2048 --env NCCL_P2P_DISABLE=1 \
    --env PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    --env PYTHONPATH="$PROBE" \
    --env PROBE_FROZEN_VISION_NO_GRAD="${PROBE_FROZEN_VISION_NO_GRAD:-0}" \
    "$LOCAL/sft-train.sif" \
    /opt/venv/bin/torchrun --standalone --nnodes=1 --nproc_per_node=4 /opt/venv/bin/swift sft \
    --model "$LOCAL/Qwen3.5-9B" --model_type qwen3_5 --template qwen3_5 \
    --dataset "$OUT/test_data.jsonl" --split_dataset_ratio 0 \
    --enable_channel_loss "$CHANNEL" --tuner_type full --loss_scale last_round \
    --freeze_vit true --freeze_aligner true --preserve_thinking true \
    --attn_impl sdpa --deepspeed "$DS" --torch_dtype bfloat16 \
    --per_device_train_batch_size 1 --gradient_accumulation_steps 16 \
    --learning_rate 3e-6 --lr_scheduler_type cosine --warmup_ratio 0.1 \
    --weight_decay 0.0 --adam_beta1 0.9 --adam_beta2 0.999 --adam_epsilon 1e-8 \
    --seed 42 --data_seed 42 --max_length "$CAP" --gradient_checkpointing true \
    --max_steps 2 --dataloader_num_workers 0 --dataset_num_proc 1 \
    --save_strategy steps --save_steps 2 --save_total_limit 1 --logging_steps 1 \
    --report_to none --output_dir "$OUT/train" > "$OUT/train.log" 2>&1
RC=$?
set -e
echo "$RC" > "$OUT/exit_code.txt"
echo "SMOKE_COMPLETE case=$CASE exit=$RC"
tail -35 "$OUT/train.log"
exit "$RC"
