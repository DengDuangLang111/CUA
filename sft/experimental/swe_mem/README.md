# SWE-MeM rollout-balanced SFT experiment

This directory is intentionally isolated from the production builder, existing
datasets, and current sbatch files.

## Scope

The experiment reproduces only SWE-MeM Equation (3): average valid supervised
tokens inside each rollout, then average rollouts. It does **not** add SWE-MeM's
memory tool, curriculum, compression policy, GRPO objective, or step rewards.

The current CUA representation is otherwise unchanged:

- every existing step-prefix row is retained;
- the current inference-aligned screenshot/history folding is retained;
- `loss_scale=last_round` remains the base mask;
- source JSONL and images are read-only;
- the copied Swift JSONL stores absolute paths back to source images.

SWE-MeM has not released the paper-specific training code. The implementation
here follows its published equation and uses ms-swift's documented non-binary
per-message `loss_scale` path.

## Build a copied dataset

Run once over all four MixB source directories. A single global trajectory-token
mean is required; normalizing each source independently would leave V16 and V11
on different scales.

```bash
python -m ostg.sft.experimental.swe_mem.prepare_copy \
  /gpfs/scrubbed/jy050706/sft/data/mixB-swemem \
  --source-dir /gpfs/scrubbed/jy050706/sft/data/v16-main \
  --source-dir /gpfs/scrubbed/jy050706/sft/data/v16-pilot \
  --source-dir /gpfs/scrubbed/jy050706/sft/data/v11new-500 \
  --source-dir /gpfs/scrubbed/jy050706/sft/data/v11new-all \
  --tokenizer /gpfs/scrubbed/jy050706/sft/models/Qwen3.5-9B
```

The output directory contains:

- one `*_train_swift_abs.jsonl` per source build;
- optional `*_val_swift_abs.jsonl` files;
- one trajectory-weight audit JSONL per split;
- `swemem_report.json` with equalization checks;
- `SOURCE_DIRS.txt` recording the four immutable source builds.

## Required training delta

Use a copied sbatch and point its four dataset paths at the four weighted JSONL
files in `mixB-swemem`. Keep every other model/data/optimizer argument fixed
and add:

```text
--is_binary_loss_scale false
```

Keep:

```text
--loss_scale last_round
```

Without `--is_binary_loss_scale false`, ms-swift silently drops non-binary
message weights and the experiment becomes identical to the baseline.

## Smoke test

```bash
PYTHONPATH=. python -m sft.experimental.swe_mem.test_prepare_copy
```

Before launching GPUs, require `max_abs_equalization_error` in every generated
report to be near floating-point zero, and inspect the min/median/max weights for
unexpected outliers.
