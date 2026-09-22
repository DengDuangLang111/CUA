#!/bin/bash
#SBATCH --job-name=vt-b9m
#SBATCH --account=video
#SBATCH --partition=gpu-h200
#SBATCH --qos=normal
#SBATCH --nodes=4
#SBATCH --gpus-per-node=2
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=400G
#SBATCH --time=1-00:00:00
#SBATCH --output=/gpfs/scrubbed/jy050706/sft/mixB_9b_swemem_%j.out
# Experimental COPY of mixB-9b.sbatch. Production data/scripts are untouched.
#
# ONLY intended objective delta:
#   ordinary token-average -> SWE-MeM Eq.(3)-style rollout-balanced weights
#
# Data rows, all step-prefixes, last_round masking, model, optimizer, LR, batch,
# epochs, image/history window, and decoding format remain identical to MixB.
# The copied JSONL is prepared by sft/experiments/swe_mem/prepare_copy.py.
umask 077
set -x
B=/gpfs/scrubbed/jy050706/sft

DS=$B/data/mixB-swemem
SRC_V16MAIN=$B/data/v16-main
SRC_V16PILOT=$B/data/v16-pilot
SRC_V11NEW500=$B/data/v11new-500
SRC_V11NEWALL=$B/data/v11new-all
DS_V16MAIN=$DS/v16-main_train_swift_abs.jsonl
DS_V16PILOT=$DS/v16-pilot_train_swift_abs.jsonl
DS_V11NEW500=$DS/v11new-500_train_swift_abs.jsonl
DS_V11NEWALL=$DS/v11new-all_train_swift_abs.jsonl
DSLIST="$DS_V16MAIN $DS_V16PILOT $DS_V11NEW500 $DS_V11NEWALL"

# Build the independent JSONL copy before submitting this job:
# PYTHONPATH=$B/runcwd python -m ostg.sft.experiments.swe_mem.prepare_copy \
#   "$DS" \
#   --source-dir "$SRC_V16MAIN" --source-dir "$SRC_V16PILOT" \
#   --source-dir "$SRC_V11NEW500" --source-dir "$SRC_V11NEWALL" \
#   --tokenizer "$B/models/Qwen3.5-9B"

for _f in $DSLIST; do
  [ -s "$_f" ] || {
    echo "FATAL: missing SWE-MeM copied data: $_f" >&2
    exit 1
  }
done
[ -s "$DS/swemem_report.json" ] || {
  echo "FATAL: missing SWE-MeM audit: $DS/swemem_report.json" >&2
  exit 1
}

OUT=$B/out/mixB-9b-swemem
for _a in "$OUT"/*/args.json; do
  [ -e "$_a" ] || continue
  grep -q 'is_binary_loss_scale.*false' "$_a" || {
    echo "FATAL: $OUT contains a non-SWE-MeM run: $_a" >&2
    exit 1
  }
done
mkdir -p "$OUT"
cp "$DS/swemem_report.json" "$OUT/SWEMEM_DATA_REPORT.json"
echo "$DS" > "$OUT/CORPUS.txt"

export PATH="$HOME/.local/bin:$PATH"
cd $B/runcwd && source $B/venv/bin/activate
export CUDA_HOME=$B/cuda13 PATH="$B/cuda13/bin:$PATH"
export LD_LIBRARY_PATH="$B/cuda13/lib64:$B/cuda13/lib:${LD_LIBRARY_PATH:-}"
export NCCL_P2P_DISABLE=1
export PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True'
export IMAGE_MAX_TOKEN_NUM=2048

# Preflight images and prove every final assistant message carries a positive,
# genuinely non-binary trajectory weight. Abort before allocating GPUs on any
# silent fallback to the baseline objective.
python - $DSLIST <<'PY' || exit 1
import json, os, sys
bad_img = rows = missing_w = nonbinary = 0
weights = []
for path in sys.argv[1:]:
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        row = json.loads(line); rows += 1
        for p in row.get("images", []):
            if not os.path.isabs(p) or not os.path.exists(p):
                bad_img += 1
                if bad_img < 4:
                    print("UNRESOLVED:", p)
        msgs = row.get("messages") or []
        w = msgs[-1].get("loss_scale") if msgs else None
        if not isinstance(w, (int, float)) or not w > 0:
            missing_w += 1
        else:
            weights.append(float(w))
            nonbinary += int(abs(float(w) - 1.0) > 1e-12)
print(f"preflight rows={rows} bad_images={bad_img} missing_weights={missing_w} "
      f"nonbinary_weights={nonbinary} min={min(weights):.6g} max={max(weights):.6g}")
if bad_img or missing_w or not nonbinary:
    raise SystemExit(1)
PY

eval "$(python - $DSLIST <<'PY'
import sys
n = 0
for path in sys.argv[1:]:
    n += sum(1 for line in open(path, encoding="utf-8") if line.strip())
GB = 64
spe = -(-n // GB)
for d in (3, 2, 1):
    if spe % d == 0:
        save = spe // d
        break
print(f"SAMPLES={n}")
print(f"STEPS_PER_EPOCH={spe}")
print(f"SAVE_STEPS={save}")
print(f"TOTAL_STEPS={spe*3}")
PY
)"
echo ">>> SWE-MeM copy | samples $SAMPLES | steps/epoch $STEPS_PER_EPOCH | save_steps $SAVE_STEPS | total $TOTAL_STEPS"
[ "$SAMPLES" = 18576 ] || {
  echo "FATAL: row count changed; expected the all-prefix MixB count 18576" >&2
  exit 1
}

REPORT=none; RUN_NAME=mixB-9b-swemem-${SLURM_JOB_ID}
if [ -f "$B/wandb.env" ]; then set +x; source "$B/wandb.env"; set -x
  export WANDB_PROJECT="${WANDB_PROJECT:-cua-sft}"; REPORT=wandb; fi
export WANDB_NOTES="SWE-MeM Eq.(3) rollout-balanced loss copy of MixB-9B. All 18,576 prefixes retained; only per-trajectory target-token weights differ. img10/fold1, gb64, lr3e-6, 3ep."
export B DSLIST REPORT RUN_NAME OUT SAVE_STEPS
export MASTER_ADDR=$(scontrol show hostnames "$SLURM_JOB_NODELIST" | head -n1)
export MASTER_PORT=$((20000 + SLURM_JOB_ID % 9000))
export NNODES=4 NPROC_PER_NODE=2
echo ">>> multinode: nodes=$SLURM_JOB_NODELIST master=$MASTER_ADDR port=$MASTER_PORT"
srun --ntasks=4 --ntasks-per-node=1 --kill-on-bad-exit=1 bash -c '
  export NODE_RANK=$SLURM_NODEID
  echo ">>> node $SLURM_NODEID ($(hostname)) launching NPROC=$NPROC_PER_NODE"
  DS_ARGS=""; for d in $DSLIST; do DS_ARGS="$DS_ARGS $d"; done
  swift sft \
    --model $B/models/Qwen3.5-9B \
    --dataset $DS_ARGS \
    --enable_channel_loss true \
    --tuner_type full --loss_scale last_round --is_binary_loss_scale false \
    --gradient_accumulation_steps 8 \
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
    --output_dir $OUT
'
echo "EXIT_mixB_9b_swemem $?"
