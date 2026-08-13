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

## Pilot-2 prep (2026-08-13, awaiting user approval to launch)

**Builder v2 filters** (calibrated as-judge on all 51 passing trajectories,
zero false positives on clean ones): mid-episode identical runs >=8 drop all
but the first attempt; cap-hitting trajectories get a low-diversity-tail cut
(<=3 distinct actions, >=8 steps). Result: 841 train + 133 val samples
(legacy 609+125, partial 232+8); 413 loop-junk steps removed (~30%).

**Data transfer standard** (after two failed patterns): pack ONE tar,
`rsync --partial --inplace --info=progress2` the single file (608 MB in
44 s), untar into `.staging/`, verify file counts, atomic `mv`, then
`cp -al` frozen per-run snapshots. Progress must always be visible
(`tail -f logs/...`). Never mutate a dataset dir a queued/running job
references; jobs point only at snapshots (`*-snap-<run>`).

**Shipped-data audit** (run on the snapshots, 2026-08-13): zero hallucinated
actions left in targets; all referenced images exist at 1920x1088; zero
duplicate (task, step) pairs; train/val task overlap zero in both sets;
legacy's 39 initial frames from recording.mp4 flagged in meta.

Params for approval: pilotS = RECIPE v1s (full, 1 GPU, zero2_offload,
lr 1e-5) and pilotL = RECIPE v1L (LoRA r32 a64, 1 GPU, lr 1e-4), both:
effective batch 8, 1 epoch (~130 steps), eval every 20, checkpoints every
40 keep 3, wandb + channel loss, dependent action-metric evals on both
fixed panels. Sources backing each value: swift Qwen3.5 best-practices,
Unsloth Qwen3.5 guide, OpenWebRL released SFT config.

## Data persistence on Tillicum (standing policy)

Datasets LIVE on `/gpfs/scrubbed/jy050706/sft/data/` — the shared parallel
FS every compute node mounts, so training reads them in place; nothing is
ever re-shipped for a new run. Layout and lifecycle:

- `v11-legacy/` — **frozen forever** (its campaign is closed; 39 traj,
  609+125 samples). Never rebuilt.
- `v11-500-partial/` — refreshed as the rollout produces passes, via
  `refresh_partial.sh` (WSL): rebuild -> ONE tar -> rsync single stream with
  visible progress -> md5 + file-count verify -> `.staging` -> atomic swap.
  Replaced by `v11-500-full/` when the 444-task rollout completes.
- `*-snap-<run>/` — per-run hardlink snapshots (`cp -al`, instant, ~zero
  disk). Every training job reads ONLY its snapshot; live dirs are free to
  refresh at any time. Snapshots are deleted only after their run's jobs
  finish.

## Pilot-2 launch record (2026-08-13 ~09:00 PT, user-approved)

pilotS=226918 (full, RECIPE v1s) and pilotL=226920 (LoRA, RECIPE v1L), both
on snapshots of 916 train + 151 val (56 trajectories), effective batch 8,
1 epoch = 115 steps, ckpt every 40 keep 3, dependent action-metric evals
armed. The chain-submitted 2-GPU pilot1 (226915) was cancelled: redundant
with pilotS and predates the snapshot-isolation rule.

## RUN LEDGER — standing rule: every launch appends a row here, no exceptions

Smoke ladder rounds (226592-226656) are tabulated in their own section above.

