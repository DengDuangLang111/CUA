#!/bin/bash
#SBATCH --job-name=sft-q38Bhqs2t-loranp
#SBATCH --account=video
#SBATCH --partition=gpu-h200
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --gpus-per-node=8
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=64
#SBATCH --mem=400G
#SBATCH --time=07:00:00
#SBATCH --output=/gpfs/scrubbed/jy050706/sft/sft_q38Bhqs2t_loranp_%j.out
# Bhqs-2-terminal under LoRA, NO VISIBLE PROSE, one node.
#
# Single variable vs 240310 (the same arm on the r5 corpus): the visible text
# each target writes between </think> and <tool_call> is deleted -- from the
# training target and from the history rendering alike, terminal steps
# included. Everything else is copied verbatim: same trajectories, same
# terminal rewrites, same think-cap 2048, same LoRA hyper-parameters, same
# system-prompt date (the corpus was built with --freeze-date so a rebuild on
# a later day would not silently differ by more than the flag under test).
#
# The corpus is q38-Bhqs2t-r5np-*, built from worktree /mnt/d/research/
# ostg-noprose (branch noprose, commit 9ddaea5e) and accepted by two gates:
#   1. no prose survives anywhere -- 0 of 6,023 mid targets, 0 of 362 terminal;
#   2. stripping prose from r5 AND from this corpus yields identical bytes,
#      so prose is the only difference.
# Gate 2 alone is blind: it strips both sides, so it passed even when the
# first build left 315 terminal statements intact. Gate 1 is what caught that.
#
# What this measures: prose is 13.9% of target tokens here versus 0.3% in
# OpenWebRL's SFT data. It is NOT a termination fix -- the base 4B model emits
# prose on 100% of its eval steps (1,587/1,587) and still terminates
# explicitly more often than any SFT arm, so prose and termination do not
# co-vary in the direction the prose-fallback story implied. The risk is the
# mirror image: removing prose pushes the target off the student's own output
# prior, and that is the experiment.
#
# Original header follows.
#
# Single variable vs the Bs-LoRA arm (235948, 45.8%-arm weights under LoRA):
# the CORPUS. Every LoRA hyper-parameter is copied from that job verbatim --
# rank 32, alpha 64, dropout 0.05, all-linear, lr 1e-4, 3 epochs, global batch
# 64 -- so a difference in eval is attributable to the data, which is the whole
# point of this arm.
#
# SHAPE: 8 ranks x accum 8 = the same global batch 64 that 16 ranks x accum 4
# gave. accum 8 is proven safe under the memory law (accum 16 dies; 8 ran 450
# steps on arm A). One node schedules into gaps that a 2-node request waits
# behind, which matters on a cluster that has been fully allocated all day.
#
# WALL: 7h (user decision), not the 4h first proposed. Measured: the 16-GPU
# Bs-LoRA run took 2:54:36. Half the ranks doubles that to ~5:49, and this
# corpus is 14% larger (6,385 samples vs 5,586), giving ~6:38 -- so 7h is a
# 5% margin. A 4h wall would have killed it two thirds of the way through.
# If it does hit the wall, --save_steps 30 means the last checkpoint is at
# most 30 steps of work behind, and the run is resumable rather than lost.
#
# DATA: the r5 corpus -- curate rev2 + canonicalised endings, rebuilt after
# three defects were fixed (tail truncation that cut real actions, poisoned
# pixels inherited through --image-cache, and a rewrite that re-tripped
# looks_infeasible). Every sample carries terminal_mode and rescued in its
# meta, so a post-hoc question about which repair path helped can be answered.
umask 077
set -x
B=/gpfs/scrubbed/jy050706/sft
DS1=$B/data/q38-Bhqs2t-r5np-v11100
DS2=$B/data/q38-Bhqs2t-r5np-v11500
export PATH="$HOME/.local/bin:$PATH"
cd $B/runcwd && source $B/venv/bin/activate
export CUDA_HOME=$B/cuda13 PATH="$B/cuda13/bin:$PATH"
export LD_LIBRARY_PATH="$B/cuda13/lib64:$B/cuda13/lib:${LD_LIBRARY_PATH:-}"
export NCCL_P2P_DISABLE=1
export PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True'
export IMAGE_MAX_TOKEN_NUM=2048
for DS in $DS1 $DS2; do
python - "$DS" <<'PY' || { echo "PREFLIGHT FAILED — aborting"; exit 1; }
import json, os, sys
ds = sys.argv[1]; bad = tot = 0
for line in open(os.path.join(ds, "train_swift.jsonl"), encoding="utf-8"):
    if not line.strip(): continue
    for p in json.loads(line).get("images", []):
        tot += 1
        if not os.path.isabs(p) or not os.path.exists(p):
            bad += 1
            if bad < 4: print("UNRESOLVED:", p)
print(f"preflight {ds}: {tot} image refs, {bad} unresolved")
sys.exit(1 if bad else 0)
PY
done
REPORT=none; RUN_NAME=q38Bhqs2t-loranp-${SLURM_JOB_ID}
if [ -f "$B/wandb.env" ]; then set +x; source "$B/wandb.env"; set -x
  export WANDB_PROJECT="${WANDB_PROJECT:-cua-sft}"; REPORT=wandb; fi
export WANDB_NOTES="Bhqs-2-terminal under LoRA, 1 node. LoRA hyper-parameters copied verbatim from Bs-lora (235948); corpus is the only variable. 8 ranks x accum 8 = global batch 64."
export B DS1 DS2 REPORT RUN_NAME
export MASTER_ADDR=$(scontrol show hostnames "$SLURM_JOB_NODELIST" | head -n1)
export MASTER_PORT=29500 NNODES=1 NPROC_PER_NODE=8
echo ">>> single node: $SLURM_JOB_NODELIST (8 GPUs x accum 8 = global 64)"
srun --ntasks=1 --ntasks-per-node=1 --kill-on-bad-exit=1 bash -c '
  export NODE_RANK=$SLURM_NODEID
  echo ">>> node $SLURM_NODEID ($(hostname)) launching NPROC=8"
  swift sft \
    --model $B/models/Qwen3.5-4B \
    --dataset $DS1/train_swift.jsonl $DS2/train_swift.jsonl \
    --enable_channel_loss true \
    --tuner_type lora --lora_rank 32 --lora_alpha 64 --lora_dropout 0.05 \
    --target_modules all-linear \
    --preserve_thinking true \
    --loss_scale last_round --gradient_accumulation_steps 8 \
    --attn_impl sdpa --deepspeed zero2_offload \
    --torch_dtype bfloat16 \
    --num_train_epochs 3 --per_device_train_batch_size 1 \
    --learning_rate 1e-4 --warmup_ratio 0.1 \
    --max_length 65536 --gradient_checkpointing true \
    --save_strategy steps --save_steps 30 --save_total_limit 12 \
    --logging_steps 2 \
    --report_to $REPORT --run_name $RUN_NAME \
    --output_dir $B/out/q38Bhqs2t-loranp
'
echo "EXIT_q38Bhqs2t_loranp $?"
