#!/bin/bash
#SBATCH --job-name=eval9b-a4
#SBATCH --account=video
#SBATCH --partition=gpu-h200
#SBATCH --qos=normal
#SBATCH --nodes=4
#SBATCH --gpus-per-node=2
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=400G
#SBATCH --time=12:00:00
#SBATCH --exclude=g018
#SBATCH --output=/gpfs/scrubbed/jy050706/sft/sft_mixaw9b_%j.out
# ARM: 9B on the same img10 corpus
#
# ---- what differs from the champion recipe (sft-q38Bhqs2t-lr3e6-nocap) ----
# corpus r5nocap -> r5nocapimg10 AND model Qwen3.5-4B -> Qwen3.5-9B.
#
# ---- shape ----
# 8 GPUs as 4 nodes x 2, not 16 as 2 nodes x 8. Measured queue waits on this
# account: 8-GPU jobs 0-67 min (median 7), 16-GPU jobs 0-571 min. Fairshare
# here is last in the cluster, so the tail is what matters, and eight GPUs
# backfill where two whole nodes wait hours. This exact shape ran nocapnp. Global batch stays 64 -- 8 ranks x
# bs1 x accum8 -- so the gradient is identical to the 16x4 champion
# (average_tokens_across_devices=True). Steps become 306, not 303: step count
# tracks rank count, floor(6474/8)=809 then ceil(809/8)=102 per epoch.
#
# accum 8 was the documented ceiling (~250MB/microbatch on the external loss
# path) back when the 20-image corpus peaked at 136.7 GiB of 139.79. The
# img10 corpus measured 83.74 GiB on 2026-08-22, so the extra four
# microbatches cost ~1 GB against 56 GB of headroom.
#
# ---- launch ----
# Standard torchrun, unchanged from nocapnp. A --gpus-per-task=1 variant was
# tried first so Slurm could split the 8 GPUs any way it liked; it failed
# (smoke 252370): each task then sees one GPU as device 0, but DeepSpeed
# recomputes local_rank as rank-within-node and calls set_device(7) on a
# process whose only visible device is 0 -- CUDA error 101, invalid device
# ordinal. Flexible per-node GPU counts are not reachable without patching
# DeepSpeed's local-rank inference, and 4x2 already gets the queue benefit.
umask 077
set -x
B=/gpfs/scrubbed/jy050706/sft
DS1=$B/data/mixa-webstar-v16strict
export PATH="$HOME/.local/bin:$PATH"
cd $B/runcwd && source $B/venv/bin/activate
export CUDA_HOME=$B/cuda13 PATH="$B/cuda13/bin:$PATH"
export LD_LIBRARY_PATH="$B/cuda13/lib64:$B/cuda13/lib:${LD_LIBRARY_PATH:-}"
export NCCL_P2P_DISABLE=1
export PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True'
export IMAGE_MAX_TOKEN_NUM=2048
for DS in $DS1; do
python - "$DS" <<'PY' || { echo "PREFLIGHT FAILED"; exit 1; }
import json, os, sys
ds = sys.argv[1]; bad = tot = 0
for line in open(os.path.join(ds, "train_swift.jsonl"), encoding="utf-8"):
    if not line.strip(): continue
    for p in json.loads(line).get("images", []):
        tot += 1
        if not os.path.isabs(p) or not os.path.exists(p): bad += 1
print(f"preflight {ds}: {tot} image refs, {bad} unresolved")
sys.exit(1 if bad else 0)
PY
done
REPORT=none; RUN_NAME=mixaw9b-${SLURM_JOB_ID}
if [ -f "$B/wandb.env" ]; then set +x; source "$B/wandb.env"; set -x
  export WANDB_PROJECT="${WANDB_PROJECT:-cua-sft}"; REPORT=wandb; fi
export WANDB_NOTES="mixA + WebSTAR step filter. Corpus: v11 r5-img10 (362 traj) + v16 strict-340, both step-filtered by WebSTAR official-revised-desktop-v1 (gpt-5.6-luna, score>5 keeps the target; dropped steps stay in later context). 13199 scored steps -> 7311 kept (55.4%). All 687 terminal targets kept and all carry an explicit terminate: v16 was rebuilt with terminalfix (3.7% -> 100%). Known costs: the 687 rewritten endings were never graded (grading predates terminalfix), the post-grading sha256 guard was removed, and the 200-step calibration was skipped so score>5 is uncalibrated on this corpus. Second judge (claude-opus-5) only reached 31% before the relay key died; on the shared 3311 it agreed 70.8% and kept 74.9% vs luna 56.0%."
export MASTER_ADDR=$(scontrol show hostnames "$SLURM_JOB_NODELIST" | head -n1)
export MASTER_PORT=$((20000 + SLURM_JOB_ID % 9000))
export B DS1 REPORT RUN_NAME
echo ">>> mixaw9b on $SLURM_JOB_NODELIST ($SLURM_JOB_NUM_NODES nodes, $SLURM_NTASKS tasks)"
export NNODES=4 NPROC_PER_NODE=2
srun --ntasks=4 --ntasks-per-node=1 --kill-on-bad-exit=1 bash -c '
  export NODE_RANK=$SLURM_NODEID
  echo ">>> node $SLURM_NODEID ($(hostname -s)) launching NPROC=$NPROC_PER_NODE"
  swift sft \
    --model $B/models/Qwen3.5-9B \
    --dataset $DS1/train_swift.jsonl \
    --enable_channel_loss true \
    --tuner_type full --loss_scale last_round --gradient_accumulation_steps 8 \
    --preserve_thinking true \
    --attn_impl sdpa --deepspeed zero2_offload \
    --torch_dtype bfloat16 \
    --num_train_epochs 3 --per_device_train_batch_size 1 \
    --learning_rate 3e-6 --warmup_ratio 0.1 \
    --weight_decay 0.0 --adam_beta2 0.999 \
    --max_length 65536 --gradient_checkpointing true \
    --save_strategy steps --save_steps 115 --save_total_limit 4 \
    --logging_steps 2 \
    --report_to $REPORT --run_name $RUN_NAME \
    --output_dir $B/out/mixaw9b
'
echo "EXIT_mixaw9b $?"
