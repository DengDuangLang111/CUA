#!/bin/bash
#SBATCH --job-name=eval4bnp
#SBATCH --account=video
#SBATCH --partition=gpu-h200
#SBATCH --qos=interactive
#SBATCH --nodes=1
#SBATCH --gpus=1
#SBATCH --cpus-per-gpu=8
#SBATCH --mem=100G
#SBATCH --time=08:00:00   # maintenance reservation verified RELEASED
                          # (scontrol show reservation, 2026-08-18 evening)
#SBATCH --output=/gpfs/scrubbed/jy050706/qwen-serve/eval4bnp_%j.out
#SBATCH --exclude=g018    # CUDA 'available devices to be zero' node; not
                          # drained by admins yet -- remove once known good
#SBATCH --signal=B:USR1@600
#
# kG: no-prose LoRA (corpus sft-Bhqs2tr5np-v11500) merged at its ENDPOINT,
# official stock template. Differs from the r5lora arm ONLY by prose removal
# (two build gates: strip-both-identical + direct zero-prose; see
# CUA/sft/RESULTS.md). Merged dir derived via the same policy the merge used,
# so a missing merge fails loudly instead of serving a stale dir.
#
set -uo pipefail

PROJ=/gpfs/scrubbed/jy050706/qwen-serve
SELF="$PROJ/serve-chain-4b-loranp-stock.sbatch"
LORA_CKPT=$(/gpfs/scrubbed/jy050706/qwen-serve/pick_ckpt.sh "/gpfs/scrubbed/jy050706/sft/out/q38Bhqs2t-loranp/v*" "${CKPT_POLICY:-endpoint}") || exit 1
MODEL=/gpfs/scrubbed/jy050706/sft/out/q38Bhqs2t-loranp-merged-${LORA_CKPT##*checkpoint-}
[ -f "$MODEL/config.json" ] || { echo "FATAL: no merge for ${LORA_CKPT##*/} at $MODEL"; exit 1; }
echo "[serve] loranp adapter ${LORA_CKPT##*/} -> merged weights $MODEL" >&2
KEYFILE="${VLLM_API_KEY_FILE:-$PROJ/.vllm_api_key}"
CHAIN_IDX="${CHAIN_IDX:-1}"; CHAIN_MAX="${CHAIN_MAX:-2}"

export UV_CACHE_DIR=/gpfs/scrubbed/jy050706/uv-cache
export HF_HUB_OFFLINE=1
export CUDA_HOME=/gpfs/scrubbed/jy050706/cuda-13.0
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"
export LIBRARY_PATH="$CUDA_HOME/lib64:$CUDA_HOME/lib64/stubs:${LIBRARY_PATH:-}"
# torch.compile cache on NODE-LOCAL NVMe, not GPFS (49k-file .jitcache stalled
# vLLM 13+ min in GPFS metadata; cold recompile is ~18 s -- see bs-stock notes)
export XDG_CACHE_HOME=/tmp/jitcache-$SLURM_JOB_ID
mkdir -p "$XDG_CACHE_HOME"
trap 'rm -rf /tmp/jitcache-$SLURM_JOB_ID' EXIT
export NVCC_APPEND_FLAGS="-DCCCL_DISABLE_CTK_COMPATIBILITY_CHECK"

[ -f "$KEYFILE" ] || { echo "FATAL: key file $KEYFILE missing (chmod 600)"; exit 1; }
perm=$(stat -c "%a" "$KEYFILE")
case "$perm" in 600|400) : ;; *) echo "FATAL: $KEYFILE perms=$perm (want 600/400)"; exit 1;; esac
export VLLM_API_KEY="$(cat "$KEYFILE")"
[ -n "$VLLM_API_KEY" ] || { echo "FATAL: $KEYFILE is empty"; exit 1; }
[ -d "$MODEL" ] || { echo "FATAL: checkpoint dir $MODEL missing"; exit 1; }

RESUBMITTED=0
resubmit() {
  [ "$RESUBMITTED" = 1 ] && return; RESUBMITTED=1
  if [ "$CHAIN_IDX" -ge "$CHAIN_MAX" ]; then echo ">>> [chain $CHAIN_IDX/$CHAIN_MAX] CHAIN_MAX reached; ending."; return; fi
  nxt=$((CHAIN_IDX+1))
  echo ">>> [chain] ~10min to wall -> submitting successor $nxt/$CHAIN_MAX (afterany:$SLURM_JOB_ID)"
  sbatch --dependency=afterany:"$SLURM_JOB_ID" --export=ALL,CHAIN_IDX="$nxt",CHAIN_MAX="$CHAIN_MAX" "$SELF" \
    || echo ">>> [chain] WARNING: successor sbatch FAILED -> chain stops."
}
trap resubmit USR1

source "$PROJ/.venv/bin/activate"
echo ">>> [q38Bhqs2t-loranp-stock chain $CHAIN_IDX/$CHAIN_MAX] node=$(hostname) job=$SLURM_JOB_ID bind=127.0.0.1:8031"
python -c "import vllm; print('>>> vllm', vllm.__version__)" 2>/dev/null || true

vllm serve "$MODEL" \
  --served-model-name q38Bhqs2t-loranp-stock \
  --tensor-parallel-size 1 \
  --max-model-len 262144 \
  --kv-cache-dtype fp8 \
  --reasoning-parser qwen3 \
  --override-generation-config '{"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0, "presence_penalty": 0.0, "repetition_penalty": 1.0, "max_new_tokens": 81920}' \
  --limit-mm-per-prompt '{"image": 20}' \
  --host 127.0.0.1 \
  --port 8031 &
VLLM_PID=$!
while kill -0 "$VLLM_PID" 2>/dev/null; do wait "$VLLM_PID"; done
echo ">>> [q38Bhqs2t-loranp-stock chain $CHAIN_IDX] vLLM exited; this link ends."
