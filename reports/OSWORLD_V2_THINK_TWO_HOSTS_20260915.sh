#!/usr/bin/env bash
set -euo pipefail
BENCH_ROOT=${OSWORLD_HARNESS_ROOT:?Set the existing V2 checkout}
BENCH_HOST=${1:?workstation or windows}
case "$BENCH_HOST" in
  workstation) BENCH_VM_COUNT=6; MODEL_URL=http://127.0.0.1:8100/v1 ;;
  windows) BENCH_VM_COUNT=2; MODEL_URL=http://100.72.191.125:8100/v1 ;;
  *) exit 2 ;;
esac
cd "$BENCH_ROOT"
export OPENAI_API_KEY
OPENAI_API_KEY=$(cat "$HOME/.config/cua-v2/teacher_api_key")
export OSWORLD_EVAL_MODEL_BASE_URL=https://api.anthropic.com
export OSWORLD_USER_SIM_BASE_URL=https://api.anthropic.com
export CUA_TRAJECTORY_TOOL="$HOME/cua-v2-trajectory-tool-20260915"
export CUA_INSPECTION_CONFIG="$BENCH_ROOT/launch-think-20260915/inspection.json"
exec .venv/bin/python -u launch-think-20260915/entry.py \
  --eval_version v2 --provider_name docker --observation_type screenshot \
  --model qwen38-27b --base_url "$MODEL_URL" --api_key_env OPENAI_API_KEY \
  --enable_thinking \
  --temperature 1.0 --top_p 0.95 --max_tokens 81920 \
  --max_steps 100 --num_envs "$BENCH_VM_COUNT" --history_n 100 \
  --image_max 10 --fold_size 1 \
  --test_config_base_dir evaluation_examples \
  --test_all_meta_path "launch-think-20260915/tasks-$BENCH_HOST.json" \
  --result_dir "results_v2/qwen38-27b-think-i10f1-r3-20260915-$BENCH_HOST"
