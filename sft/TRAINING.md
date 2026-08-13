# Training on Tillicum — environment, flags, and what the smoke test taught

Everything here was established empirically on 2026-08-13 by a ladder of
1-GPU smoke jobs (each < $1, minutes to verdict). The sbatch that encodes all
of it lives at `/gpfs/scrubbed/jy050706/sft/smoke.sbatch` and doubles as the
template for real runs.

## Layout

```
/gpfs/scrubbed/jy050706/sft/
├── venv/                 uv-managed Python 3.11 (login node has only 3.9)
├── models/Qwen3.5-4B/    student weights (hf download, on a compute node)
├── data/<set>/           train_swift.jsonl + images/, shipped from WSL by tar
├── out/                  runs
├── wandb.env             OPTIONAL, chmod 600, user-created (see below)
└── smoke.sbatch          the template
```

**Policy rule: the login node only edits files and submits jobs.** Package
installs, model downloads, and training all run inside the sbatch on a
compute node. Short jobs (≤1.5 h) backfill in seconds even when the queue
holds hundreds of 5 h+ jobs.

## The environment recipe (why each pin exists)

| requirement | reason |
|---|---|
| `uv venv --python 3.11` | system python is 3.9; uv fetches a managed interpreter, no sudo |
| **ms-swift from git main** | PyPI 4.4.2 crashes on `SftArguments.logging_dir` with transformers 5.x — Qwen3.5 support effectively lives on main (the best-practices doc is built from 4.5.0.dev0) |
| `transformers>=5.9` | minimum for the `Qwen3_5ForConditionalGeneration` arch |
| `qwen_vl_utils>=0.0.14` + `torchvision` | VL processor imports both; neither is pulled by ms-swift |
| `flash-linear-attention` + `causal-conv1d` (git, `--no-build-isolation`) | Qwen3.5 is a hybrid linear-attention arch; guarded with `|| WARN` — transformers has a slow fallback |
| `peft liger-kernel wandb` | best-practices list + logging |
| skipped: vllm, deepspeed, flash-attn | inference-only / multi-GPU-only / 20-min compile with an sdpa fallback — none needed for single-GPU SFT |

A **preflight block** runs before the trainer: import chain, AutoConfig +
AutoProcessor on the student, open one dataset row and one image. It converts
"25 minutes to an obscure crash" into "seconds to a named failure".

## Flags that carry decisions (not defaults)

| flag | value | why |
|---|---|---|
| `--tuner_type` | `full` | 4.x renamed `--train_type`; full-parameter on the 4B |
| `--loss_scale` | `last_round` | one sample per step, loss ONLY on the final assistant turn (sft/CONTEXT.md §6); swift@main auto-combines `+ignore_empty_think` |
| `IMAGE_MAX_TOKEN_NUM` | `2048` | our screenshots are 1920×1088 ≈ 2040 visual tokens; the official example's 1024 would DOWNSAMPLE training images relative to the rollout — exactly the train/infer mismatch this pipeline exists to prevent |
| `--max_length` | `65536` | late-step samples carry up to 20 images ≈ 50k+ tokens; 32k would truncate them |
| `PYTORCH_CUDA_ALLOC_CONF` | `expandable_segments:True` | long-sequence fragmentation |

## The smoke ladder (what each round caught)

| round | time | caught |
|---|---|---|
| 226592 | 4 min | `--train_type` renamed to `--tuner_type` in swift 4.x |
| 226598 | 24 s | missing `qwen_vl_utils` |
| 226601 | 56 s | missing `torchvision` |
| 226607 | 44 s | swift 4.4.2 ↔ transformers 5.15 incompatible (`logging_dir`) |
| 226619 | 9 min | reached training; step-2 OOM (fp32 Adam states on-GPU); 1-GPU sdpa = 322 s/it |
| 226647 | 8 min | 2×GPU zero2: still OOM at step 2; but 85 s/it (3.8× from data parallel) |
| 226652 | 42 s | zero2_offload needs nvcc (DeepSpeedCPUAdam JIT) — no toolkit anywhere on the cluster |
| **226656** | 14 min | **SMOKE_EXIT 0** — micromamba user-space CUDA 13 unblocked cpu_adam; loss 0.82→0.08 over 8 steps |

