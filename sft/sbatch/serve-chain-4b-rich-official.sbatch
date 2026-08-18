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
# model dir's built-in template
# (current-step thinking unaffected). Client behaviour stays upstream-
# identical (sends history think; template discards at render). Paired with
# rich/rich (keepthink) this isolates the eval-time effect of history-think
# visibility on the same weights. Port 8015 per the port-per-role convention.
# Sampling override = official general-thinking profile incl top_k 20, same
# as every other serve. CHAIN_MAX=2 as usual.
# CORRECTED 2026-08-18: the stock template does NOT strip history
# <think>. It lifts inline <think> out of content itself (:94-96), and
# history.py wraps every non-first user turn in <tool_response>, pinning
# the template's ns.last_query_index at 1 -- so the keep branch (:101)
# fires for every historical assistant turn. stock and keepthink render
# byte-identically on all 100 cached real payloads. The reason to use
# stock is that it is the model's own template and the OSWorld-Verified
# default, not that it hides anything. See CUA/sft/RESULTS.md 5.7.
set -uo pipefail

PROJ=/gpfs/scrubbed/jy050706/qwen-serve
SELF="$PROJ/serve-chain-4b-rich-official.sbatch"
MODEL=$(/gpfs/scrubbed/jy050706/qwen-serve/pick_ckpt.sh "/gpfs/scrubbed/jy050706/sft/out/q38e3-rich/v*" "${CKPT_POLICY:-endpoint}") || exit 1
KEYFILE="${VLLM_API_KEY_FILE:-$PROJ/.vllm_api_key}"
CHAIN_IDX="${CHAIN_IDX:-1}"; CHAIN_MAX="${CHAIN_MAX:-2}"

export UV_CACHE_DIR=/gpfs/scrubbed/jy050706/uv-cache
export HF_HUB_OFFLINE=1
export CUDA_HOME=/gpfs/scrubbed/jy050706/cuda-13.0
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"
export LIBRARY_PATH="$CUDA_HOME/lib64:$CUDA_HOME/lib64/stubs:${LIBRARY_PATH:-}"
# torch.compile cache on NODE-LOCAL NVMe, not GPFS: the shared
# .jitcache had grown to 49,284 small files across 32 model hashes,
# and vLLM stalled 13+ min in cxiWaitEventWait (GPFS metadata) where
# a healthy start takes 95 s (2026-08-17). A cold recompile costs
# ~18 s, so per-job local cache is strictly cheaper than sharing.
export XDG_CACHE_HOME=/tmp/jitcache-$SLURM_JOB_ID
mkdir -p "$XDG_CACHE_HOME"
trap 'rm -rf /tmp/jitcache-$SLURM_JOB_ID' EXIT
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