| job | date | recipe | data (version) | outcome | wandb / artifacts |
|---|---|---|---|---|---|
| 226724 eval-base | 08-13 | zero-shot exam | v500 val panel (29) | **baseline: type_acc 0.759 · coord_mae 239 · think 0.99** | runs/53bxw0e5 |
| 226788 pilot0 | 08-13 | v1 full 2-GPU | v1 filters, 1004 | ✗ Slurm scattered GPUs across nodes (fix: `--nodes=1`) | — |
| 226802 pilot0b | 08-13 | v1s full 2-GPU | v1 filters | cancelled: superseded by 1-GPU arms | — |
| 226860 pilotL / 226862 pilotS | 08-13 | v1L / v1s, 1-GPU | v1 filters, live dirs | ✗ **killed by in-place data reship at ~26 min** — origin of the isolation rule | — |
| 226915 pilot1 | 08-13 | v1 full 2-GPU (chain) | v2 но live dirs | cancelled: redundant + pre-isolation | — |
| **226918 pilotS** | 08-13 | **v1s full 1-GPU, lr 1e-5, offload** | **v2 snapshots: 916+151 (56 traj)** | ✗ scancelled: deepspeed preset silently set eff. batch 16 (approved: 8) → replaced by 226922 | [runs/mk2kibr5](https://wandb.ai/yanjiayuan/cua-sft/runs/mk2kibr5) |
| **226920 pilotL** | 08-13 | **v1L LoRA r32, lr 1e-4** | same snapshots | ✓ — outcome row below | [runs/0f02foqj](https://wandb.ai/yanjiayuan/cua-sft/runs/0f02foqj) · adapters `out/pilotL/v*/checkpoint-*` |
| 226919 / 226921 evals | 08-13 | fixed two-panel exam | v2 snapshot panels | 226919 fell with 226918; 226921 ran — outcome row below | pilotS-eval-* / pilotL-eval-* |

| 226922 pilotS | 08-13 | v1s + explicit accum 8 | v2 snapshots | ✓ EXIT 0, 115 steps, final eval_loss 0.513 — replaces 226918 (deepspeed silently set eff. batch 16, violating approved 8) | run pilotS-226922 · `out/pilotS/v2-20260813-090458/checkpoint-115` |
| 226920 pilotL | 08-13 | v1L LoRA r32 lr 1e-4 | v2 snapshots | ✓ EXIT 0, 115 steps, final eval_loss 0.459 | run pilotL-226920 · `out/pilotL/v1-20260813-085916/checkpoint-115{,-merged}` |
| 226927 eval-base2 | 08-13 | zero-shot exam, v2 snapshot panels | 26+40 samples | ✓ v500: acc 0.731 · MAE 380.3 · think 1.10 / legacy: 0.775 · 123.3 · 0.925 — **the old baseline (226724) took a v1-era panel; deltas must compare same-exam only** | eval-base2-* |
| 226921 evalpilotL | 08-13 | two-panel exam on ckpt-115-merged | v2 snapshot panels | v500: acc 0.654 · MAE 414.1 · think 0.0 / legacy: 0.800 · 192.2 · 0.0 — **numbers unreliable, see forensics below** | pilotL-eval-* |
| 226923 evalpilotS | 08-13 | two-panel exam on ckpt-115 | v2 snapshot panels | v500: acc 0.731 · MAE 389.9 · think 0.0 / legacy: 0.775 · 182 · 0.0 — **numbers unreliable, see forensics below** | pilotS-eval-* |
| 227162 probe | 08-13 | raw-generation forensics, 3 models x 4 samples | v2 snapshot panels | ✓ all three models reason fully; see forensics | `proberaw_227162.out` |

## Pilot-2 forensics (2026-08-13 afternoon): think=0.0 was the exam, not the model

Symptom: both trained arms scored think_len_ratio 0.0 on all panels; coord_mae
flat-or-worse vs baseline. Full-chain investigation (swift source + training
label dumps + jinja rendering + raw-generation probe 227162), receipts:

1. **Training was healthy.** pilotS label dump (`pilotS_226922.out`, [LABELS]):
   `[-100 * 5492]` then `<think>\n...full reasoning...</think>\n\n<tool_call>...
   <|im_end|>` — last round only, think fully supervised, no image-pad leakage.
   `ignore_empty_think` only zeroes EMPTY think (`^<think>\s*</think>`), never
   fires on our non-empty targets. (Beware reading these logs with Python
   `readlines()`: tqdm `\r`s split lines differently than sed/grep — extract by
   marker, not line number.)
2. **But swift and the HF jinja disagree on two conventions.**
   (a) History think: swift's `_get_preserve_thinking` (template/base.py:171)
   forces preserve=False under is_thinking + last_round + training, so
   `_remove_history_thinking` STRIPS `<think>` from history assistant turns;
   the model's own jinja (= eval AND future student rollout) KEEPS them
   (verified: real val sample renders 4 `<think>`, 3 from history).
   NOTE the campaign runner did NOT pass `--preserve_thinking` (live cmdline;
   dir is even named `think-nopreserve`) — and it made no difference: both
   3.5/3.6 jinjas compute `last_query_index` by skipping user turns that are
   pure `<tool_response>` blobs, so in our instruction-then-tool_responses
   structure every assistant turn sits after the last real query and the
   keep-branch fires unconditionally. The teacher DID see full history think;
   the flag only matters for mid-conversation human queries, which we never
   have. (Agent side keeps it too: `_response_transform =
   ensure_empty_think_prefix`, history.py:90 — preserves existing think,
   only pads an empty one when absent.)
   (b) Open tag: swift trains it target-side (first supervised token); the
   jinja generation prompt appends `<think>\n` prompt-side.
3. **think=0.0 on trained models = artifact of (b).** The exam regex demanded
   an opening `<think>` inside the generated text; trained models don't re-emit
   it (it's in the prompt). Probe 227162: both arms produce full coherent
   reasoning then `</think>` then a well-formed tool_call, and stop cleanly.
4. **Baseline think 0.93-1.10 = a different artifact.** Base fails to
   terminate its turn in 3/4 probes and hallucinates fake `user`/`assistant`
   continuation rounds; the literal `<think>` the regex matched lives in those
   hallucinated rounds. The trained models' clean turn-ends are an
   IMPROVEMENT the old metric scored as collapse.
5. **coord_mae comparisons are void**: trained models sat an out-of-format
   exam (history think present at eval, absent in training); base sat an
   in-format one. Regression is unproven either way until re-exam.

Fixes: `eval_actions.py` think parsing is now tag-position-agnostic (first
`</think>`, guarded against post-action rounds) and the wandb Table stores
raw student text — parsed-only logging is why this took a dig instead of a
glance. Training fix = RECIPE v2 below (`--preserve_thinking true`), aligning
training context with the jinja that both the exam and the deployed student
will use.

## RECIPE v2 — FROZEN 2026-08-13 (user-approved, full arm only)

Delta vs v1s/v1L, everything else byte-identical:

```
  --preserve_thinking true      # keep history <think> in training encoding;
                                # matches teacher context + jinja rendering
                                # at eval + rollout
```

Naming trap, for the record: this swift flag is NOT the runner's
`--preserve_thinking`. The runner flag (OFF in the campaign) asks the vLLM
template to keep history think — a no-op for our message shape, where the
template's multi-step-tool branch keeps it unconditionally. The swift flag
controls training encoding, whose default STRIPS. Align the rendered
behavior (keep), not the flag values.

Approved scope: full-FT arm only ("跑一个全量的微调, 数据保持和之前一样").
LoRA v2 arm not launched. Data = the frozen pilot-2 snapshots verbatim —
no rebuild, no reship; they are read-only with no writer (rebuilds only
ever touch live dirs), which honors the isolation rule's intent.

Re-exam: same two v2 snapshot panels, FIXED eval_actions (think parsing is
tag-position-agnostic + raw text logged); baseline retakes the same fixed
exam (same-exam rule). Old pilot2 exams: acc/MAE columns remain valid
(ACTION/COORD parsing unchanged), think column void.

| job | date | recipe | data (version) | outcome | wandb / artifacts |
|---|---|---|---|---|---|
| 227162 probe | 08-13 | raw-gen forensics | pilot2 snapshot panels | ✓ see forensics section | proberaw_227162.out |
| **227303 pilotS3** | 08-13 | **v2 full 1-GPU (v1s + preserve_thinking)** | frozen pilot2 snapshots verbatim | SUBMITTED (on g001 within a minute) | run pilotS3-227303 · `out/pilotS3/` |
| 227304 evalpilotS3 | 08-13 | fixed two-panel exam | pilot2 snapshot panels | armed, afterok:227303 | pilotS3-eval-* |
| 227305 eval-base3 | 08-13 | baseline retake, fixed exam | pilot2 snapshot panels | ✓ v500: acc 0.731 · MAE 371.6 · think 1.02 (n=26) / legacy: 0.775 · 123.0 · 1.00 (n=40). acc identical to the broken-parser run (cross-check ✓); think now measures real first-round reasoning; **MAE 380.3→371.6 across two identical zero-shot runs = the ±9 run-to-run noise floor** | base3-eval-* |
| — pilotS3 train outcome | 08-13 | v2 | frozen pilot2 snapshots | ✓ EXIT clean, 115 steps, ~44s/step. eval_loss 0.294/0.290/0.279/0.273 @ 20/40/60/80 — monotone, vs v1s flat 0.528→0.513. best = checkpoint-115 | `out/pilotS3/v0-20260813-125631/` |
| **227714 serve-35s** | 08-13 | vLLM serve pilotS3 ckpt-115, ckpt's own template, 1 GPU 8h | — | QUEUED (job name eval35; tunnel WSL:18002) | `qwen-serve/serve-35s.sbatch` |
| **tier-3 valpanel driver** | 08-13 | student rollout: 9 held-out val tasks × 3 attempts, 3 envs, **ms50** (user), temp 0.6, WAIT-break 10 | merged exam dir `OSWorld/eval_valpanel_tasks` (2 tasks from v11-500-final + 7 from **v11-all** — the corpus the legacy teacher run actually read; note: discharge-summary has 3 divergent versions across run dirs, we use v11-all's = the version the teacher's pass was judged under) | RUNNING (444 rollout paused for it — teacher serve had died at its 12h wall anyway, replacement 227448 queued; driver auto-restores the 444 runner @3 envs once :18001 answers) | `osworld-verified-control/valpanel_driver.sh` + logs/valpanel_driver.log |

| 227304 evalpilotS3 | 08-13 | fixed two-panel exam on ckpt-115 | pilot2 snapshot panels | ✓ v500: acc 0.577 · MAE 311.3 · think 0.918 (n=26) / legacy: **acc 0.800** · MAE 130.3 · think 1.00 (n=40). See reading below | pilotS3-eval-* |

| 227829 pilotS3e23 | 08-13 | continue-train from ckpt-115 +2 epochs, **warm restart** (fresh warmup+cosine) | same snapshots | ✗ cancelled at step 32: the fresh warmup (8.3e-7→1e-5 over 12 steps) confounds the epoch comparison — grad_norm rise and eval_loss 0.273→0.325 are partly restart artifacts, not epoch effects. Replaced by a single 3-epoch schedule | — |
| **228092 pilotS3x3** | 08-13 | **RECIPE v2, single 3-epoch schedule from base** (one warmup + one cosine over 345 steps), ckpts at every epoch boundary 115/230/345 | same frozen pilot2 snapshots | RUNNING g002 (interactive QOS) | `out/pilotS3x3/` |
| 228093 eval-pS3x3 | 08-13 | fixed exam on all three epoch ckpts × both panels → clean epoch-response curve | pilot2 snapshot panels | armed, afterok:228092 | pilotS3x3-ep{1,2,3}-eval-* |
| **tier-3 attempt 1** | 08-13 | pilotS3 ckpt-115 served on vLLM (own template), 9 held-out val tasks, ms50, temp 0.6, 3 envs | `eval_valpanel_tasks` (9 tasks the teacher passed 9/9) | **1/9 pass (arxiv-listing, 6 steps)** — see failure-mode table below | `results_generated/qwen35-4b-pilotS3/valpanel-a1` |

### Tier-3 first result: 1/9, and 7 of the 8 failures are ONE pathology

| task | score | steps | distinct actions | max repeat | teacher steps |
|---|---|---|---|---|---|
| arxiv-listing | **1.0** | 6 | 5 | 2 | 4 |
| chrome-downloads | 0 | 50 | **1** | 50 | 27 |
| spectra-loader | 0 | 50 | **1** | 50 | 14 |
| vscode-telemetry | 0 | 50 | 2 | 48 | 50 |
| discharge-summary | 0 | 50 | 7 | 42 | 24 |
| exam-kiosk | 0 | 50 | 10 | 18 | 34 |
| gdpr-art17 | 0 | 50 | 4 | 17 | 8 |
| depot-bookmark | 0 | 50 | 6 | 11 | 33 |
| store-hours | 0 | 12 | 10 | 3 | 13 |

**The pathology: the model copies its own previous response instead of reading the
current screenshot.** Receipt (chrome-downloads): the response at steps 1, 2, 3
and 25 is byte-identical — same `<think>` text ("屏幕左侧有一个Chrome图标，点击它
应该可以启动浏览器"), same coordinate — while the screenshots demonstrably change
(3 distinct screens among the sampled steps; Chrome had already opened).

Mechanism: the teacher's step 2 on this task is `wait` (let Chrome load); the
student clicks again instead. An unchanged screen produces an identical
response, two identical assistant turns enter the history, and in-context
pattern lock makes every later step a copy — even after the screen changes.

**This is the same defect the action exam saw as "phase lag"** (student's step-k
answer = teacher's step k−1 = the last assistant turn in its context). In
teacher-forced mode it copies the teacher's last turn; in closed loop it copies
its own. My exam-time reading — "phase lag self-corrects in closed loop" — was
WRONG, and the rollout is what proved it. Recording that: single-step exams
cannot see compounding; only tier 3 can.

**It is NOT taught by repeated-action training data.** Measured on the shipped
training set: of 873 samples with a previous assistant turn, only **15 (1.7%)**
have a target identical (action + coordinate) to the previous step; 290 (33%)
share only the action *type*, which is normal GUI behavior. The
`identical_runs` / `low_diversity_tail` filters did their job. Alignment is not
off-by-one either: `lib_run_single.py` writes `screenshot_file` AFTER
`env.step()`, and build.py uses `[initial] + steps[:-1]` screenshots, so the
last image of a step-k sample is exactly the screen that step k acts on.

Live hypotheses, in order, each testable:
1. **Too little data / undertrained** — 916 samples, 115 steps. Copying gives
   perfect format + the right action type 33% of the time; it is a cheap local
   optimum. 228092 (3 epochs) tests the "more optimization" half.
2. **`preserve_thinking` may have made copying easier** — history now carries
   full prior reasoning, a richer copy source. Testable with the retained v1s
   checkpoint on the same 9 tasks.
3. **Base-model behavior** — unknown whether stock Qwen3.5-4B loops the same way;
   needs a base rollout on the same panel (VM-bound, queued behind attempts 2-3).

Engineering stopgap (not yet enabled, would change termination semantics
mid-campaign so deferred to the next one): a generic repeat-breaker — N
consecutive identical actions ⇒ terminate, N ≥ 10 — which CLAUDE.md §3.1 already
recommends. It cannot make a task pass, but it reclaims ~44 wasted steps per
locked task and would roughly halve attempt wall-clock.

### THE HEADLINE RESULT: SFT regressed the model, 4/9 → 1/9

| arm | passes | which tasks |
|---|---|---|
| teacher Qwen3.6-27B | **9/9** | (panel is built from its passes) |
| **stock Qwen3.5-4B** | **4/9** | arxiv(5 steps), exam-kiosk(28), vscode-telemetry(10), store-hours(54) |
| **SFT v2 (pilotS3)** | **1/9** | arxiv(6) |

Every proxy metric said the training was healthy: eval_loss fell monotonically
0.294→0.273 (v1 recipe was flat at ~0.52), token_acc reached 0.95+, and on the
legacy exam panel v2 scored the best action-type accuracy of any model (0.800 vs
base 0.775). **The rollout is the only tier that saw the damage.** Record this:
loss and single-step exams cannot detect a policy that has stopped looking at
its observation, because teacher forcing hands it the correct history anyway.

Why the model stopped using the screenshot — measured, not guessed:

1. **Only 0.61% of the training signal strictly requires the pixels.** Over 916
   targets (mean 587 chars): `<think>` prose 59%, action names + format
   boilerplate ~35%, coordinate tags 4.9%, and the coordinate DIGITS — the only
   tokens that cannot be produced without looking — **0.61%**. Cross-entropy is
   averaged over tokens, so in 115 optimizer steps the cheapest loss reduction
   is text modeling. The model did not forget how to see; it learned that
   seeing is worth 0.6% of the reward.
2. **`preserve_thinking` makes the text half even more predictable** (the next
   reasoning paragraph often continues the previous one), which is the honest
   cost of that otherwise-correct fix.
3. **It is NOT vision damage**: `freeze_vit: True`, `freeze_aligner: True`,
   `freeze_parameters: ['model.visual', 'model.visual.merger']` — the vision
   tower and merger were never updated. Only the LLM moved.
4. **Sharpening removes the accidental escape route.** Base, with a flatter
   output distribution, varies its clicks and stumbles out of dead ends — that
   is how it passed exam-kiosk (difficulty 5) and vscode-telemetry. The SFT
   model emits the same peaked answer for the same screen, so a stuck state is
   absorbing.

Where it locks, from the frames (two distinct modes):

- **Never engaged**: chrome-downloads and spectra-loader repeat step 1's action
  50×. The step-25 screenshot shows Chrome fully open, Google new-tab filling
  the screen, cursor on the dock icon — while the response still reads "I see a
  Chrome icon on the left sidebar, click it to open the browser". Byte-identical
  to step 1.
- **Engaged, then stuck on a fine-grained operation**: discharge-summary opens
  the document correctly, then clicks (720,401) 42× trying to drag-select the
  "Ramipril" line; exam-kiosk reaches Chrome's Autofill settings page, then
  misses "Privacy and security" by a few pixels 18×. Base passed exam-kiosk by
  varying its clicks.

Fix directions, in the order worth trying:
1. **Weight the coordinate span in the loss** (swift `loss_scale` accepts a
   regex→weight config; the same mechanism `ignore_empty_think` uses). Give
   `<parameter=coordinate>` spans 5–10× weight so grounding carries gradient
   proportional to its importance rather than to its token count.
2. **Do not over-sharpen**: LoRA, or a lower LR, to keep enough entropy that a
   repeated state can be escaped.
3. **More and more diverse data** — the text half saturates fast (token_acc
   0.97 by epoch 2); the marginal value of new trajectories lands mostly on the
   grounding 0.6%. Recovery behaviour is nearly absent from the corpus: `wait`
   is 3.4% of target actions and `terminate` 3.6%, and every trajectory is a
   teacher SUCCESS, so "you are stuck, do something else" is never demonstrated.

### The three-arm tier-3 control (2026-08-13 evening)

Same 9 tasks, same settings (ms50, temp 0.6, 3 envs, own chat template per
checkpoint), run strictly one arm at a time so they never contend for the 3 VMs:

| arm | model | what it isolates | serve | result |
|---|---|---|---|---|
| **base** | stock Qwen3.5-4B | does the stock 4B loop the same way? ⇒ is SFT the cause at all | 228108 (debug QOS, g003) | running |
| **v1** | pilotS ckpt-115 (`preserve_thinking` unset ⇒ history think stripped) | did preserve_thinking amplify the copying? | 228158 (normal QOS, g019) | queued behind base |
| **v2** | pilotS3 ckpt-115 (`preserve_thinking: true`) | — | done | **1/9** |

Teacher on this panel: 9/9 (these are val tasks split out of passing
trajectories). Sequencing is enforced in `v1_driver.sh`, whose first action is
to block on `BASE_DONE` in the base driver's log.

**Operational lesson — killing a runner leaks its containers.** The base arm
sat 10 minutes in an `EnvProcess-Restart` loop ("Checking if virtual machine is
ready…") with zero task dirs. Cause: `pkill`-ing the previous driver skipped
its own `stop_runner`, so 11 containers from the student arm survived and ate
RAM down to 4 GB free — new VMs starved at boot. `docker rm -f $(docker ps -aq)`
restored 17 GB and the arm ran normally. **Any manual `pkill` of a runner must
be followed by `docker rm -f $(docker ps -aq)`** before the next arm starts;
the result dir is resume-safe (`get_unfinished`), so a restart costs nothing.

Also noted, cluster mechanics that cost time today: two serve jobs landed on the
same node and both wanted `127.0.0.1:8000` — the second cannot bind. When
several serve jobs may be in flight, either give them distinct ports or ensure
only one is alive per node. And a nested `ssh` inside a heredoc-fed script eats
the remaining script lines unless invoked with `-n`.

### pilotS3 exam reading (per-sample forensics, 08-13 evening)

- **Legacy panel: clean.** Best acc of any model (0.800 vs base 0.775), MAE
  130 vs base 123 = inside the ±9 noise floor, thinking intact. v1s's
  format-mismatch damage on this panel (182) fully recovered.
- **v500 acc 0.577 is a metric artifact of PHASE LAG, not lost competence.**
  Per-sample: on the 18-step chrome-downloads trajectory the student runs
  exactly one step behind the teacher (its step-k answer = teacher's step
  k−1: re-issues the previous action when the screen shows no change, then
  trails the whole way). Nearly the same action SEQUENCE, shifted by one —
  every shifted step scores a type mismatch. The baseline's higher acc
  (0.731) on this panel is partly free type-matches from near-constant
  left_click spam (10/10 sampled steps), which coincides with the teacher's
  modal action type. Meanwhile MAE — computed only on type-matched pairs —
  improved 372→311 (7× the noise floor): when in phase, the student points
  closer than the base model does.
- **Panel caveat**: v500 val = only 2 tasks, so errors are correlated and
  a single de-sync poisons many samples.
- **Arbiter**: phase lag is self-correcting in closed loop (the model sees
  its own action's effect next step) — whether it matters at all is exactly
  what the running tier-3 9-task rollout measures.

Teacher-serve template note (found while cloning the serve script): the teacher
is served with `--chat-template chat_template_think.jinja`, which differs from
stock ONLY in the generation prompt: `<|im_start|>assistant\n<think>\nOkay, `
— thinking force-opened and seeded with "Okay, ". History-think keeping is
byte-identical to stock, so the forensics conclusions stand. Corollary: the
seeded "Okay, " is prompt-side, which is why no recorded teacher think starts
with it — and the student (trained without it) is correctly served WITHOUT
this override, on the checkpoint's own template.

## The action exam — protocol and how to read it (2026-08-13)

What `sft/eval_actions.py` does, exactly:

1. **Panel** = a snapshot's `val_samples.jsonl` (task-level held-out; v500
   n=26, legacy n=40). Same panels for every model, forever (same-exam rule).
2. **Per sample**: rebuild the exact context the teacher saw at that step,
   render with the model's own chat template (`add_generation_prompt=True`),
   greedy decode (`do_sample=False`), `IMAGE_MAX_TOKEN_NUM=2048` for rollout
   parity.
3. **Parse teacher and student identically**: action = first
   `<parameter=action>` name; coordinate = first `<parameter=coordinate>`
   `[x, y]`; think length = chars before the first `</think>`, invalid if a
   `<tool_call>` precedes it (tag-position-agnostic: the chat template may
   supply the opening `<think>` prompt-side — the 08-13 forensics).
4. **Metrics**:
   - `action_type_acc` — student's action name equals the teacher's.
   - `coord_mae` — mean L1 distance `|dx| + |dy|`, computed ONLY over samples
     where both sides produced coordinates AND the action types match, so
     type errors never pollute coordinate error.
   - `think_len_ratio` — median of student/teacher think length where the
     teacher thought.

Reading rules (each one learned the hard way):

- **Space**: the model-native 0–999 relative grid (the runner scales
  ×1920/999, ×1080/999 at execution). 1 unit ≈ 1.9 px horizontal / 1.1 px
  vertical; 100 units ≈ 10% of the screen span.
- **It measures agreement with the teacher, not correctness.** On an open
  step (menu vs shortcut, A-then-B vs B-then-A) a reasonable-but-different
  choice scores a huge distance. Task difficulty is tier-3 rollout success;
  MAE is a grounding-agreement proxy. Corollary: a cross-panel score gap
  (base 123 legacy vs 372 v500) proves the panels differ in composition
  (element geometry, step openness, domain mix) — NOT that one panel's
  tasks are "harder". Compare models within a panel only.
- **Noise floor: ±9 MAE units** (measured: same model, same panel, two
  independent runs → 380.3 vs 371.6; GPU nondeterminism). Under ~10 is
  noise; with n=26/40 and an outlier-sensitive mean, treat differences of a
  few tens as tentative.
- Only the FIRST action of a multi-action response is compared.

### Which number decides what

Four numbers, strictly ordered by authority. A lower row always overrides a
higher one when they disagree.

| number | what it can decide | what it can NEVER decide |
|---|---|---|
| train loss | did optimization move at all; batch-level health | success of anything — it falls under pure memorization too |
| eval_loss (held-out tasks, during training) | is the model learning transferable structure (falls) or memorizing (plateaus while train falls — v1's signature) | whether actions are usable |
| action exam (type acc / coord MAE / think) | format health; relative progress between recipes on the same panel | task capability — it scores agreement with the teacher, and a different-but-correct action scores badly |
| **rollout success rate** (tier 3: our tasks, then OSWorld-Verified) | **whether training worked. This is the acceptance criterion; everything above is a proxy for this row** | — |

Ledger row contract: job id, recipe version, data version (filter version +
sample counts + snapshot name), outcome (incl. failures and WHY), wandb link,
checkpoint path. Corollary learned today: an eval baseline is only valid for
deltas if it took the SAME exam — re-baseline whenever the panel changes.