**The proven full-run stack**: 2×H200 · `NPROC_PER_NODE=2` · `--deepspeed
zero2_offload` (CPU Adam via the micromamba toolchain) · sdpa (~90 s/it;
flash-attn deferred — no wheel for torch2.13+cu130, compile now unblocked if
needed) · `IMAGE_MAX_TOKEN_NUM=2048` · `max_length 65536`.

Lesson recorded at user's insistence, deservedly: rounds 2–4 were
one-missing-package-per-round whack-a-mole. The complete dependency set was
sitting in the official Qwen3.5 best-practices page the whole time — **read
the model family's own docs before the first submit, then smoke-test.**

## wandb

The template sources `/gpfs/scrubbed/jy050706/sft/wandb.env` when it exists
and falls back to `--report_to none` otherwise. To enable, the user (not the
agent — keys stay out of shell history and transcripts) runs once:

```bash
cat > /gpfs/scrubbed/jy050706/sft/wandb.env <<'ENV'
export WANDB_API_KEY=<your key>
export WANDB_PROJECT=cua-sft
ENV
chmod 600 /gpfs/scrubbed/jy050706/sft/wandb.env
```

Runs then appear under project `cua-sft`, named `smoke-<jobid>` /
`<run name>`.

## Observability (added after the smoke, before the full run)

- **Task-level val split** — `build.py --val-ratio 0.15` holds out whole
  slugs (never steps of a training trajectory); a requested split can never
  come back empty. Export emits `val_swift.jsonl`; train.sbatch passes
  `--val_dataset`.
- **Per-domain loss** — every exported row carries `channel` = task domain;
  `--enable_channel_loss true` gives one loss curve per application in wandb.
- **Truncation counter** — `over_length_estimate` in report.json counts
  samples whose estimated tokens exceed `--length-budget` (65536): those
  targets get trainer-truncated and should stay ~0.
- **Action metrics** — `eval_actions.py CKPT SAMPLES_DIR --wandb-project
  cua-sft`: greedy generation on the val panel, reports
  `action_type_acc` / `coord_mae` (0–999 space) / `think_len_ratio` plus a
  teacher-vs-student wandb Table. Zero-shot baseline of the untouched student
  logged as run `eval-base-qwen3.5-4b`.
- **Provenance** — train.sbatch writes the dataset name + report.json digest
  into `WANDB_NOTES`.

Full-run entrypoint: `sbatch train.sbatch /gpfs/scrubbed/jy050706/sft/data/<full-set>`.

## Zero-shot baseline (eval-base, job 226724)

The untouched Qwen3.5-4B on the 29-sample v500 val panel:
**action_type_acc 0.759 · coord_mae 239 (0–999 space, ~a quarter of the
screen) · think_len_ratio 0.99**. Reading: the base model already knows WHAT
to do; it does not know WHERE — grounding is the gap SFT must close. Run:
wandb `eval-base-qwen3.5-4b` (53bxw0e5).

## Pilot-0 = debug dry-run (job 226788 + dependent eval 226789)

Same config as pilot-1, fired immediately on the material available at 07:05
(v11-legacy 706 + v11-500-partial 298 ≈ 1000 samples, 47 traj) against a
hard-linked snapshot `v11-500-partial-debug` — isolation from pilot-1's
08:45 rebuild, which rm-rf's the live partial dir while this run would still
be lazily reading images from it. Purpose: debug the first real outing of
multi-dataset + `--val_dataset` + `--enable_channel_loss` two hours before
the run that counts. Its dependent eval doubles as an early Δ reading.

