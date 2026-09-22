#!/bin/bash
#SBATCH --job-name=eval38
#SBATCH --account=video
#SBATCH --partition=gpu-h200
#SBATCH --qos=interactive
#SBATCH --nodes=1
#SBATCH --gpus=1
#SBATCH --cpus-per-gpu=8
#SBATCH --mem=200G
#SBATCH --time=04:00:00
#SBATCH --output=/gpfs/scrubbed/jy050706/qwen-serve/serve38i_%j.out
#SBATCH --signal=B:USR1@600
#
# Qwen3.8-27B, BF16, released 2026-08-14. 27.78B params, Apache 2.0,
# text+image+video, 262144 native context, 64 layers = 48 Gated DeltaNet
# (linear) + 16 Gated Attention, vocab 248,320 (verified from the downloaded
# config.json, not the card).
#
# TWO DELIBERATE DIFFERENCES FROM THE Qwen3.6 SERVE, both corrections:
#
# 1. NO --chat-template override. The 3.6 serve points at
#    chat_template_think.jinja, which differs from Qwen3.6's own in two ways:
#    it forces thinking unconditionally AND prefills the thinking block with
#    "Okay, ". That second one is an undocumented behavioural nudge and there is
#    no reason to believe it transfers to a different model. Qwen3.8's own
#    template already honours `enable_thinking` and defaults to thinking on,
#    which is what the runner asks for.
#
# 2. Sampling is Qwen3.8's OFFICIAL GENERAL THINKING profile:
#       temperature 1.0 · top_p 0.95 · top_k 20 · min_p 0 · presence 0 · rep 1.0
#    The campaigns to date ran temperature 0.6, which is the profile Qwen labels
#    "precise coding tasks (e.g. WebDev)". Driving a GUI is agentic control.
#
# 3. Official vLLM recipe (recipes.vllm.ai/Qwen/Qwen3.8-27B) applied: TP1,
#    --max-model-len 262144, --kv-cache-dtype fp8, --reasoning-parser qwen3.
#    Requirements met: vLLM 0.25.1 >= 0.17.0, transformers 5.14.1 >= 5.8.0.
#
#    DELIBERATELY NOT TAKEN from the recipe: --enable-auto-tool-choice and
#    --tool-call-parser qwen3_coder. Those make vLLM parse the tool call and
#    return it as a structured field; this harness parses the RAW text itself in
#    mm_agents/qwen/actions.py (parse_internal_response) and would receive an
#    empty body. "Use the official settings" stops where they would break the
#    harness -- and this one would break it silently, into the WAIT fallback.
#
#    *** THE CLIENT WINS. *** --override-generation-config only sets defaults;
#    run_multienv_qwen.py sends temperature per request and that takes
#    precedence. The 3.6 serve has said "temperature: 1.0" this whole time while
#    every rollout actually ran at 0.6. The RUNNER must pass --temperature 1.0.
set -uo pipefail

PROJ=/gpfs/scrubbed/jy050706/qwen-serve
SELF="$PROJ/serve-chain-38.sbatch"
MODEL=/gpfs/scrubbed/jy050706/models/Qwen3.8-27B
KEYFILE="${VLLM_API_KEY_FILE:-$PROJ/.vllm_api_key}"
CHAIN_IDX="${CHAIN_IDX:-1}"; CHAIN_MAX="${CHAIN_MAX:-14}"

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
echo ">>> [Qwen3.8-27B chain $CHAIN_IDX/$CHAIN_MAX] node=$(hostname) job=$SLURM_JOB_ID bind=127.0.0.1:8000"
python -c "import vllm; print('>>> vllm', vllm.__version__)" 2>/dev/null || true

vllm serve "$MODEL" \
  --served-model-name qwen38-27b-local \
  --tensor-parallel-size 1 \
  --max-model-len 262144 \
  --kv-cache-dtype fp8 \
  --reasoning-parser qwen3 \
  --override-generation-config '{"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0, "presence_penalty": 0.0, "repetition_penalty": 1.0, "max_new_tokens": 81920}' \
  --limit-mm-per-prompt '{"image": 20}' \
  --host 127.0.0.1 \
  --port 8000 &
VLLM_PID=$!
while kill -0 "$VLLM_PID" 2>/dev/null; do wait "$VLLM_PID"; done
echo ">>> [Qwen3.8-27B chain $CHAIN_IDX] vLLM exited; this link ends."
