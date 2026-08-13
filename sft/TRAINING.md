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