## Pilot-1 (2026-08-13, scheduled 08:45 PT)

Material: `v11-legacy` (39 traj → 706 train + 127 val) + `v11-500-partial`
(rebuilt at fire time from whatever the live rollout has passed — ~10 traj
expected). Scale check: OpenWebRL-4B initialized from **0.4K trajectories**
before RL (arXiv 2606.02031), so ~50 trajectories is a legitimate pilot, an
order below their init, two below CUA-Gym's 3,578-trajectory warm-up.
The pilot's deliverable is the evidence chain, not the best model.

Automation: `pilot_chain.sh` (WSL) sleeps 2 h to let the rollout accumulate,
rebuilds + ships the partial set, submits `pilot.sbatch` (1 epoch, ~70 steps,
eval every 20, checkpoints every 40), and arms `evalpilot.sbatch` as a Slurm
`--dependency=afterok` job: when training succeeds, the newest checkpoint
takes both val panels (29-sample v500 panel + 40-sample legacy panel) and
logs `pilot1-eval-*` runs next to the `eval-base-qwen3.5-4b` zero-shot
baseline. Expected wall clock: rebuild 08:45 → train done ~11:00 → eval done
~11:45 PT, all in wandb project `cua-sft`.

Curation calibration vs OpenWebRL §4.2 (read 2026-08-13): they teacher-roll
Qwen3-VL-235B×4 per task, judge with GPT-4.1, then keep only the SHORTEST
success per task group, capped per website → 412 trajectories for a 4B
student. Ours differs by design: programmatic judging, within-trajectory
cleaning instead of between-trajectory selection, diversity engineered at
generation time. Borrow list when we do multi-rollouts: keep-shortest-pass
curation switch; stronger teacher for failed tasks; few epochs (their
"avoid excessive imitation" warning).

## RECIPE v1 — the frozen command template (2026-08-13)

**Rule: every training run uses this template verbatim.** The only things
that vary are the lines marked `# VARIES`. Changing anything else requires a
new `RECIPE v2` block here with a rationale — never an in-place edit, or
runs stop being comparable.

```bash
#SBATCH --account=video --partition=gpu-h200
#SBATCH --nodes=1                      # REQUIRED: --gpus alone lets Slurm
#SBATCH --gpus=2                       # scatter GPUs across nodes (killed a run)
#SBATCH --cpus-per-gpu=8 --mem=200G

source $B/venv/bin/activate
export CUDA_HOME=$B/cuda13 PATH="$B/cuda13/bin:$PATH"

PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True' \
IMAGE_MAX_TOKEN_NUM=2048 \
NPROC_PER_NODE=2 \
swift sft \
  --model $B/models/Qwen3.5-4B \
  --dataset <TRAIN_JSONL...>           # VARIES: dataset files \
  --val_dataset <VAL_JSONL...>         # VARIES: matching val files \
  --enable_channel_loss true \
  --tuner_type full --loss_scale last_round \
  --attn_impl sdpa --deepspeed zero2_offload \
  --torch_dtype bfloat16 \
  --num_train_epochs 1 --per_device_train_batch_size 1 \
  --learning_rate 1e-5 --warmup_ratio 0.05 \
  --max_length 65536 --gradient_checkpointing true \
  --eval_steps 20 --save_steps 40 --save_total_limit 2 \
  --logging_steps 2 \
  --report_to wandb --run_name <RUN_NAME>   # VARIES \
  --output_dir $B/out/<RUN_NAME>       # VARIES
```

Evaluation pairs with it, always both:
```bash
python $B/eval_actions.py <CKPT> <SAMPLES_DIR> --limit N \
    --wandb-project cua-sft --run-name <RUN_NAME>-eval-<panel>
```
against the SAME two panels every time (v500 val, legacy val), so numbers
line up across runs and against `eval-base-qwen3.5-4b`.
