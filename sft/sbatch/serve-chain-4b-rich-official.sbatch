#!/bin/bash
#SBATCH --job-name=eval4bro
#SBATCH --account=video
#SBATCH --partition=gpu-h200
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --gpus=1
#SBATCH --cpus-per-gpu=8
#SBATCH --mem=100G
#SBATCH --time=12:00:00
#SBATCH --output=/gpfs/scrubbed/jy050706/qwen-serve/serve4bro_%j.out
#SBATCH --signal=B:USR1@600
#
# Qwen3.5-4B SFT arm "rich" checkpoint-450 served under the OFFICIAL chat
# template -- the rich/stock cell: rich-trained weights, OSWorld-Verified
# DEFAULT serving. No --chat-template override, so vLLM renders with the
# model dir's built-in template, which STRIPS <think> from history turns
# (current-step thinking unaffected). Client behaviour stays upstream-
# identical (sends history think; template discards at render). Paired with
# rich/rich (keepthink) this isolates the eval-time effect of history-think
# visibility on the same weights. Port 8015 per the port-per-role convention.
# Sampling override = official general-thinking profile incl top_k 20, same
# as every other serve. CHAIN_MAX=2 as usual.
set -uo pipefail

PROJ=/gpfs/scrubbed/jy050706/qwen-serve
SELF="$PROJ/serve-chain-4b-rich-official.sbatch"
MODEL=/gpfs/scrubbed/jy050706/sft/out/q38e3-rich/v0-20260815-012706/checkpoint-450
KEYFILE="${VLLM_API_KEY_FILE:-$PROJ/.vllm_api_key}"
CHAIN_IDX="${CHAIN_IDX:-1}"; CHAIN_MAX="${CHAIN_MAX:-2}"

export UV_CACHE_DIR=/gpfs/scrubbed/jy050706/uv-cache
export HF_HUB_OFFLINE=1
export CUDA_HOME=/gpfs/scrubbed/jy050706/cuda-13.0
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"
export LIBRARY_PATH="$CUDA_HOME/lib64:$CUDA_HOME/lib64/stubs:${LIBRARY_PATH:-}"
export XDG_CACHE_HOME=/gpfs/scrubbed/jy050706/qwen-serve/.jitcache
export NVCC_APPEND_FLAGS="-DCCCL_DISABLE_CTK_COMPATIBILITY_CHECK"

[ -f "$KEYFILE" ] || { echo "FATAL: key file $KEYFILE missing (chmod 600)"; exit 1; }
perm=$(stat -c '%a' "$KEYFILE")
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
echo ">>> [q38e3-rich450-stock chain $CHAIN_IDX/$CHAIN_MAX] node=$(hostname) job=$SLURM_JOB_ID bind=127.0.0.1:8015"
python -c "import vllm; print('>>> vllm', vllm.__version__)" 2>/dev/null || true

vllm serve "$MODEL" \
  --served-model-name q38e3-rich450-stock \
  --tensor-parallel-size 1 \
  --max-model-len 262144 \
  --kv-cache-dtype fp8 \
  --reasoning-parser qwen3 \
  --override-generation-config '{"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0, "presence_penalty": 0.0, "repetition_penalty": 1.0, "max_new_tokens": 81920}' \
  --limit-mm-per-prompt '{"image": 20}' \
  --host 127.0.0.1 \
  --port 8015 &
VLLM_PID=$!
while kill -0 "$VLLM_PID" 2>/dev/null; do wait "$VLLM_PID"; done
echo ">>> [q38e3-rich450-stock chain $CHAIN_IDX] vLLM exited; this link ends."
