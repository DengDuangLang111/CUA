#!/bin/bash
#SBATCH --job-name=merge-lora-bs
#SBATCH --account=video
#SBATCH --partition=gpu-h200
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=120G
#SBATCH --time=01:00:00
#SBATCH --output=/gpfs/scrubbed/jy050706/sft/merge_lora_bs_%j.out

# Merge the Bs-LoRA adapter into full weights so the eval serves it exactly
# like every full-FT arm (same vLLM path, no --enable-lora kernel). Without
# this the LoRA cell would differ from its comparators in TWO ways -- how the
# weights were trained AND how they are served -- and the arm would answer
# neither question cleanly.
umask 077
set -x
B=/gpfs/scrubbed/jy050706/sft
CKPT=$(/gpfs/scrubbed/jy050706/qwen-serve/pick_ckpt.sh "$B/out/q38Bs-lora/v*" "${CKPT_POLICY:-endpoint}") || exit 1
# The output dir carries the step. The first merge silently took
# checkpoint-90 (the picker above sorted paths lexicographically), and that
# merged dir is what the published 47.81% run served -- overwriting it would
# destroy the artifact behind a released number. Merging a different step now
# lands beside it instead of on top of it.
STEP=$(basename "$CKPT" | sed 's/checkpoint-//')
OUT=$B/out/q38Bs-lora-merged-$STEP
[ -n "$CKPT" ] && [ -d "$CKPT" ] || { echo "FATAL: no LoRA checkpoint"; exit 1; }
echo ">>> merging $CKPT (step $STEP) -> $OUT"
cd $B/runcwd && source $B/venv/bin/activate
export CUDA_HOME=$B/cuda13 PATH="$B/cuda13/bin:$PATH"
export LD_LIBRARY_PATH="$B/cuda13/lib64:$B/cuda13/lib:${LD_LIBRARY_PATH:-}"
rm -rf $OUT
swift export --adapters "$CKPT" --merge_lora true --output_dir "$OUT"
[ -f "$OUT/config.json" ] || { echo "FATAL: merge produced no config.json"; exit 1; }
ls -la "$OUT" | head -20
echo "MERGE_LORA_OK $OUT"
