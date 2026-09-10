#!/bin/bash
#SBATCH --job-name=sft-q38Bhqs2t-gb64
#SBATCH --account=video
#SBATCH --partition=gpu-h200
#SBATCH --qos=normal
#SBATCH --nodes=2
#SBATCH --gpus-per-node=8
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=64
#SBATCH --mem=600G
#SBATCH --time=04:00:00
#SBATCH --output=/gpfs/scrubbed/jy050706/sft/sft_q38Bhqs2t_gb64_%j.out
# Arm Bhqs-2-terminal: evidence-based curation (rev2) PLUS canonicalised
# endings. Corpus = 376 trajectories: 227 clean passes, 84 flagged-but-
# unconvicted passes (suspicion alone never drops a trajectory), 65 rescues
# that survived an adversarial defence of their checker (84 of 149 rescue
# rulings did NOT survive it). Every ending now parses as an explicit
# terminate(success) whose justification the writer produced for that task;
# 35 stalled tails were truncated to where the work actually stopped.
# Same 16xH200 / global batch 64 / lr 1e-5 / 3ep / wd 0.0 / beta2 0.999 as
# Bs-gb64, so the corpus is the only variable -- but it carries TWO changes
# (curation and endings), because the plain rev2 arm was skipped to save
# eval slots. A decomposition needs that arm later.
# Original Bhqs header follows.
# Arm Bhqs-gb64: EXACT twin of Bs-gb64 (235926) -- same 16xH200 shape, same
# global batch 64, same aligned optimizer, same think-cap 2048 -- with the
# corpus as the only variable: Bhqs = judge+arbitration curated
# (304 trajs / 5,367 samples vs Bs 312 / 5,586). Curation = two judge
# families agreeing (Qwen v2req >=9 + clean checklist, Opus >=8), no weak
# terminal step, plus 56 checker-bug rescues admitted by arbitration.
# First corpus built after the slug-collision fix, so it is also the first
# with provably unshared image dirs (SFT_DATA.md incident).
# Original gb128 header retained below for the memory-law rationale.
# Arm B-gb128-owo: identical to the successful 16x H200 multinode gb128
# (235513) EXCEPT the two framework-default optimizer deltas vs OpenWebRL
# are aligned too: weight_decay 0.1->0.0, adam_beta2 0.95->0.999
# (LlamaFactory defaults). After this arm, our recipe differs from their
# SFT ONLY in data shape (cross-gen teacher, 20-img window, kept thinking,
# 65k cutoff). 3 epochs, global batch 128.
# Why this shape: seven single-node attempts established two hard laws --
#   (1) per-device batch is pinned at 1 (one 65k-token/20-image sample's
#       activations + response-logits already sit at ~131 GiB of 139.79);
#   (2) memory grows ~250 MB per accumulated micro-batch (ms-swift external
#       last_round loss path retains per-microbatch logits until the
#       boundary; upstream issue #5230 family; invariant to ZeRO stage,
#       channel_loss, width). accum 4 proven (B jobs), accum 8 proven on
#       arm A (450 steps); accum >=16 dies at 137-139.
# So global 128 = 16 ranks x 8 accum is the only lawful factorization.
# NCCL_P2P_DISABLE kept (free, measured); cross-node traffic rides IB.
umask 077
set -x
B=/gpfs/scrubbed/jy050706/sft
DS1=$B/data/q38-Bhqs2t-v11100
DS2=$B/data/q38-Bhqs2t-v11500

# ---- 防撞自检 (2026-08-18) --------------------------------------------
# 曾有三份 sbatch 共用 output_dir=$B/out/q38Bhqs2t-gb64，产物名不编码语料
# 版本，事后只能靠 args.json 才分辨得出某个 checkpoint 是哪份语料训的。
# 现在每份各走各的 OUT，并在开跑前确认目录里没有别的语料的产物。
OUT=$B/out/q38Bhqs2t-gb64
for _a in "$OUT"/*/args.json; do
  [ -e "$_a" ] || continue
  grep -q "q38-Bhqs2t-v11500" "$_a" || {
    echo "FATAL: $OUT 里已有别的语料训出的产物: $_a" >&2
    echo "       换 OUT，或把旧产物移走。拒绝启动以免口径混淆。" >&2
    exit 1; }
done
mkdir -p "$OUT" && echo "$DS1 $DS2" > "$OUT/CORPUS.txt"
# -----------------------------------------------------------------------

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
REPORT=none; RUN_NAME=q38Bhqs2t-gb64-${SLURM_JOB_ID}
if [ -f "$B/wandb.env" ]; then set +x; source "$B/wandb.env"; set -x
  export WANDB_PROJECT="${WANDB_PROJECT:-cua-sft}"; REPORT=wandb; fi
export WANDB_NOTES="Bhqs-2-terminal: rev2 evidence-based curation (376 trajs = 227 clean + 84 flagged-unconvicted + 65 adversarially-survived rescues) with every ending canonicalised to an explicit terminate(success); 35 stalled tails truncated. Same gb64 recipe as Bs, corpus is the only variable."
export B DS1 DS2 REPORT RUN_NAME OUT
export MASTER_ADDR=$(scontrol show hostnames "$SLURM_JOB_NODELIST" | head -n1)
export MASTER_PORT=29500 NNODES=2 NPROC_PER_NODE=8
echo ">>> multinode: nodes=$SLURM_JOB_NODELIST master=$MASTER_ADDR"
srun --ntasks=2 --ntasks-per-node=1 --kill-on-bad-exit=1 bash -c '
  export NODE_RANK=$SLURM_NODEID
  echo ">>> node $SLURM_NODEID ($(hostname)) launching NPROC=8"
  swift sft \
    --model $B/models/Qwen3.5-4B \
    --dataset $DS1/train_swift.jsonl $DS2/train_swift.jsonl \
    --enable_channel_loss true \
    --tuner_type full --loss_scale last_round --gradient_accumulation_steps 4 \
    --preserve_thinking true \
    --attn_impl sdpa --deepspeed zero2_offload \
    --torch_dtype bfloat16 \
    --num_train_epochs 3 --per_device_train_batch_size 1 \
    --learning_rate 1e-5 --warmup_ratio 0.1 \
    --weight_decay 0.0 --adam_beta2 0.999 \
    --max_length 65536 --gradient_checkpointing true \
    --save_strategy steps --save_steps 30 --save_total_limit 12 \
    --logging_steps 2 \
    --report_to $REPORT --run_name $RUN_NAME \
    --output_dir $OUT
'
echo "EXIT_q38e3B_gb128 $?"
