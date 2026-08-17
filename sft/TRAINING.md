# Training on Tillicum — environment, flags, and what the smoke test taught

## 现状(2026-08-16 深夜,过时即改)

- **eval-50 矩阵四行闭合(arm A 语料)**:base/keepthink **19/50=38%** >
  rich/rich **14/50=28%** ≈ ep1 快照 **13/50=26%** > lean/keepthink
  **11/50=22%**(+1 题 0.90 部分分,严口径不计)。SFT 全臂低于 base;
  lean 垫底 —— OpenWebRL 式"瘦文本史训练"在跨代跨分布设置下没有救赎力,
  渲染这条线关闭(除非后续被翻案)。50 题单 seed 幅度噪声 ±2-3 题,
  臂间 2-6 题差距只作方向证据。
- **rich/stock 在跑**(2026-08-16 20:40 自动接力):同 rich-450 权重 + 官方
  模板(历史 think 渲染剥除)= OSWorld-Verified 默认口径,serve 235405
  (:8015),与 rich/rich 成对隔离"eval 期历史 think 可见性";2×2 的
  base/stock 角待 richstock 出分后裁决要不要补。
- **B 语料三训练并行**:235322(3ep,~19h)/ 235323(1ep 独立退火)/
  **235420**(gb128 = OpenWebRL 优化域,8×H200 batch128)。gb128 前两发
  (235364/g017、235400/g014)均死于第 ~8 步 NVLink P2P "invalid
  access"——跨节点复现 = 栈级病非坏节点;8 路通信缓冲把水位吃到
  137.8/141(2 卡作业 131.9),P2P 注册在刀刃头寸上踩空。第三发
  `NCCL_P2P_DISABLE=1`(改走主机共享内存)后**同节点 g014 穿过坠机点**,
  步速无损(145.6 vs 145.9 s/it)——通信改道对本负载免费,因为一步 147s
  几乎全是计算,累积边界只搬 ~8GB 梯度。落地后按 ep1/ep3/1ep/gb128
  依次 eval,量与优化域两案分开裁决。
- OpenWebRL 对照的一手核实(含 per-turn/1 图/冻结方案/HF 公开语料)
  → `CUA/READING.md`;移植对照实验的数据来源已就位。

---

Everything below was established empirically starting 2026-08-13 by a ladder
of 1-GPU smoke jobs (each < $1, minutes to verdict). The sbatch that encodes
all of it lives at `/gpfs/scrubbed/jy050706/sft/smoke.sbatch` and doubles as
the template for real runs.

> **Published live at** https://cua-dashboard-theta.vercel.app → sidebar group
> **SFT** (Overview · Tier-3 Panel · Training runs). The panel view refreshes
> itself from `sft.json` and every cell of its task × arm matrix opens that
> arm's step player for that task. This file stays the source of truth for
> *why*; the dashboard is the source of truth for *what the numbers are right
> now*. Operating manual for the two publishing daemons: `CUA/DASHBOARD.md` §3.
> **A new arm is not reported until it is on that panel** — a number in a chat
> message is not a result anyone else can check.

---

# READ THIS FIRST — the arm registry, and what the numbers can and cannot support

This file grew chronologically and now holds fifteen arms across three datasets.
This section is the map; everything below it is the dated record, including
claims this section retracts.

## The finding that governs how to read every score below

**The 9-task panel has a variance of ±2 tasks.** Same checkpoint, same settings
(temp 0.6, top_p 0.95, top_k 20, ms50, 3 VMs), vLLM unseeded, three runs:

| arm | seed 1 | seed 2 | seed 3 |
|---|---|---|---|
| `more3` | **0/9** | **1/9** | **2/9** |
| `e3` | **3/9** | 0/6 (running) | queued |

**No individual task pass has ever reproduced.** `arxiv-listing` passed on e3
seed 1 and more3 seed 3 and nowhere else; `exam-kiosk` passed only on more3
seed 2. e3's seed 2 lost all three tasks its seed 1 had passed.

Consequence: **a difference of 1–3 tasks between arms is not a result.** Every
single-seed comparison in this file is therefore suspect, and the ones that
mattered are retracted below.

## Dataset registry — three datasets, easily confused

| name | rows | trajectories | what it is |
|---|---:|---:|---|
| `pilot2` (defective) | 916 declared, **609 loaded** | — | relative media paths; a third silently never trained. Used by v1/pilotS, v2/pilotS3, pp15 |
| `abs-pilot2` | 916 | 47 | the same corpus with absolute paths and a preflight. Used by e1, e3 |
| `abs-pilot3` | 1288 | 58 | `abs-pilot2` **plus 11 trajectories, none removed** — 10 `libreoffice_calc` + 1 `gimp`. Used by more, more3, more3np, ep5pt, ep5np, fast |

`abs-pilot3`'s added trajectories have **zero domain overlap with the 9-task
panel** (which is 5 chrome, 3 vs_code, 1 writer).

## Arm registry — every trained arm, exactly

Steps = optimizer steps at effective batch 8. Sample count sets steps/epoch, so
equal epochs do **not** mean equal optimization.

| arm | dataset | samples | epochs | steps | preserve | tier-3 (seeds) |
|---|---|---:|---:|---:|---|---|
| teacher Qwen3.6-27B | — | — | — | — | — | 9/9 *(selection, not a score)* |
| stock Qwen3.5-4B | — | — | — | — | — | 4/9 (1) |
| stock + top_k 20 | — | — | — | — | — | 4/9 (1) |
| OpenWebRL-4B-SFT | theirs | 3085 | 3 | — | — | 2/9 (1) |
| v1 · pilotS | pilot2 | 609 | 1 | 115 | unset | 1/9 (1) |
| v2 · pilotS3 | pilot2 | 609 | 1 | 115 | true | 1/9 (1) |
| v2 + presence 1.5 | pilot2 | 609 | 1 | 115 | true | 2/9 (1) |
| e1 | abs-pilot2 | 916 | 1 | 115 | true | 1/9 (1) |
| **e3** | abs-pilot2 | 916 | 3 | 345 | true | **3/9, 0/6…** (2 of 3) |
| more | abs-pilot3 | 1288 | 1 | 161 | true | 1/9 (1) |
| **more3** | abs-pilot3 | 1288 | 3 | 483 | true | **0/9, 1/9, 2/9** (3) |
| more3np | abs-pilot3 | 1288 | 3 | 483 | **false** | 1/9 (1) |
| ep5pt | abs-pilot3 | 1288 | 5 | 805 | true | 1/9 (1) |
| ep5np | abs-pilot3 | 1288 | 5 | 805 | **false** | 2/9 (1) |
| `fast` | abs-pilot3 | 1288 | 5 | 805 | true | **not evaluated** — a speed A/B twin of ep5pt (2 GPU · flash_attn · causal_conv1d), loss curves overlay ep5pt at 202 points |

## Retracted — claims this file made from single-seed comparisons

| claim | why it is withdrawn |
|---|---|
| "1288 samples at 3 epochs is clearly worse than 916 at 3 epochs" (0/9 vs 3/9) | more3 is 0/1/2 across seeds and e3's seed 2 is 0/6 so far — the gap is inside the noise |
| "the added calc data caused the regression" | the *facts* stand (zero domain overlap, 29% dilution, longer trajectories); the **gap they were invoked to explain does not exist yet** |
| "`preserve_thinking` off beats on" (1/9 vs 0/9 and 2/9 vs 1/9) | one task on a nine-task panel, twice. Inside the noise |
| "epochs are the one lever that moved the real metric" (e1 1/9 → e3 3/9) | both single-seed; e3's second seed undercuts it |

## Not retracted — what survives, and why

| finding | why variance does not touch it |
|---|---|
| **SFT arms sit below the stock model** | every one of 11 trained arms scored ≤3/9 against 4/9; the stock number should still be re-run for seeds |
| **The failure mechanism** (below, "WHY SFT makes it worse") | measured over thousands of steps, not nine binary outcomes: dead-end steps 11 (stock) vs 78 (e3) vs 114 (more3) vs 195 (e1), and repeat-rate 18% vs 90% vs 81% vs 99% |
| **Termination rate tracks success** | same — counted over every step of every episode |
| **`zero2` without CPU offload does not fit** | two OOMs at the same step, with a mechanical cause (swift's custom loss excludes liger's fused CE) |
| **The acceleration is quality-neutral** | 202 aligned logging points, sign split 106/96 |

**The standing lesson: score comparisons on this panel need ≥3 seeds, or they
are not comparisons.** Behavioural counts do not — they aggregate thousands of
decisions and separate cleanly where the scores cannot.

---

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

### Full log audit, 2026-08-13 evening (after the silent-drop defect)

A sweep of every training, exam and rollout log, looking specifically for
failures that change a conclusion without announcing themselves.

**Clean — conclusions stand:**

| check | result |
|---|---|
| v2 rollout (the 1/9) | 815 LLM requests, **815 × HTTP 200**, zero `call_llm failed` |
| v1 rollout (the 1/9) | 297 requests, all 200 |
| base rollout (the 4/9) | 58 × HTTP 400 in the log, but **all before 16:19:04**; first 200 at 16:21:58, first result written 16:23:12 — every failure predates the scored run (they are the `max-model-len` mistake, caught and fixed before scoring) |
| unhandled/hallucinated actions | 0 across all three arms |
| length truncation | `over_length_estimate` 0 (legacy) and 2 (v500) against a 65536 budget — `truncation_strategy=delete` had essentially nothing to delete |
| e1 under RECIPE v3 | **zero** `template.encode` errors (pilotS3 had 70, pilotS3x3 had 130) — the fix is confirmed in production |

**Worth knowing, not defects:**

- **The tail filter is NOT over-cutting** — the aggregate percentage misleads.
  Re-audited on the 29 passing trajectories of the current campaign (1204
  steps): the 34% of cut steps is concentrated in **6 trajectories; the other 23
  lose nothing**, and 5 of the 6 are 100-step cap-hitters losing 58–97 steps
  each. The worst (d3b966ba) has 97 of its 100 steps cut, and that tail contains
  exactly three distinct action-lists: `moveTo(960,600)` ×48 alternating with
  `scroll(-3)` ×48. The evaluator passed the task anyway — the teacher had
  finished and then scrolled forever. Those steps are precisely what must not
  enter SFT. Report the split (how many trajectories affected), never the bare
  aggregate.

### Do the filters catch the loops? Audit 2026-08-14 (`/tmp/loopaudit.py`)

Re-applied the exact `build.py` chain to **all 71 passing trajectories** in the
two run dirs behind abs-pilot3. It works, mostly: **614 tail steps trimmed from
12 trajectories, 54 mid-episode targets dropped**, and the teacher's showiest
loop — `vscode-no-telemetry`, 44 repeats — **is** caught (`low_diversity_tail`
trims it 50 → 5). Three trajectories escape, each through a different hole:

| filter | matches | blind to |
|---|---|---|
| `tail_run` | trailing run of byte-identical actions | anything mid-episode; all oscillation |
| `low_diversity_tail` | trailing ≤3-distinct window — **only if `len(steps) >= 50`** | everything mid-episode; every loop in a trajectory that ended normally under 50 steps |
| `identical_runs` | mid-episode runs of **≥8** byte-identical actions | oscillation; runs of 7; and it removes **targets only, not history** |

| escapee | shape | why it survives |
|---|---|---|
| `chrome/eadbe7a5` (69 steps) | `aabcde·[a×55]·fbbcdegh` | the 55-run *is* caught — 54 targets dropped. But all 69 steps stay in the context history, so each of the 15 surviving targets is conditioned on **55 identical assistant turns**. The tail filter reads 0 because the tail itself is varied |
| `calc/768f4c21` (63 steps) | `…gg`**`hhhhhhh`**`ij…` | a run of **7**, one short of `min_run=8`, kept whole. Calibration recorded the longest *legitimate* run as 6 — so 7 is already outside the legitimate band and the threshold has zero margin |
| `gimp/e16448e3` (37 steps) | `…vv`**`wxyxyxyxy`**`za` | a 2-cycle oscillation. `identical_runs` needs consecutive byte-identical steps; `low_diversity_tail` would catch it but only fires on cap-hitters and only at the tail. **Mid-episode oscillation under 50 steps is modelled by nothing** |

#### What the escape actually looks like in a shipped sample

`eadbe7a5` = slug `sec-edgar-berkshire-cik`. **14 of its samples are in
`abs-pilot2` and `abs-pilot3` `train_swift.jsonl`** — the data all four running
jobs read. The worst of them:

```
step 62 of 69 · 61 assistant turns in context · 6 distinct
                one response repeated 56x, and the label says "produce turn 62"
```

That repeated response is the model observing *"the current page is showing an
error… a previous search failed"* — fifty-six consecutive times. `identical_runs`
removed 54 of those steps as **targets**, which means "do not score the model for
producing this". It does **not** mean "do not show it to the model".

#### Sizing it before believing it (measured, and it lowers the priority)

Across the whole 1288-sample training set:

| context's most-repeated assistant turn | samples | share |
|---|---:|---:|
| no repeat | 1100 | 85.4% |
| 2–3× | 71 | 5.5% |
| 4–7× | 58 | 4.5% |
| **≥ 8×** | **7** | **0.5%** |
| (no assistant turn yet — step 1) | 52 | 4.0% |

**All 7 of the ≥8× samples come from that one trajectory.** So this is
**hygiene, not the explanation** — 0.5% of samples cannot account for 4/9 → 1/9,
and an earlier note in this file calling it "the one to fix first" overstated it.

Where it *does* matter is **before scaling the corpus**: one bad trajectory in 71
produced 0.5%, and the blind spots that let it through (oscillation off the tail,
the `>= 50` gate, `min_run` with no margin) get exercised far more at 10× the
data. Cheap to close now, expensive to discover later.

#### Repeat count is not evidence of pathology — all three proposals reverted

**Nothing from the 2026-08-14 filter proposals shipped. `traj.py` is byte-identical
to its pre-audit state (md5 `65c3dc96`).** They were written, installed, and then
killed by the verification that should have come first. Both failures are worth
keeping, because they are the same mistake in two directions.

**(1) collapse a caught run in the rendered history — killed by reading the labels.**
The 7 surviving samples of `sec-edgar-berkshire-cik` are:

| step | context turns | label |
|---:|---:|---|
| 62 | 61 | `left_click [48, 81]` — **a different place**, breaking the loop |
| 63–67 | 62–66 | redo the search: the same click/type/click that worked at steps 3–6 |
| 69 | 68 | **`terminate`** |

That is a **recovery demonstration** — *you clicked the same spot 55 times and it
did not work, so go elsewhere, redo what worked, finish*. This file records that
recovery is never otherwise demonstrated (every trajectory is a teacher success)
and that `terminate` is the rare token e1 never learned. The long repetitive
context is not poison, it is the **setup** that makes the recovery label mean
something. Corpus-wide there are **100** such samples; `build.py` now counts them
as `recovery_samples` in `report.json` — the only change kept from this whole
episode, and it is pure instrumentation.

**(2) `min_run` 8 → 7 and (3) a mid-episode oscillation filter — killed by
looking at the screenshots.** Both were built on repeat *count*. The case that
motivated (2) was `libreoffice_calc/768f4c21` grinding
`moveTo(743,697)+scroll(-10)` seven times. Hashing the frames:

```
step  8..15   moveTo(743,697) + scroll(-10)
              screen changed at EVERY step — 9 of 9 transitions
```

It is not grinding. **It is paging down a spreadsheet**, which is exactly what
scrolling is for. The change would have deleted 6 correct training targets, and
the oscillation filter would have taken a 7th from the same trajectory.

**The rule that came out of it — and its replacement (2026-08-14 evening).**
The first attempt was: *a repeated action is pathological only if the world did
not respond* (`action(k+1)==action(k)` and `shot(k)==shot(k-1)`). Measured at 8
targets, 0.49%, and it correctly spared the productive 7x scroll.

**Then `more3`'s failure showed that criterion is too weak.** On
`arxiv-listing` it alternates `click(215,280)` / `typewrite("1207.7214")` for 50
steps — 2 distinct actions, one repeated 27 times — and **the screen changes on
28 of 49 transitions**. The clicks open and close something; the state cycles.
An unchanged-screen test sees a no-op; this is a live 2-cycle between policy and
environment, and that test would miss it entirely.

**The signal that does catch it is state revisitation** — the fraction of steps
whose screenshot hash has been seen before in the same episode:

| | passing tasks | failing tasks |
|---|---:|---:|
| e3 | **0.02** | **0.56** |
| stock 4B | 0.09 | 0.16 |
| more3 | (none) | 0.37 |

On the arxiv trajectory: more3 **76%** revisited, 12 distinct screens across 50
steps; e3 **0%**, 5 screens in 5 steps.

Read it as a **loop detector, not a failure predictor** — the stock model's
separation is weak (0.09 vs 0.16) because it fails by doing the wrong thing
rather than by cycling. Where it is sharp is exactly where the SFT arms are
broken.

Two uses, both cheap and neither implemented:
- **runtime circuit breaker.** `OSTG_WAIT_BREAK` and `OSTG_LOOP_LOG` are both
  action-based and blind to this shape; a state-revisitation threshold would
  have ended more3's arxiv episode around step 10 instead of 50.
- **training-data filter.** This is what the withdrawn oscillation filter was
  groping at, done on *states* instead of *actions* — and unlike a repeat count,
  it does not mistake seven productive scrolls for grinding.

Both need calibration before use, on the same 72-trajectory corpus.

**Tests: `ostg/sft/test_filters.py`**, 10 cases covering only the shipped
filters, including one asserting that a run of 7 is deliberately NOT caught and
why. It also pins a pre-existing semantic worth knowing: `low_diversity_tail`'s
`max_distinct=3` lets a *neighbouring* action join the window as the third
distinct entry, so an 8-step oscillation next to one other action trims 9, not 8.

```
cd /mnt/d/research/ostg-v11.1 && PYTHONPATH=. \
  /mnt/d/research/OSWorld/.venv/bin/python -m ostg.sft.test_filters
```

**The process lesson, which is the real output of this episode.** The order was
propose → implement → verify, and verification killed two of three. Two separate
checks would each have caught it before any code was written: reading the labels
of the samples a filter removes, and hashing the frames on either side of the
steps it calls pathological. Both are minutes of work. **Verify, then execute.**

- **Every legacy trajectory's first frame is an approximation**:
  `tasks_initial_from_mp4: 39` out of 39 passing tasks. Those runs predate
  `initial_state.png`, so step-1 samples use recording frame 0. Flagged in
  sample meta; affects 39 of 609 legacy samples.
- The `FileNotFoundError: 'images/court-docket-numbers-lookup/obs_021.png'`
  entries are the same CWD defect in a second guise (both named slugs belong to
  the v500 dataset), not a separate problem.

### Official sampling for Qwen3.5 / 3.6 / 3.8 — and we are on the wrong profile

Read from the three model cards on 2026-08-14, not from memory. **Every one of
them publishes two different thinking-mode profiles**, and this file had only
ever recorded one of them.

| model | thinking · **general** | thinking · precise coding | instruct / non-thinking |
|---|---|---|---|
| **Qwen3.5-4B** (our student) | **temp 1.0**, top_p 0.95, top_k 20, min_p 0, **presence 1.5** | temp 0.6, top_p 0.95, top_k 20, presence 0.0 | temp 0.7, top_p 0.80, top_k 20, presence 1.5 · *reasoning:* temp 1.0, top_p 1.0, **top_k 40**, presence 2.0 |
| **Qwen3.6-27B** (our teacher) | **temp 1.0**, top_p 0.95, top_k 20, min_p 0, presence 0.0 | temp 0.6, top_p 0.95, top_k 20, presence 0.0 | temp 0.7, top_p 0.80, top_k 20, presence 1.5 |
| **Qwen3.8-27B** (candidate) | **temp 1.0**, top_p 0.95, top_k 20, min_p 0, presence 0.0 | — (card lists one thinking profile) | temp 0.7, top_p 0.80, top_k 20, presence 1.5 |

All three recommend an output length of **32,768** for most queries, and 81,920
only for competition-grade maths and programming. We run `--max_tokens 81920`
everywhere, which is the benchmark setting, not the general one.

**What we actually run, teacher and student alike:**

```
temperature 0.6 · top_p 0.95 · top_k 20 · presence 0.0 · thinking ON
```

That is the **precise-coding** thinking profile. The general thinking profile is
**temperature 1.0**. Qwen's own label for the 0.6 row is "precise coding tasks
(e.g. WebDev)" — code *generation*. Driving a desktop GUI is agentic control,
which sits much closer to "general".

**Why this is not a footnote.** The failure mechanism measured on 2026-08-14 is
that SFT arms get stuck because, after an action that changes nothing, they
repeat it (67–99% of the time) where the stock model varies (82%). **Temperature
is the variance knob, and we are running 0.6 where the vendor recommends 1.0 for
this class of use.** Lower temperature makes exactly the failure worse.

This yields a falsifiable prediction, and a cheap experiment:

> Raising the student serve from temp 0.6 → 1.0 should reduce the
> repeat-after-dead-end rate and help the **SFT arms more than it helps the
> stock model**, because the stock model already has the variance it needs.

If that holds, part of the "SFT made it worse" result is a serving choice rather
than a training outcome.

**A second connection this table explains.** `qwen35-4b-pp15` — the arm run with
`presence_penalty 1.5` — scored 2/9 against v2's 1/9, and it was treated at the
time as an ad-hoc ablation. **presence_penalty 1.5 is exactly Qwen3.5's official
general-thinking recommendation.** One task on a nine-task panel is noise, but
the arm was closer to the vendor's setting than the baseline it was compared
against, and that was not known when it was read.

**Do not carry 0.6 over to Qwen3.8 by default** (plan: `CUA/EXPERIMENTS.md` §11).
Whichever profile is chosen, record it next to the score — the campaigns to date
do not state which of the two thinking profiles they used, and the answer is the
precise-coding one.

### Sampling and action-chunk audit (2026-08-13 late)

**There is no action-chunk parameter** — the agent executes every action a
response contains. Measured on real trajectories:

| model | mean actions/step | distribution | max |
|---|---|---|---|
| teacher 27B | 1.20 | 80% single, 20% double | 7 |
| stock 4B | 1.28 | 90% single | 24 |
| **SFT v2** | **1.00** | **100% single** | **1** |

SFT collapsed multi-action responses entirely. Under a 50-step cap the teacher
effectively gets ~60 actions and the SFT student exactly 50 — a second, quieter
narrowing of behaviour to add to the copy-previous pathology.

**A real teacher/student sampling mismatch:**

| | temperature | top_p | top_k | presence_penalty |
|---|---|---|---|---|
| teacher serve (data generation) | 0.6 (client) | 0.95 | **20** (serve `--override-generation-config`) | 0 |
| student & base serves | 0.6 | 0.95 | **unset ⇒ disabled** | 0 |

The student checkpoint's `generation_config.json` carries only `eos_token_id`,
and the downloaded `models/Qwen3.5-4B/` has **no `generation_config.json` at
all**, so vLLM fell back to its own defaults and `top_k` never applied. Student
and base shared this, so the 4/9-vs-1/9 comparison stays fair, but both differ
from the distribution the training data was generated under.

**Against Qwen3.5's official recommendations** (model card): thinking mode,
general — temp 1.0 / top_p 0.95 / **top_k 20** / presence_penalty 1.5; thinking
mode, precise-coding — temp 0.6 / top_p 0.95 / **top_k 20** / presence_penalty
0.0. Our temp 0.6 + top_p 0.95 lands exactly on the precise-coding profile,
which is a defensible choice; **`top_k=20` is recommended in both profiles and
we omitted it**. Fix for the next rollout: give every serve
`--override-generation-config '{"temperature":0.6,"top_p":0.95,"top_k":20,
"repetition_penalty":1.0}'` so teacher, student and base share one declared
sampler.

**Applied 2026-08-13**: all three student/base/v1 serve scripts now carry
`--override-generation-config '{"temperature":0.6,"top_p":0.95,"top_k":20,
"repetition_penalty":1.0}'`. **No retraining is implied** — `top_k` is a
sampling parameter and never touches a cross-entropy fit on fixed targets. It
affects exactly two things: the teacher rollout that produced the data (already
baked in, top_k=20) and tier-3 rollouts (today's 4/9 and 1/9, which ran without
it). Both of today's arms shared the omission, so their comparison stands; the
absolute numbers were measured under a wider sampler than the data was
generated with.

**Ablation run and settled (2026-08-13 20:23): `presence_penalty` does not fix
the lock-ups.** Same pilotS3 checkpoint, same 9 tasks, single variable
0 → 1.5:

| | passes | mean distinct actions | trajectories with a ≥10× repeated action |
|---|---|---|---|
| SFT v2, presence 0 | 1/9 | 5.1 | **7/9** |
| SFT v2, presence 1.5 | 2/9 | 6.6 | **7/9** |
| stock 4B | 4/9 | 13.3 | 3/9 |

One extra pass is inside the noise at n=9, and the lock-up count did not move at
all; on arxiv it made things worse (6 steps and a pass at presence 0 became 46
repeats and a fail). **The mechanism explains it: `presence_penalty` acts within
a single completion, penalising tokens already emitted in *that* response. Our
repetition is across steps — each step is a fresh API call whose completion is
internally varied but identical to the previous step's.** The sampler cannot see
the previous turn's output, so it was never the right knob. My earlier
suggestion that it might be a one-flag deployment fix was wrong, and this
40-minute experiment is what showed it.

Conclusion tightened: **the lock-up lives in the weights, not the sampler.**
Stock averages 13.3 distinct actions with 3/9 lock-ups; after SFT it is 5–6.6
with 7/9. No sampling parameter recovers that gap — only data and recipe can,
which is exactly what the e1 / more / e3 arms test.

Do not expect `top_k=20` to cure the lock-ups — it *narrows* the distribution,
making the policy more deterministic, which if anything makes an absorbing
repeated state more likely. The parameter aimed at repetition is
**`presence_penalty`**, which the official card sets to 1.5 for general thinking
mode (and 0.0 for the precise-coding profile we adopted). A cheap, high-value
ablation is therefore: same checkpoint, same 9 tasks, `presence_penalty` 0 vs
1.5 — it separates "the weights lost the behaviour" from "the sampler let it
loop", and if the latter carries weight, it is a one-flag deployment fix rather
than a retrain.

Also noted: the official card advises that for multi-turn history "the
historical model output should only include the final output part and does not
need to include the thinking content" — the opposite of what `preserve_thinking`
does. That guidance is for plain multi-turn chat; the chat template's
tool-use branch keeps interleaved thinking unconditionally, and the teacher
generated every trajectory under that branch. Matching the teacher is what SFT
parity requires, so v3 keeps it — but the tension is worth remembering if a
future arm serves the student in a non-tool-use shape.

### Rebuilt corpus + third arm (2026-08-13 19:20)

Rebuilt v11-500 from the campaign's **29 passes** (was 17) through the standard
pipeline (`ostg.sft.build --val-ratio 0.15` → `export --dialect swift` → tar →
rsync → md5 + file-count verify → install), merged with legacy into
`data/abs-pilot3`: **1288 train + 178 val rows, 0 missing images**.

The stock `refresh_partial.sh` was NOT used as written: it contains
`rm -rf v11-500-partial-snap-pilot2`, and jobs 228622/228623 hold absolute paths
into that snapshot — running it would have killed both. The adapted script
writes only new names (`v11-500-r2`, `abs-pilot3`) and touches nothing in use.

Three arms now in flight, one recipe, one variable each:

| job | data | epochs | isolates |
|---|---|---|---|
| 228622 `sft-e1` | abs-pilot2 (916) | 1 | the fixed-data baseline |
| 228623 `sft-e3` | abs-pilot2 (916) | 3 | more optimization |
| 228667 `sft-more` | abs-pilot3 (1288) | 1 | more data |

### Serve port allocation — the collision that bit three times (2026-08-13)

Every serve sbatch hardcodes `--port 8000`, and Slurm freely puts two of our
jobs on one node, so a second serve dies instantly with
`OSError: [Errno 98] Address already in use`. It happened three times in one
evening (base-backup vs v1; the `more` arm vs a leftover smoke-test serve).
The failure is silent from the driver's side: the driver only polls for an HTTP
endpoint, so a serve that died at startup looks exactly like a serve that is
still loading, and the driver waits out its entire timeout (up to 2h).

**Rule until the fix lands: exactly one eval serve alive at a time.** The tier-3
queue is already sequential; every collision so far came from an ad-hoc serve
left running by hand.

**The fix, to apply when no driver is mid-flight** (editing a running bash
script corrupts its execution, and the drivers hold `RPORT=8000` internally, so
this cannot be hot-swapped):

| serve | remote port |
|---|---|
| teacher (Qwen3.6) | 8000 (unchanged) |
| tier-3 queue arms | 8731 |
| base / base-topk | 8732 |
| v1 | 8733 |
| sampler ablations | 8734 |
| external checkpoints (OpenWebRL etc.) | 8735 |

Each serve script sets its own `--port`; each driver starts its tunnel with the
matching `RPORT`. Unusual numbers are deliberate — ports are per-node and shared
with other users, so 8010-style values are likelier to be occupied by someone
else.

Meanwhile `serve_watchdog.sh` runs continuously: it greps every serve log for
`Address already in use` and reports within two minutes, and warns whenever more
than one eval serve is alive. It caught the `more` collision retroactively on
its first cycle.

### What 1 → 3 epochs actually bought: the model learned to stop

Comparing e1 and e3 step by step on the same 9 tasks (same 916 samples, same
recipe, epochs the only difference):

| | e1 (1 epoch) | e3 (3 epochs) |
|---|---|---|
| tasks that burned the full 50 steps | **9 / 9** | 5 / 9 |
| tasks that emitted `terminate` | **0 / 9** | **4 / 9** |
| mean steps per task | 50 | 33 |
| `mouse_move` share of actions | **32%** | 15% |
| `left_click` share | 54% | 75% |
| `terminate` in 450 / 296 actions | **never once** | present |

**e1 never emitted `terminate` in 450 actions.** It could not tell that a task
was finished — including the one it passed. On arxiv both models do the same
correct thing in the first four steps; e3 then emits `DONE` at step 5, while e1
oscillates between the address bar and the result link for another 46 steps:

```
e3:  click(226,87) → type "1207.7214" → click(207,130) → click(590,353) → DONE
e1:  click(257,87) → type "1207.7214" → press return → click(576,357)
     → click(92,87) → click(576,357) → click(92,87) → click(576,357) → ...  (×23)
```

It passed only because the checker reads the final state. The same behaviour is
fatal elsewhere: on chrome-downloads e3 sustains an 18-step multi-stage plan
(file manager → wait → Chrome → settings → change dir → Ctrl+S → DONE) while e1
falls into the `moveTo(960,600) + scroll(-3)` loop by step 8 — the very pattern
the tail filter strips from teacher trajectories.

**Interpretation.** One epoch is enough to learn the output *format* — legal
tool calls, plausible click targets — which is 99.4% of the target tokens. It is
not enough to learn the task's *temporal structure*: when a task is complete,
which actions advance it, how a plan survives across stages. Those live in rare
tokens (`terminate` is 3.6% of target actions, `wait` 3.4%), and rare signals
need repetition. It also explains why eval_loss saw nothing: the loss is
dominated by the 99.4%, so it "converged" at step 20 while the behaviour that
decides task success was still being learned.

**Falsifiable**: terminate-rate should keep rising with epochs until
overfitting. It is now a first-class metric in this ledger — it moved when
loss did not.

### An epoch-k checkpoint is not a k-epoch model

The cosine schedule spans the run's **total** steps, so "epoch 3" means
different things in different runs. Measured from the logs:

| | total steps | LR at the end of epoch 3 |
|---|---|---|
| e3 (a 3-epoch run) | 345 | **0.0** — annealed; the log shows 1e-8 at step 340, 0.0 by 342 |
| ep5pt/ep5np (5-epoch runs) | 805 | **3.77e-6 = 38% of peak** — still moving |

e3's final checkpoint is a finished product; the 5-epoch run's epoch-3
checkpoint is a mid-flight snapshot. Expect the snapshot to look worse, and do
**not** read that as a contradiction — it is the schedule, the same trap that
made the warm-restart run (227829) uninterpretable earlier the same day.

Consequences for reading the epoch curve:
- The five checkpoints of one run are comparable **to each other** (one
  schedule, five points along it) — good for trend, terminate-rate, behaviour.
- They are **not** answers to "what would a k-epoch run produce". That needs k
  independent runs, each annealing its own cosine — 15 epochs of compute for
  k = 1..5 instead of 5.
- We have two annealed products already (e1 = 1 epoch, e3 = 3 epochs) plus
  more3 (229348: 1288 samples, 3 epochs, its own full cosine). Where a snapshot
  differs from the matching annealed product, **that difference is the value of
  annealing** and is worth recording rather than explaining away.

Every checkpoint in the results table should carry the LR it was saved at.

### Why SFT is slow — measured 2026-08-14, nothing applied yet

**Baseline (job 229277, live):** `46.28 s/it`, 805 steps → **10.3 h**. One epoch
of abs-pilot3 is 35.3 M tokens over 161 optimizer steps, so throughput is
**4,740 tokens/s** on one H200.

**Where the tokens are** (1288 samples):

| | value |
|---|---|
| tokens/sample, mean | 27,421 |
| p50 / p90 / p99 | 29,600 / 43,878 / 50,389 |
| images/sample, mean | 11.2 (max 20) |
| **share of tokens that are screenshots** | **84%** (11.2 × 2040 = 22.8k of 27.4k) |

**Model shape that decides which lever matters** (`config.json`):

| | value |
|---|---|
| layers | 32 = **24 linear-attention + 8 full-attention** (`full_attention_interval: 4`) |
| hidden | 2560 |
| **vocab** | **248,320** |

Two consequences. Quadratic attention only exists in **8 of 32 layers**, so
FlashAttention is worth much less here than the usual advice assumes. And that
vocabulary is enormous: the logits tensor for one 27k-token sample is
`27k × 248,320` = **13.4 GB in bf16**, more when cross-entropy upcasts, plus its
gradient. That single tensor is the likeliest reason this config needs both
`zero2_offload` and `gradient_checkpointing`.

**Current config** (`sft-ep5pt.sbatch`): 1 GPU, `per_device_train_batch_size 1`,
`gradient_accumulation_steps 8`, `--attn_impl sdpa`, `--deepspeed zero2_offload`,
`--gradient_checkpointing true`, `--max_length 65536`. `freeze_vit` and
`freeze_aligner` are `True` by swift default — confirmed, the vision tower is
forward-only.

**Levers, ranked by expected value / cost. All VERIFIED AS AVAILABLE, none
applied — the four runs in flight must not be disturbed.**

| # | lever | status | why it should help |
|---|---|---|---|
| 1 | `--use_liger_kernel true` | **installed, flag exists, defaults `False`, we never pass it** | fused linear+CE never materialises the 13.4 GB logits tensor. Modest speed on its own; the prize is the memory headroom that unlocks 2 and 3 |
| 2 | `zero2_offload` → `zero2` | config change | DeepSpeedCPUAdam runs the optimizer step on CPU every 8 micro-batches. 4B params on GPU needs ~64 GB of 141 — should fit once (1) frees the logits memory |
| 3 | `--gradient_checkpointing false` | config change | recompute-in-backward is a 30–40% tax; only affordable after 1+2 |
| 4 | install `causal_conv1d` | **MISSING** (`fla` is present, `causal_conv1d` is not) | 24 of 32 layers are linear attention and use a short causal conv; without the fused kernel there is a slower fallback |
| 5 | 2 GPUs | scheduling | halves wall-clock (grad-accum 8 → 4/GPU). The original smoke ladder measured 322 → 85 s/it going 1 → 2 GPU, *superlinear* — consistent with the 1-GPU config thrashing on exactly the memory (1) targets |
| 6 | `flash_attn` | MISSING, ~20 min build | only reaches 8 of 32 layers here. Lowest priority of the kernel work, contrary to the usual first instinct |
| 7 | `--packing` / `--padding_free` | flags exist, unused | at batch size 1 there is no intra-batch padding, so the win is filling the 65k window instead of 8 sequential micro-batches. **Risky on this arch**: packed samples must not leak across sequence boundaries, and linear-attention layers carry state differently from full attention. Verify correctness before speed |
| 8 | shrink the image window | **not a config change** | 84% of training tokens are screenshots. `image_max=20` / `fold_size=10` come from the agent, so cutting it changes what the model sees at *inference* too. Biggest lever by far and the only one that also speeds up rollout — but it is an accuracy experiment, not a free win |

**How to test it**: the same smoke ladder that established this environment — a
short job on a fixed subset, ~20 steps, measuring `s/it` under one change at a
time. Each is minutes and well under $1. Do not benchmark by editing a real run.

### The acceleration A/B, run 2026-08-14 (jobs 229685 / 229709 / 229710)

Same data (abs-pilot3), same 5 epochs, same `preserve_thinking true`, same LR
schedule, **same effective batch 8** — so job **229277** is a same-parameter
control and the loss curves must overlay.

**Getting the kernels built took three attempts, each failing for a reason worth
keeping:**

| build | died after | cause |
|---|---|---|
| 229671 | 2 min | the venv is `uv venv`, which installs **no pip**, so a bare `pip` fell through PATH to the system python 3.9 and tried to build a torch extension against an interpreter with no torch. Never trust a bare `pip` here — use `uv pip install --python <venv python>` |
| 229672 | 8 min | `fatal error: cuda_runtime_api.h`. `CUDA_HOME` is a conda-layout toolkit whose `$CUDA_HOME/include` holds conda's generic headers (`bfd.h`, `bzlib.h`, `X11`); the CUDA headers are under `targets/x86_64-linux/include`. nvcc finds its own, the **host compiler does not** — set `CPATH` |
| **229676** | **succeeded, 1 h** | `causal_conv1d 1.6.2.post1` + `flash_attn 2.8.3.post1`, both into `$B/ext` via `--target`, never into `venv/` (four jobs were importing from it) |

Also learned: flash-attn first tries to download a prebuilt wheel and gets a
**404** for torch 2.13/cu130, then compiles from source (~35 min at `MAX_JOBS=8`,
**154 GB peak RSS** — the 200 GB request was necessary, 120 GB would have OOMed).

**`--deepspeed zero2` (dropping the CPU offload) does not fit. Measured twice:**

| job | config | result |
|---|---|---|
| 229685 | 4 changes | 28.8 → 24.0 → **22.4 s/it**, then **OOM at step 3** |
| 229709 | 4 + `--use_liger_kernel true` | **59.2 s/it**, **OOM at the same step 3** |

Removing the offload puts ~48 GB of optimizer state back on the GPU, and a
65536-token sample needs a `65536 × 248320` logits tensor — 32.5 GB in bf16,
~65 GB once cross-entropy upcasts, plus its gradient. **The one thing that would
erase that is liger's fused linear+CE, and swift refuses to apply it here**:

```
[WARNING:swift] The cross_entropy loss function defined in Liger Kernel
                will not take effect, potentially leading to increased
                GPU memory consumption.
```

`--loss_scale last_round` + `--enable_channel_loss` make swift compute the loss
itself from logits, outside the model, which is exactly the path liger's fused
CE replaces. **The two are mutually exclusive** — this is not a flag that was
tuned wrong. 229709 being *slower* than 229685 is the same story: it survived a
step longer by thrashing at 139 of 139.79 GiB, and the allocator paid for it.

**So the usable configuration is 3 of 4** (job 229710): 2 GPUs + `flash_attn` +
`causal_conv1d`, keeping `zero2_offload`. It cleared step 3 — the sample that
killed both `zero2` runs — and is running.

**Read the result per micro-batch, not per step.** Two GPUs alone halve the
micro-batches each GPU handles (8 → 4), so wall-clock improves even if nothing
else does:

| | baseline 229277 | 229710 (early) |
|---|---|---|
| per optimizer step | 46.28 s | ~32 s |
| micro-batches per GPU | 8 | 4 |
| **per micro-batch** | **5.79 s** | **~8 s** |

If that survives to steady state it means **the GPU count is doing all the work
and the two kernels contribute nothing net**, plausibly eaten by DeepSpeed's
cross-GPU gradient reduction. Early steps are not steady state (the baseline's
46.28 is a step-144 reading), so this is the number to check at step 50+, not a
conclusion. Report the per-micro-batch figure alongside any speedup claim.

#### Verdict, at steady state (baseline step 498, accelerated step 102)

**Speed — 1.49x wall clock, and the GPU count is doing all of it.**

| | baseline 229277 | accelerated 229710 |
|---|---|---|
| config | 1 GPU · sdpa · zero2_offload | 2 GPU · flash_attn · causal_conv1d · zero2_offload |
| per optimizer step | **42.98 s** | **28.87 s** |
| micro-batches per GPU | 8 | 4 |
| **per micro-batch** | **5.37 s** | **7.22 s** |
| wall clock | — | **1.49x faster** |
| per micro-batch | — | **1.34x SLOWER** |

Two GPUs alone should give 2.0x. We measured 1.49x, so **everything else in the
change set costs ~26%**. That 26% is flash_attn + causal_conv1d + DeepSpeed's
cross-GPU gradient reduction combined, and this experiment **cannot separate
them** — one run cannot attribute a shared cost. The honest statement is: *the
two kernels bought nothing net at this sequence length, and may have cost
something.* Plausible: only 8 of 32 layers are full attention, so flash-attn has
little surface to work on here, while the all-reduce is unavoidable at 2 GPUs.

**To attribute it properly**, one more 20-step run: 1 GPU, `zero2_offload`,
`flash_attn` + `causal_conv1d`, `gradient_accumulation_steps 8`. Compared
against the baseline's 5.37 s/micro-batch that isolates the kernels from the
communication. Minutes, well under $1 — worth doing before anyone credits
flash-attn for this speedup.

**Quality — no loss. 27 aligned logging points:**

| | value |
|---|---|
| mean loss delta | **+0.00006** (+0.038% relative) |
| sd | 0.00277 (0.824% relative) |
| range | −0.0070 to +0.0052 |
| sign split | **12 above / 15 below** |

Bit-identical was never the target: two GPUs change the gradient reduction order
and flash-attn changes attention numerics. The test is *tracking without drift*,
and a sign split that close to even is exactly that — a systematic change would
be lopsided and would grow with training. `grad_norm` and `token_acc` track the
same way. **The three accelerations are mathematically neutral.**

### Runs in flight (2026-08-14 01:10)

All on abs-pilot3 (1288 samples, 161 steps/epoch) unless noted; every arm keeps
a checkpoint at each epoch boundary.

| job | arm | epochs | preserve_thinking | annealed? | purpose |
|---|---|---|---|---|---|
| 229277 | `ep5pt` | 5 | **true** | snapshots | epoch curve, preserve on |
| 229278 | `ep5np` | 5 | **false** | snapshots | epoch curve, preserve off |
| 229348 | `more3` | 3 | true | **yes** | vs e3 — but confounds volume with +40% steps, see correction below |
| 229354 | `more3np` | 3 | **false** | **yes** | the preserve_thinking question at 3 epochs |

The pairs answer distinct questions. `ep5pt` vs `ep5np` gives the flag's effect
along a whole 5-epoch curve; `more3` vs `more3np` gives it at a single properly
annealed 3-epoch point.

**Correction (2026-08-14): `more3` vs `e3` does NOT isolate data volume.** This
file said it did. At a fixed effective batch of 8, sample count sets steps per
epoch, so holding *epochs* equal does not hold *optimization* equal:

| | samples | steps/epoch | 3 epochs = |
|---|---:|---:|---:|
| e3 | 916 | 115 | **345 steps** |
| more3 | 1288 | 161 | **483 steps** |

`more3` takes **40% more optimizer steps**. The comparison moves data volume and
total optimization together, and cannot attribute a difference to either.

That matters here because both runs are already **past the point of
overfitting** — `eval_loss` rises through training in both (e3 0.3110 → 0.3445,
more3 0.3440 → 0.3571). Another 40% of steps *inside the overfitting regime* is
on its own a sufficient explanation for a worse model, with no need to suppose
the extra 372 trajectories are lower quality.

**The experiment that separates them already exists on disk.** `more3` saved
`checkpoint-322` — 322 steps, the nearest match to e3's 345. Run the panel on it:

- `more3@322` ≈ e3's 3/9 → **steps were the cause, volume is exonerated**
- `more3@322` still poor → **volume (or the quality of the added trajectories) is implicated**

Until that runs, "more data hurt" is not a supported claim.

> **RETRACTED as a comparison.** 0/9 was the worst of three seeds (0/1/2). The
> behavioural counts in this section still hold; the ranking does not.

#### Result: `more3` scored **0/9** — the lowest of any arm (2026-08-14)

| arm | data | epochs | steps | **solved** | terminated | hit the 50-step cap | mean steps |
|---|---|---:|---:|---:|---:|---:|---:|
| stock Qwen3.5-4B | — | — | — | **4/9** | 7/9 | 2/9 | 24.3 |
| e3 | abs-pilot2 916 | 3 | 345 | **3/9** | 4/9 | 5/9 | 32.9 |
| e1 | abs-pilot2 916 | 1 | 115 | 1/9 | 0/9 | 9/9 | 50.0 |
| **more3** | abs-pilot3 1288 | 3 | **483** | **0/9** | 3/9 | 6/9 | 44.9 |

**It fit the data better than e3 and solved nothing.** Final train loss 0.0335
vs e3's 0.0373; token_acc 0.9906 vs 0.9861; fully annealed. The sharpest single
frame: on `arxiv-listing`, the easiest task on the panel, **e3 and the stock
model both finish in 5 steps and emit `terminate`; more3 burns all 50 and never
terminates.**

The degradation runs along the same axis e1 established — terminate rate falls
(4/9 → 3/9), cap-hits rise (5/9 → 6/9), mean steps rise (32.9 → 44.9).
**Termination is the first capability to go**, and it is the one that
`eval_loss` and `token_acc` are blindest to.

**State it as "1288 samples at 3 epochs gives 0/9", not "more data is worse".**
The 40%-more-steps confound above is unresolved, and both runs sit past the
overfitting knee. `more3/checkpoint-322` settles it and is already on disk.

Third time this project has hit the same wall: proxy metrics improve, the real
metric degrades. First the action exam, then eval_loss, now train loss and token
accuracy. Every one of them is computed without letting the policy choose its
own next observation.

> **The facts here stand; the conclusion does not.** The domain overlap is
> genuinely zero and the dilution genuinely 29%, but the score gap these were
> invoked to explain has not survived seeding.

#### Why `more3` is worse: the added data has zero domain overlap with the panel

Not "more data hurt". **abs-pilot3 = abs-pilot2 + 11 trajectories, nothing
removed** (verified by slug diff: 47 → 58 trajectories, 0 dropped). Those 11:

| | count |
|---|---|
| **added trajectories** | `libreoffice_calc` × 10, `gimp` × 1 |
| **the 9-task panel** | `chrome` × 5, `vs_code` × 3, `libreoffice_writer` × 1 |
| **overlap** | **none** |

By construction the added 372 samples cannot raise the score on this panel, and
they dilute what can: the panel-relevant trajectories fall from 100% of the
corpus to **71%** (916 of 1288).

**And the added trajectories are the teacher's longest, most marginal runs.**
The v11-500 rollout used a 100-step budget where v11 used 50:

| added trajectory | domain | original steps |
|---|---|---:|
| carrier-fuel-surcharge-lookup | calc | **100 — hit the cap** |
| returns-restock-fee-audit | calc | **100 — hit the cap** |
| tutor-invoice-pdf-from-rates | calc | 97 |
| pallet-manifest-weight-repair | calc | 63 |
| lab-fee-invoice-pdf | calc | 46 |

The existing 47 trajectories average 28 steps, max 50. Sample contribution is
also lopsided: `tutor-invoice-pdf-from-rates` alone yields **97 samples** (the
previous maximum for any trajectory was 45), and two trajectories account for
42% of the 372 added.

Four factors, all pushing the same way, and the symptom matches every one:
zero-overlap domains · 29% dilution · demonstrations that are twice as long and
include two the teacher barely finished · 40% more optimizer steps. `more3`
burns a mean of 44.9 steps, hits the cap 6/9, and terminates on only 3/9 — it
learned to take long meandering episodes, which is exactly what it was shown.

**The honest limit of this result.** The panel's domains are fixed, so calc data
can only cost points here — this shows *adding data outside the test's syllabus
loses on that test*, **not** that these calc trajectories are bad data. A
benchmark with real domain coverage would be needed to say that, which is one
more reason real evaluation moves to OSWorld-Verified.

#### Is a 100-step pass a bug? No — and two of my own claims here were wrong

Asked whether hitting exactly the 100-step cap and still scoring 1.0 looks like
a bug. It does not, for a mechanical reason: **100 IS the cap**, so it is the
expected length of every trajectory that fails to terminate, not a coincidence.
And the passes are real — all five added calc tasks score **0.0 on an untouched
VM** in the control sweep, so `compare_table` cannot be satisfied without
actually editing the spreadsheet.

What the two cap-hitters are is *the work done, then an inability to stop*:

| trajectory | steps | most-repeated action | tail trimmed | **samples reaching training** |
|---|---:|---:|---:|---:|
| carrier-fuel-surcharge | 100 | **72×** | 73 | **27** |
| returns-restock-fee | 100 | **90×** | 92 | **8** |
| tutor-invoice-pdf | 97 | 15× | 0 | 97 |

**Correction 1.** This file said the added data was "the teacher's longest, most
marginal runs". Overstated: the tail filter caught both cap-hitters, cutting them
to 35 samples between them — under 10% of the 372 added. The largest contributor,
`tutor-invoice-pdf-from-rates`, is a **legitimate** 97-step trajectory with 61
distinct actions that ends in `DONE` with nothing trimmed.

**Correction 2.** Those two cases suggested the teacher itself cannot terminate,
and that the student inherits it. Measured across every passing trajectory in
both source runs, that is **false**:

| source | passing trajectories | **ended with `DONE`** | ran out the budget |
|---|---:|---:|---:|
| v11 (ms50) | 39 | **33 = 85%** | 6 |
| v11-500 (ms100) | 57 | **46 = 81%** | 9 |

The teacher terminates in four trajectories out of five. The students manage
0/9 (e1), 3/9 (more3), 4/9 (e3). **The student is losing a capability that the
data demonstrates well** — this is not a coverage gap, it is a learning failure.

Which sharpens the token-share argument rather than softening it: `terminate` is
3.6% of target actions and occupies **one position in a ~28-step trajectory**.
Token-averaged cross-entropy cannot see it under the 99.4% of format and prose.
It is the first capability lost and the last recovered, and weighting that span
in the loss is now the best-motivated open change in this file.

**Rule going forward: report the domain overlap between any new training data
and the evaluation before reporting the score.** It was not checked before this
run, and it explains more of the result than anything else measured.

#### WHY SFT makes it worse — measured, and it is not about grounding tokens

The token-share argument explains why SFT fails to *teach* much. It does not
explain why the model ends up **worse than untrained**. This does.

**Measurement: after an action that changed nothing on screen, what happens next?**

| model | dead-end steps | repeats the action | tries something else | solved |
|---|---:|---:|---:|---|
| **stock Qwen3.5-4B** | **11** | 18% | **82%** | **4/9** |
| teacher Qwen3.6-27B | 41 | 85% | 15% | 9/9 (selection) |
| e3 | 78 | 90% | 10% | 3/9 |
| more3np | 67 | 67% | 33% | 1/9 |
| more3 | 114 | 81% | 19% | 0/9 |
| e1 | **195** | **99%** | 1% | 1/9 |

**The teacher repeats too — 85% of the time — and it is right to.** In a
successful trajectory a click that produced no visible change usually just needs
a moment: the dialog is still opening, the app is still repainting. Repeating is
correct behaviour *for a model that rarely mis-clicks*. And since every training
trajectory is a success, **repetition is the only failure response the data can
teach.**

The student inherits the habit without the accuracy behind it:

```
teacher    41 dead ends x 85% repeat  -> still finishes
e3         78           x 90%         -> 3/9
more3     114           x 81%         -> 0/9
e1        195           x 99%         -> the entire budget spent in place
```

The stock model has the opposite profile: **equally inaccurate, but its response
to a dead end is to vary (82%)** — not because it is smarter, but because
nothing has sharpened its output distribution. On this panel, flailing works:
try enough different things and one lands. That is where its 4/9 comes from.

**So the regression has a single sentence: the correct policy is conditional on
your own accuracy, and SFT copies the policy without the accuracy.** It also
removes the exploration that was covering for the inaccuracy.

Two corollaries this explains that nothing else did:

- **Why e3 beats e1**: 78 dead ends vs 195. The extra epochs mainly bought
  *fewer wasted actions*, not better recovery — e3's repeat rate (90%) is barely
  under e1's (99%).
- **Why the stock model is hard to beat here**: the panel rewards variance, and
  SFT's first effect is to destroy variance.

**What follows for the recipe.** Adding more successful trajectories cannot fix
this — every one of them teaches "repeat" as the failure response. The data
needs episodes where an action fails and the model does something *else*, and
the corpus contains only 100 such samples (`recovery_samples` in `report.json`).
Candidates: keep failed-then-recovered teacher episodes rather than only
`score == 1.0` trajectories; or accept that behaviour cloning alone cannot fix
it and the recovery policy has to come from RL on the generated tasks.

#### All six arms on the identical nine tasks (2026-08-14, complete)

| arm | data | epochs | steps | preserve | **solved** | terminated | hit cap |
|---|---|---:|---:|---|---:|---:|---:|
| **stock Qwen3.5-4B** | — | — | — | — | **4/9** | 7/9 | 2/9 |
| **e3** | 916 | 3 | 345 | true | **3/9** | 4/9 | 5/9 |
| e1 | 916 | 1 | 115 | true | 1/9 | 0/9 | 9/9 |
| more | 1288 | 1 | 161 | true | 1/9 | 2/9 | 6/9 |
| more3np | 1288 | 3 | 483 | **false** | 1/9 | 4/9 | 5/9 |
| more3 | 1288 | 3 | 483 | true | **0/9** | 3/9 | 6/9 |

**No SFT arm has reached the stock model.** The best is still e3 at 3/9.

Three readings that hold:

1. **`preserve_thinking` off beat on at a clean annealed point** — 1/9 vs 0/9,
   identical in every other respect. One task on a nine-task panel is not
   evidence of much, but it is enough to retract this file's earlier
   "exonerated" verdict, which rested on two 1-epoch runs over defective data.
2. **1288 samples at 3 epochs is clearly worse than 916 at 3 epochs** (0–1/9 vs
   3/9) — with the attribution still open between volume and the +40% steps.
   `checkpoint-322` settles it.
3. **Termination tracks success**, not monotonically but unmistakably:
   base 7/9 terminated → 4/9 solved; e3 4/9 → 3/9; more3np 4/9 → 1/9;
   more3 3/9 → 0/9; e1 0/9 → 1/9. **A model that cannot stop cannot finish.**
   `terminate` is 3.6% of target actions and invisible to every token-level
   metric in this file.


### Eval policy: final checkpoints only (2026-08-14 01:40, user decision)

`ckpt_pipeline.sh` — which evaluated **every** epoch-boundary checkpoint as it
landed — is **stopped**. Superseded by `final_evals.sh`: **a 5-epoch run is
evaluated at 5 epochs and a 3-epoch run at 3 epochs**, nothing in between.

| arm | evaluated at | = |
|---|---|---|
| `ep5pt` / `ep5np` | `checkpoint-805` | 5 epochs |
| `more3` / `more3np` | `checkpoint-483` | 3 epochs |

Two reasons, and the second is the one that makes the mid-run snapshots close to
worthless as *results*:

1. **The 3 VMs are the scarce resource.** Ten checkpoint evals cost ~6.7 h of VM
   time that the v11-500 teacher rollout needs to finish the corpus.
2. **An epoch-k snapshot of a longer run is not a k-epoch model** (§ above): the
   cosine spans the run's *total* steps, so `ep5`'s epoch-3 snapshot sits at 38%
   of peak LR while `e3`'s is annealed to 0. Comparing a snapshot against an
   annealed product measures the schedule, not the epochs.

The five snapshots of one run remain comparable **to each other** for a trend,
and they are still written — this is a decision about what gets VM time, not
about what gets saved. `final_evals.sh` is installed and **not running**; it
waits for every `sft-*` job to leave the queue, then runs the four arms one at a
time. Launch it by hand when the VMs are free.

## The commands actually in use (2026-08-14)

**Training — the epoch-curve pair.** Identical except `--preserve_thinking`;
`--save_steps 161` = one epoch on abs-pilot3 (1288 samples ÷ effective batch 8),
so checkpoints land at 161/322/483/644/805 = epochs 1–5. `--qos=normal` because
805 steps × ~47 s ≈ 10.5 h exceeds the interactive QOS's 8-hour cap.

```bash
cd $B/runcwd                       # neutral CWD, never a dataset dir
PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True' IMAGE_MAX_TOKEN_NUM=2048 NPROC_PER_NODE=1 \
swift sft \
  --model $B/models/Qwen3.5-4B \
  --dataset     $B/data/abs-pilot3/train_swift.jsonl \
  --val_dataset $B/data/abs-pilot3/val_swift.jsonl \
  --enable_channel_loss true \
  --tuner_type full --loss_scale last_round --gradient_accumulation_steps 8 \
  --preserve_thinking true|false \
  --attn_impl sdpa --deepspeed zero2_offload --torch_dtype bfloat16 \
  --num_train_epochs 5 --per_device_train_batch_size 1 \
  --learning_rate 1e-5 --warmup_ratio 0.05 \
  --max_length 65536 --gradient_checkpointing true \
  --eval_steps 40 --save_steps 161 --save_total_limit 6 --logging_steps 4 \
  --report_to wandb --run_name <name>-$SLURM_JOB_ID \
  --output_dir $B/out/<name>
```

Preceded in every job by the RECIPE v3 preflight (below), which aborts before
any GPU time if a single image path fails to resolve.

**Serving a checkpoint for the rollout** (one serve alive at a time):

```bash
vllm serve $CK --served-model-name <name> \
  --tensor-parallel-size 1 --max-model-len 262144 --reasoning-parser qwen3 \
  --override-generation-config '{"temperature":0.6,"top_p":0.95,"top_k":20,"repetition_penalty":1.0}' \
  --limit-mm-per-prompt '{"image": 20}' --host 127.0.0.1 --port 8000
```

**The 9-task rollout** (`run_arm.sh` wraps this; `OSTG_PARAM_DIALECT=inline`
only for foreign checkpoints such as OpenWebRL's):

```bash
OSTG_WAIT_BREAK=10 OSTG_LOOP_LOG=12 .venv/bin/python scripts/python/run_multienv_qwen.py \
  --provider_name docker --path_to_vm .../Ubuntu.qcow2 --headless \
  --observation_type screenshot --action_space pyautogui \
  --model <name> --base_url http://127.0.0.1:<port>/v1 \
  --temperature 0.6 --top_p 0.95 --max_tokens 81920 --max_steps 50 \
  --sleep_after_execution 1 --enable_thinking --num_envs 3 --simple_path \
  --screen_width 1920 --screen_height 1080 \
  --test_config_base_dir  .../eval_valpanel_tasks \
  --test_all_meta_path    .../eval_valpanel_tasks/manifest.json \
  --result_dir .../results_generated/<name>/valpanel-a1
```

**Evaluating the finished arms** (`final_evals.sh`, replaces `ckpt_pipeline.sh`):
waits until no `sft-*` job is in the queue, then for each arm serves its final
checkpoint and runs the 9-task panel, strictly one arm at a time. If the exact
final step is missing it falls back to the newest checkpoint **and logs that the
number is not the full schedule** — a partial run still deserves a number, but
never a silently mislabelled one.

The retired pipeline's one idea worth keeping, should checkpoint streaming ever
come back: a checkpoint counts as ready only when `config.json` and the weight
shards exist **and the directory has been untouched for 180 s**. swift writes
shards progressively, and serving a half-written checkpoint is the failure that
guards against.

## RECIPE v3 — FROZEN 2026-08-13 evening (supersedes v2)

v2 plus the two changes that make the 08-13 silent-data-drop impossible:

```
  --dataset     $B/data/abs-pilot2/train_swift.jsonl     # ONE file, ABSOLUTE image paths
  --val_dataset $B/data/abs-pilot2/val_swift.jsonl
  cd $B/runcwd                                           # neutral CWD, never a dataset dir
```

and a **preflight block that aborts the job** before any GPU time is spent:

```bash
python - "$DS" <<'PY' || { echo "PREFLIGHT FAILED — aborting"; exit 1; }
import json, os, sys
ds = sys.argv[1]; bad = tot = 0
for split in ("train_swift", "val_swift"):
    for line in open(os.path.join(ds, split + ".jsonl"), encoding="utf-8"):
        if not line.strip(): continue
        for p in json.loads(line).get("images", []):
            tot += 1
            if not os.path.isabs(p) or not os.path.exists(p):
                bad += 1
                if bad < 4: print("UNRESOLVED:", p)
print(f"preflight: {tot} image refs, {bad} unresolved")
sys.exit(1 if bad else 0)
PY
```

First run under v3 (job 228622) printed `preflight: 11194 image refs, 0
unresolved`. **Non-negotiable rules this encodes:**

1. **Media paths in an emitted dataset are ABSOLUTE.** A relative path is only
   meaningful next to a CWD, and two datasets cannot share one CWD.
2. **Never `cd` into a dataset directory.** It made image paths appear to work
   for whichever dataset happened to be first, and it let wandb write run
   directories into a "frozen" snapshot.
3. **Every training job proves its data loads before it trains.** Row counts
   prove nothing: swift reported `train_dataset: 916 rows` while a third of
   them could not produce an image.
4. **Grep the training log for `template.encode` warnings after every run.**
   swift's response to an unloadable sample is one warning line and a random
   substitution — a defect that costs a third of the corpus looks exactly like
   normal training otherwise.

## RECIPE v2 — superseded by v3 (kept for provenance of runs 227303/228092)

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

### Single-episode reads are treacherous — a correction (2026-08-13 23:35)

On exam-kiosk (difficulty 5, stock passed in 28 steps, `more` failed at 50) the
two episodes take nearly identical opening moves — click the Chrome dock icon,
WAIT, WAIT — and then diverge **in the environment, not in the model**: Chrome
launched for the stock run and did not launch for `more`. The step-4 screenshot
shows only the task's pre-opened text editor.

I first read `more`'s reasoning ("the previous attempt did not open Chrome,
the text editor is in the way") as a hallucination about an open browser. **The
screenshot says otherwise: its perception was correct.** What actually fails is
the remedy — it clicks (1896, 44), the top-right corner, apparently aiming at a
close button, but the editor is not maximised and its close button is at
(947, 133). The miss leaves the screen unchanged, it returns to the Chrome icon,
and a three-action cycle forms.

Two lessons, both mine:
1. **Do not narrate a trajectory without opening its frames.** This is the
   second over-read of the day (the first was "phase lag self-corrects").
2. **A single episode cannot separate model behaviour from environment
   variance.** The stock model never faced the adverse branch here. Claims of
   the form "model A handles X worse" need pass@k or many more tasks; at 9
   tasks × 1 attempt we can see gross differences (4/9 vs 1/9) and nothing
   finer.

The defect this does support: **no recovery strategy under an adverse branch.**
When an action has no effect, the SFT model repeats it, and its corrective
action is itself mis-grounded. That is consistent with a corpus of teacher
successes in which "the action did nothing, try something else" is never
demonstrated.

> **RETRACTED — see READ THIS FIRST.** Both arms here are single-seed. `more3`
> later scored 0/1/2 across three seeds and `e3`'s second seed lost all three of
> its passes, so a 1/9 → 3/9 gap is inside the panel's ±2 noise.

### Epochs are the one lever that moved the real metric (2026-08-14 00:40)

| arm | data | samples | epochs | preserve_thinking | **tasks solved** |
|---|---|---|---|---|---|
| teacher Qwen3.6-27B | — | — | — | — | 9/9 |
| stock Qwen3.5-4B | — | — | — | — | **4/9** |
| stock + top_k=20 | — | — | — | — | **4/9** |
| **e3** | abs-pilot2 | 916 | **3** | true | **3/9** |
| OpenWebRL-4B-SFT | theirs | 3085 | 3 | — | 2/9 |
| pp15 (sampler ablation) | — | 609 | 1 | true | 2/9 |
| e1 | abs-pilot2 | 916 | **1** | true | 1/9 |
| more | abs-pilot3 | **1288** | 1 | true | 1/9 |
| pilotS3 / v1 | — | 609 | 1 | true / unset | 1/9 |

Only single-variable pairs support a conclusion:

- **e1 vs e3** (same 916 samples, 1 → 3 epochs): **1/9 → 3/9.** Epochs help.
- **e1 vs more** (both 1 epoch, 916 → 1288 samples): **1/9 → 1/9.** Volume does
  not help *at this scale*.
- **e3 vs more differs in two variables and supports nothing.** e3 did not win
  because it had less data; it won because it trained three times as long.

The qualitative change matters more than the count: on chrome-downloads every
1-epoch model clicked the Chrome dock icon ~50 times; **e3 finished it in 18
actions**.

**Proxy metrics lied a third time.** e3's eval_loss bottomed at step 20 (0.311)
and then sat on a 0.34 plateau for the remaining 325 steps — read alone, that
says "more epochs bought nothing". The real tasks say 1/9 → 3/9. Together with
the two earlier cases (loss and the action exam both calling a regression an
improvement), the standing rule is now unambiguous: **on agent tasks, only the
rollout counts.**

**`preserve_thinking` has been compared only at 1 epoch** (pilotS with it unset
vs pilotS3 with it true, both 609-effective samples): held-out loss ~0.52 flat
vs 0.294→0.273 — a large difference — and **1/9 vs 1/9** on real tasks. Whether
it matters at 3+ epochs was untested, which is what the two 5-epoch arms
(229277 / 229278, abs-pilot3, checkpoints at every epoch 161/322/483/644/805,
differing only in that flag) are for.

### e1 result (2026-08-13 21:21): fixing the data bug did NOT fix the regression

| arm | passes | mean distinct actions | trajectories locked (≥10× repeat) | mean steps |
|---|---|---|---|---|
| stock 4B | **4/9** | 13.3 | 3/9 | 24 |
| pilotS3 (broken data, 609 effective samples) | 1/9 | 5.1 | 7/9 | 41 |
| pp15 (sampler ablation) | 2/9 | 6.6 | 7/9 | 42 |
| **e1 (data fixed, 916 samples)** | **1/9** | **4.4** | **9/9** | **50 — every task hit the cap** |

Restoring the silently-dropped third of the corpus raised training data by 50%
and did not move the pass count: **1/9 before the fix, 1/9 after**. Data
*integrity* is therefore eliminated as an explanation.

**Data volume is NOT eliminated, and an earlier version of this section
over-claimed that it was.** The only volumes tested are 609 → 916 → 1288
samples, i.e. 39 → 68 trajectories — a 2× span that sits entirely below the
reference point (OpenWebRL: 412 trajectories / 3,085 turn-level samples, six
times ours). A flat segment inside a range that may lie wholly on the
"too little" side of the curve cannot refute the curve. The honest statement is:
**within 609–1288 samples, volume does not move the result**; what happens at
3,000 or 10,000 is untested. The 444-task campaign is expected to yield roughly
110–120 passing trajectories, which is the first point where our scale
approaches a quarter of the reference — that is when the volume question
becomes answerable.

Also keep the resolution in mind: 9 tasks means one task is ±11 points. 4/9 vs
1/9 is three tasks and reads as real; 1/9 vs 2/9 does not.

**Caveat I introduced and must not paper over:** e1 is the first arm served with
`top_k=20` (verified in its serve log), because I patched the serve scripts
between arms. base (4/9), pilotS3 (1/9) and pp15 (2/9) all ran with `top_k`
unset. So the *lock-up worsening* in the table — 7/9 → 9/9, distinct actions
5.1 → 4.4 — **cannot be attributed to the data**: I had already predicted that
`top_k=20`, by narrowing the distribution, would make an absorbing repeated
state more likely, and e1 is the only arm carrying it. Changing a shared setting
midway through a controlled comparison was an operational error.

Remedy queued: re-run the **stock model under `top_k=20`** so the reference line
matches every arm from e1 onward. Until that lands, only the pass counts are
comparable across the pre/post-patch boundary, not the behavioural metrics.

What remains is the **kind** of data, and the OpenWebRL comparison sharpens it:

| | OpenWebRL | ours |
|---|---|---|
| trajectories | 412 | 68 |
| turn-level samples | 3,085 | 1,288 |
| **mean steps per trajectory** | **7.5** | **19** |
| selection | **keep only the shortest successful trajectory per task group**, tie-broken by shorter total response | keep every passing trajectory, then trim degenerate tails |
| epochs | 3 | 1 (e3 arm testing 3) |
| history masking | `mask_history: true` | `loss_scale last_round` — same thing |

We demonstrate "wandered, retried, eventually succeeded"; they demonstrate "no
wasted move". Our filters remove the degenerate *tails* but keep every
mid-trajectory retry, and at 19 steps per trajectory there are many. More of
that data teaches the retry habit harder — which is exactly the e1 result.

Falsifiable prediction for the `more` arm (1288 samples, same data philosophy):
1–2/9 with lock-ups at 8–9/9. If it lands there it means volume does not help
*at this scale* — it is a third point on a very short curve (609 / 916 / 1288),
not a verdict on scaling. Trajectory selection (shortest-successful) is worth
testing precisely because it is cheap and orthogonal to volume, not because
volume has been ruled out.

### DATA DEFECT found 2026-08-13 evening: a third of the corpus never trained

Every pilot so far (pilotS, pilotL, pilotS3, pilotS3x3) passed **two** dataset
files whose `images` entries are RELATIVE (`images/<slug>/obs_NNN.png`), and the
sbatch `cd`s into the first dataset's directory. swift resolves relative media
paths against the process CWD (`ROOT_IMAGE_DIR: None` in the startup log), so
the second dataset's images resolve to nonexistent paths. swift's
`vision_utils.load_file` then treats an unresolvable path as **base64**, decodes
it to garbage bytes and hands them to PIL:

```
PIL.UnidentifiedImageError: cannot identify image file <_io.BytesIO object ...>
[WARNING:swift] There are errors in the template.encode, and another piece of
data will be randomly selected.
```

Evidence chain:
- functional test on the login node, cwd = the legacy snapshot:
  `os.path.exists("images/onboarding-handouts-single-pdf/obs_001.png")` → False,
  and `load_image()` on it raises exactly the logged error;
- the slug sets of the two datasets are disjoint (32 vs 15 slugs, 0 overlap), so
  **3419/3419** v500 image references miss when resolved from the legacy dir;
- swift reports `train_dataset: 916 rows` — nothing is filtered at startup, so
  the failures happen per draw, and the warning count grows during the run
  (63 at step 76 → 80 at step 121 of pilotS3x3; 70 in pilotS3's whole run).

Consequence: the **307 v500 training samples (33% of the corpus — the newest
campaign's trajectories) and 26 of the 151 val samples could not be loaded**;
each draw was dropped and replaced by a random other sample. Effectively every
result reported today was trained on the ~609 legacy samples. (The logged
warning count is lower than the 1/3 share; the per-draw bookkeeping behind that
gap is not established, but the load failure itself is proven and total.)

Fix: **absolute image paths in the emitted jsonl** — a single `ROOT_IMAGE_DIR`
cannot serve two datasets with different roots. Built as `data/abs-pilot2/`
(916 train + 151 val rows, 0 missing files verified), written to a NEW directory
so the running job's snapshots stay untouched. `ostg/sft/export.py` should emit
absolute paths, or the runner should pass one dataset root.

This also means the epoch-response experiment and every arm comparison should be
re-run on the fixed data before being treated as measurements of "916 samples".

### THE HEADLINE RESULT: SFT regressed the model, 4/9 → 1/9 (both variants)

| arm | passes | which tasks |
|---|---|---|
| teacher Qwen3.6-27B | **9/9** | (panel is built from its passes) |
| **stock Qwen3.5-4B** | **4/9** | arxiv(5 steps), exam-kiosk(28), vscode-telemetry(10), store-hours(54) |
| **SFT v1** (history think stripped) | **1/9** | spectra-loader(9) |
| **SFT v2** (history think kept) | **1/9** | arxiv(6) |

> **Superseded 2026-08-14.** The paragraph below concluded `preserve_thinking`
> had no effect, from two arms that both scored 1/9. Both were 1-epoch runs on
> the defective 609-sample data. At a properly annealed 3-epoch point the flag
> does separate them — `more3np` (off) 1/9 vs `more3` (on) 0/9 — so "exonerated"
> is too strong. See the six-arm table below. It is a one-task difference on a
> nine-task panel and proves little on its own; what it does is reopen a
> question this file had closed.

**`preserve_thinking` is exonerated as the cause.** Both SFT variants land on
exactly 1/9 — identical magnitude of damage with and without history reasoning
in the training context. The regression is caused by SFT itself at this recipe
and data scale, not by that flag (which remains the correct train/serve
alignment fix: v2's eval_loss is far better, 0.273 vs v1's flat 0.52).

The two SFT arms keep *different* residual tasks — v2 holds the easiest one
(arxiv, 6 steps) while v1 burns 50 steps failing it yet passes spectra-loader,
which base failed and v2 locked on. Same level, different debris.

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

**Ruled out: image budget / resolution.** Measured on the shipped training set —
images per sample 1–20 (cap exactly 20, matching the agent's `image_max`),
on-disk resolution 1920×1088 (native 1080p; 1088 is smart_resize's 32px-patch
alignment, not compression), and 60×34 = **2040 visual tokens per image**, which
is the full native token count at the model's 16px patch × 2 merge. The training
env's `IMAGE_MAX_TOKEN_NUM=2048` never clipped anything (2040 < 2048), and the
label dump's `[248056 * 2040]` confirms it. vLLM serves from the checkpoint's own
preprocessor (`longest_edge` 16.7M pixels ≫ 2.09M), so serving matches training.
More decisively: **the base arm ran through the identical image pipeline** —
same agent, same `process_image`, same 20 images at 2040 tokens — and scored
4/9. Image configuration is a constant across arms and cannot explain a
between-arm difference. (The 32px effective patch IS coarse for 12–16px UI text,
which plausibly caps how well *any* arm can do here — a separate question from
the regression, and one bounded by the 1080p source.)

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

### What the 9-task panel is for, and what it is not (decided 2026-08-14)

**The panel is an instrument for ranking recipes, not a measure of the model.**
It exists to answer "which training setup works" and "how much data is needed to
beat the stock model" cheaply — 9 tasks, ~1 h per arm — and it has done that
(e1 1/9 → e3 3/9 identified epochs as the lever when loss saw nothing).

It cannot answer "did the model get better at desktop work", because it is
**in-distribution by construction**: same generator, same 1300-cell taxonomy,
and the tasks are literally the validation split of the training corpus.

**Real evaluation is on benchmarks the line has never trained toward** —
OSWorld-Verified first, then others. Contamination is already gated, which is
what makes this valid: the generated corpus scores max cosine **0.46 vs
official-361** against a `< 0.50` gate, so the student has never trained on a
paraphrase of it.

**The blocking prerequisite: there is no stock Qwen3.5-4B number on
OSWorld-Verified.** Only the teacher has one (45.2%, 141/312 non-proxy,
`results/qwen36-27b-bf16-local/osworld-verified-361-…20260731`). Without the
stock-4B baseline an SFT number on that benchmark is unreadable — "SFT helped"
and "a 4B is simply weak here" produce the same number. That baseline runs first.

**Measured cost** (2026-08-14, from the v11-500 rate): **13 tasks/h on 3 VMs**,
so 312 non-proxy tasks ≈ **24 h per arm**; the other 49 still need residential
proxy credentials. At that price not every arm can be run, so:

- run **stock 4B** and **the single best SFT arm** first — 2 days, and that pair
  is the only comparison that answers the actual question;
- for wider sweeps use a **stratified subset** (balanced by the 11 domains).
  A subset costs nothing in comparability against the teacher: its per-task
  results already exist for all 312, so it can be re-scored on any subset for
  free. A subset number is *not* comparable to the published 45.2% until the
  teacher is re-scored the same way — do that, do not quote across subsets.

### Where the 9 tier-3 tasks come from, and why they are not contaminated

Nobody picked them. They fall out of the same task-level split that produces the
validation set, in `ostg/sft/build.py`:

```python
is_val = int(hashlib.md5(slug.encode()).hexdigest(), 16) % 1000 < val_ratio * 1000
```

- **Task-level, not sample-level.** One trajectory yields many step samples that
  share a long context prefix; splitting by sample would put a held-out sample's
  own prefix in training and make eval loss meaningless. Splitting by slug keeps
  every step and every screenshot of a task on one side.
- **Deterministic across rebuilds.** The hash depends only on the slug, so a
  task that was validation in one build stays validation in every later build —
  which is why rebuilding v11-500 from 17 → 29 passing trajectories did not move
  any exam task into training.
- **The panel is the union of both corpora's val tasks**: 7 from v11-legacy
  (39 passing trajectories, `val_tasks: 7`) and 2 from v11-500.
- **The teacher scores 9/9 by construction**, because SFT data is built only
  from `score == 1.0` trajectories, so every val task is one the teacher solved.
  That is the ceiling line, not a measured achievement.

**It is a hash, not a seed.** There is no RNG and nothing to set: the draw is
`md5(slug) % 1000` compared against a threshold. Two consequences worth stating
because they are easy to assume away:

- **One escape hatch exists.** `build.py:113-131` — if the draw selects nobody,
  the lexicographically-first passing slug is *forced* into val so a requested
  split is never empty. On a small corpus that makes the val set depend on
  **which tasks passed**, i.e. on the rollout. It has not fired for these
  corpora (`drawn` was true both times), but it is the one path by which a
  rebuild could silently move the panel.
- **The panel the arms run is frozen, not drawn.** It is a materialised
  directory, `OSWorld/eval_valpanel_tasks/{examples,manifest.json}`, built once
  as the union of both corpora's val tasks. Since 2026-08-14 `sft.json` carries
  `panel_n/panel_id` (`9/35d3bac3`, md5 of the sorted task ids) and the
  dashboard prints it next to the results header, so a regeneration is visible
  rather than silent. **An arm measured on 9 tasks is not comparable to one
  measured on 12** — if the panel ever changes, every arm retakes it, same rule
  as the archived action exam.

**Contamination check, run 2026-08-14** — searched both shipped datasets for the
nine exam slugs and task ids:

| dataset | train rows | exam slugs in train | exam slugs in val |
|---|---|---|---|
| abs-pilot2 | 916 | **0 / 9** | 9 / 9 |
| abs-pilot3 | 1288 | **0 / 9** | 9 / 9 |

Not "the task was seen but not its answer" — the entire task, all of its steps
and frames, never entered training.

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
| action exam (type acc / coord MAE / think) | **demoted 2026-08-13 to a cheap format smoke-test only** — does the model still emit parseable actions | task capability, and in practice not even relative quality: it ranked the checkpoint that scored 1/9 as the best model on the panel (0.800 acc, above stock 4B's 0.775), and rendered the fatal copy-previous defect as a benign "phase lag". Teacher forcing hands the model a correct history, so a policy that has stopped reading its observation still scores well |
| **rollout success rate** (tier 3: our tasks, then OSWorld-Verified) | **whether training worked. This is the acceptance criterion; everything above is a proxy for this row** | — |

Ledger row contract: job id, recipe version, data version (filter version +
sample counts + snapshot name), outcome (incl. failures and WHY), wandb link,
checkpoint path. Corollary learned today: an eval baseline is only valid for
deltas if it took the SAME exam — re-baseline whenever the panel changes.


## How OpenWebRL handles thinking in training data — and where we differ

Checked 2026-08-14 against their released code (github.com/OpenWebRL/OpenWebRL,
clone at `0d38a95`-era HEAD), because their 4B web agent is the closest published
analogue to our student. Everything below is from their code, not the paper.

### Their rollout / RL context (`openwebrl/generate_browser.py:338-400`)

They built exactly the compression machinery we have been debating, as two knobs:

- `turn_history_reasoning_mode`: `full` | `hide_thinking` (regex-strips
  `<thinking>` blocks from **historical** assistant turns; the current turn is
  never touched) | `action_only` (history keeps only the action/tool_call
  blocks).
- `browser_history_reasoning_max_turns`: a middle setting — full reasoning for
  the last N assistant turns, `hide_thinking` for everything older.

**And then they ship every released script with both knobs off**: all three run
scripts set `TURN_HISTORY_REASONING_MODE:-full` and `MAX_TURNS:-0`. Their
headline 4B numbers (67.0% Online-Mind2Web) were trained with **full thinking in
history** — the same convention as ours and as every reasoning model in the
OSWorld authors' Verified archive (RUNBOOK, "Does thinking go back into
history"). The knobs exist for ablation; the answer they ship is `full`.

### Where they are genuinely different: images, not text

Their text history is full-length, but screenshots in context are **last 1**
(4B script) or **last 3** (8B script) — against our `image_max 20`. A 4B student
trained with a single current screenshot plus full text/thinking history reached
67% on a live-web benchmark. That is the strongest external evidence yet on our
"does the student need 20 images" question, and it points at no.

### Their SFT warm start (`sft/`)

- Stage 1 (`convert_to_openai_messages.py:256-264`): canonical episodes keep
  reasoning **inline in assistant `content`** (`<think>…` text) and split tool
  calls into structured `tool_calls` — reasoning rides in content, same as our
  convention.
- Stage 2 (`prepare_openai_for_llamafactory.py`): renders canonical episodes
  through the **base model's own `tokenizer.apply_chat_template`** — "the exact
  call the runtime makes at inference — so the SFT data is byte-consistent with
  the model's inference format" (their README). Historical thinking is kept; no
  compression exists anywhere in the SFT path.
- Two granularities: whole-episode (`mask_history: false`, supervise every
  assistant turn) or per-turn prefixes (`iter_prefixes`, `messages[:i+1]`) with
  a **single current screenshot** and `mask_history: true`.

### What the paper itself teaches — quality lessons, ranked by relevance to us

From the paper (arXiv 2606.02031) + the repo, 2026-08-14. Their released recipe,
first: **SFT used per-turn ONLY** — `PER_TURN=1` is the wrapper default and its
comment says "reproducing the released recipe"; `mask_history: true`, single
current screenshot, vision tower + projector frozen, LM full-finetuned,
`cutoff_len 36864`. The whole-episode mode exists in the tooling as an
efficiency alternative and was NOT the released run. Base for the VL family:
Qwen3-VL-4B-**Thinking**.

**① Historical reasoning is their single most valuable context component.**
Ablating it costs **−14.6 to −23.7 points — the largest effect they measured**.
Their words: reasoning traces "naturally serve as compact textual memory", and
"Human users do not repeatedly inspect every previous browser state; instead,
they rely primarily on recent visual observations together with memory of prior
actions." This settles our hide-thinking debate in the opposite direction from
the worry: **stripping think from history is the single most damaging thing
their ablations found.** Our full-think replay is the validated side.

**② Screenshot history is nearly worthless beyond 1.** Going from one screenshot
to two: −1.9 to −4.0. Combined with ①, their context recipe is "all the text,
almost none of the images" — the extreme of the trade our runner makes at 20
images. External support for a hard rollout-side `image_max` cut, already noted.

**③ Curation: small and picked, not large and complete.** "We intentionally
curate a small, high-quality subset instead of imitating all successful teacher
trajectories." Mechanics: 4 teacher rollouts per task → judge → **shortest
successful trajectory per task** (response-length tiebreak) → per-website cap →
**412 trajectories / 70 sites**. We currently take every successful trajectory,
including the four 50-step wall-hitters scored 1.0 that CLAUDE.md already calls
poison. Borrowable immediately: shortest-per-task when we have multiple
successes, and drop limit-hitting 1.0s.

**④ Heavier SFT warm start made the post-RL model WORSE.** 1.9K trajs × 3 ep
underperformed 0.4K × 3 ep after RL — "stronger warm start … may reduce policy
plasticity." Consistent with our own more-data arms showing nothing. If RL-init
is this corpus's purpose, over-SFT is a measured risk, not a hunch.

**⑤ Textual environment feedback is worth −5.2 to −8.0 when removed.** Their
user turns carry action-outcome strings ("lightweight feedback makes web
interaction more observable, allowing the agent to distinguish successful
actions from silent failures"). Our OSWorld user turns carry a screenshot and
nothing else. Injecting outcome text is a harness change — off-limits for
Verified comparability, but legitimate for generated-task training rollouts.

**⑥ Their judge is their weak point, our evaluators are ours.** They needed a
distilled 8B judge (89.8% vs GPT-4.1) because success is subjective on the live
web; our programmatic evaluators are exact — but our wall-hitting false-1.0s
show they have holes of their own kind.

### The delta table

| | OpenWebRL | ours |
|---|---|---|
| thinking in rollout history | full (default; knobs exist) | full (no knobs — would live in `_response_transform`) |
| screenshots in context | **1** (4B) / 3 (8B) | 20 |
| SFT reasoning placement | inline in content | inline in content |
| SFT rendered via | base model's official chat template (byte-consistent with inference) | our own sample assembly from `traj.jsonl` `response` |
| SFT granularity | per-turn prefix **or whole-episode packing** | per-turn prefix only |
| per-sample visual context | per-turn mode: 1 current screenshot (matches their rollout) | full inference context via the agent's own `build_messages` — 20 images + folding (matches our rollout) |
| after SFT | online multi-turn RL (slime) | nothing yet |

**A correction to an earlier phrasing.** "Aggregated by `step_num`" is not a
granularity choice and does not belong in the row above — it is a dedup fix for
an OSWorld artifact: `traj.jsonl` writes one line per pyautogui action, so a
multi-action response repeats identical lines (v11: 1,041 lines → 946 steps,
§5.2). Both pipelines are per-turn at heart; OpenWebRL never needs the fix
because its trajectories store one record per turn to begin with.

**The one real granularity difference is whole-episode packing — and it was
measured and rejected the same day** (sft/CONTEXT.md §6.2). Their
`mask_history: false` mode supervises every turn of an episode in one packed
sequence at O(T) encoded tokens instead of per-turn's O(T²). But our folding
(`image_max 20`/`fold_size 10`) rewrites history as steps advance, so packing is
only lossless for episodes ≤20 steps — 49% of the v11 corpus by count and
almost none of it by cost. Measured: full packing saves 12.9× image encodings;
the lossless subset saves **1.1×**. The savings live exactly where the
equivalence breaks. If training cost is the problem, the real lever remains a
smaller `image_max` at ROLLOUT (CONTEXT.md §6.3), for which OpenWebRL's
1-image 4B is now external support.

### Two actionable points

1. **Byte-consistency check we have never run.** They guarantee SFT text ==
   inference text by rendering through the same chat template. We assemble SFT
   samples ourselves, and we now know the serving template injects an empty
   `<think>` slot ahead of every historical assistant turn (RUNBOOK) — so our
   student trains on histories WITHOUT the empty slots and infers on histories
   WITH them. Small, but it is exactly the class of mismatch their pipeline
   exists to kill, and checking ours costs one rendered-vs-assembled diff.
2. **The image-history experiment has an external prior now.** Their 4B works
   with 1 screenshot. If we ever cut `image_max`, cut hard, not to 10.

## The pipeline is one command (2026-08-15, user rule)

All data filtering runs through a single fixed entrypoint — the same command
whether a human or an agent invokes it, no per-run planning:

```bash
bash sft/pipeline.sh RESULT_DIR TASKS_DIR OUT_DIR
```

It does exactly three things, in order: **build** (score==1.0 trajectories →
per-step samples via the agent's own context code, with the standing filters),
**verify** (`ostg.sft.verify`: every image referenced by every sample exists
and is non-empty — hard fail otherwise), **report** (print `report.json` so
drop counts are on the record). Behaviour changes happen in `ostg/sft/*.py`
through review — never by ad-hoc variation of the invocation.

Sync note: the executing copy lives on WSL (`/mnt/d/research/ostg-v11.1`);
after changing anything under `sft/`, push the file and compare md5 before
running (CLAUDE.md §9).

## The Verified eval protocol (2026-08-15, user decision)

No more val split and no more 9-task panels: **arms are evaluated on a fixed
sample of OSWorld-Verified itself.** The user's design: uniformly sample the
benchmark, run base Qwen3.5-4B and the SFT'd model on the SAME tasks, compare.

**The sample.** From the **312 non-proxy** tasks of `test_nogdrive.json` (the
49 `proxy: true` tasks are excluded — no residential proxy is configured, and
they degrade silently without one). Stratified proportionally by domain,
`random.Random(20260815)`, largest-remainder rounding:

- `evaluation_examples/verified_eval100_nonproxy.json` — 100 tasks
- `evaluation_examples/verified_eval50_nonproxy.json` — **50 tasks, a stratified
  prefix of the 100**: run the 50 first; if the result is borderline, running
  the remaining 50 upgrades the eval to n=100 with zero wasted episodes.

Copies live in the repo under `eval/`; the runner-facing copies sit in the
OSWorld `evaluation_examples/` dir on WSL. Both files are frozen — never
resample; a new draw is a new eval and old numbers stop being comparable.
**Subset property verified 2026-08-15: every task in the 50 is in the 100
(per-domain ⊆ checks all true, zero duplicates).**

**External anchor found 2026-08-15**: the Qwen3.5-4B model card itself
reports **OSWorld-Verified 35.6** (alongside ScreenSpot Pro 60.3, AndroidWorld
58.6). Not comparable to our numbers — vendor self-reports run their own
agent/harness and favored step tier on the full 369 (incl. proxy), vs our
ms50 · screenshot-only · pyautogui · 50-task non-proxy subset — but it warns
that the base prior below (5–10%) may be far too low: if stock 4B lands
25–35% even on our stricter harness, the SFT margin question is much tighter
than the power arithmetic assumed. The base-stock arm measurement settles it;
until then treat 35.6 as "the vendor can make this model do Verified" and
nothing more.

**50 vs 100, the arithmetic.** At plausible rates (base 4B ≈ 5–10%, a useful
SFT effect ≥ +15 points), n=50 gives SE per arm ≈ 4–6 points — enough to call
a ≥15-point gap, not enough for ≤8. n=100 halves nothing (SE ~3–4) but doubles
the ~10–20 h wall-clock per arm pair. Hence 50 as the screening eval with the
free upgrade path.

**Config for both arms — identical or the comparison is void:** ms50, sleep 3,
temp 1.0 / top_p 0.95, history_n 100, image_max 20, the same runner. Score =
evaluator output; report mean and exact-1.0.

## The A/B plan on 3.8 data (2026-08-15)

Not either/or: **arm A (v11-100 only) trains tonight while v11-500 rolls out —
the GPUs and the VMs are disjoint resources — and arm B (v11-100 + v11-500)
trains when the 500 lands.** Both evaluate on the frozen verified-eval-50, so
A-vs-B answers the data-volume question on a real benchmark instead of the
9-task panel whose SE retracted every earlier volume claim.

| | A: v11-100 | B: +v11-500 (projected) |
|---|---|---|
| perfect trajectories | ~62 | ~260–290 |
| samples (= steps; zero filtered, measured) | ~1,200 | ~5,000–5,500 |
| trajectory median steps | 15 | ~20–25 (3.6's v11-500 successes: med 27, mean 37.6 — harder, longer tasks) |
| OpenWebRL scale reference | below their 412-traj recipe | at it; their harm line was 1.9K |

Timeline: A launches ~02:00 Aug 15 (3ep × 1.2k ≈ 6–10 h) alongside the 500
rollout (~28–31 h); eval-50 for base + A when the VMs free up Aug 16; B builds
and trains after (3ep × 5.2k ≈ 24–36 h — epochs negotiable), evals Aug 17.
Every sbatch is shown to the user before submission.

## The two published SFT recipes bracketing ours (2026-08-15)

| | OpenWebRL (small-data + RL) | MolmoWeb (big-data pure SFT) | ours (A) |
|---|---|---|---|
| base | Qwen3-VL-4B-Thinking | Molmo2 4B/8B (Qwen3 LM + SigLIP2) | Qwen3.5-4B |
| trajectories / steps | 412 / 3,085 | 278.5K / 2.2M | 69 / ~1,250 |
| extra data | none | **+10.5M perception** (7M grounding, 2.2M screenshot QA; 20% of mix) | none |
| screenshots per sample | 1 | 1 (zero history images) | up to 20 |
| text history | full, with thinking | last 10 actions + URL/title, no thinking | full, with thinking |
| vision tower | frozen | trained (fed by the perception data) | swift default — confirm freeze_vit in the launch log |
| after SFT | online RL (SFT is warm start only) | nothing (SFT is everything) | nothing yet |

Both published recipes use ONE screenshot of visual context — the third
independent source pointing at an image_max cut. Their two proven routes are
"curation + RL on top" and "scale + perception data"; a thousand-sample pure
SFT with neither is exactly the untested cell our A/B occupies. MolmoWeb
footnote worth keeping: their 36K human trajectories gave "limited gains" over
synthetic. If A/B disappoints, grounding/perception data for the student is the
recorded next candidate — noted, not started.

## Arm C (designed, not started): open-source trajectories with similarity filtering

User idea 2026-08-15: pull open trajectory datasets, similarity-filter to our
task distribution, add to SFT. Deferred to after A/B so the volume question and
the external-data question stay separately answerable. Design on record:

1. **Contamination screen is mandatory and comes first.** Our eval is now
   OSWorld-Verified itself; the largest open CUA trajectory source is the
   authors' `ubuntu_osworld_verified_trajs` — trajectories ON the eval
   benchmark — and OSWorld-derived subsets hide inside other collections.
   Every candidate trajectory's instruction is checked against the full
   Verified 361 by embedding similarity; above-threshold → discarded, report
   archived. No screen, no training.
2. Candidate sources, surveyed 2026-08-15 — the desktop-data drought ended
   this year; what stays scarce is OUR slice (Ubuntu):
   - **AgentNet** (OpenCUA): 22.5K human tasks, of which **Ubuntu 5K** — the
     only human Ubuntu-desktop trajectories in the open, first in line.
   - **ProCUA-SFT** (2026-06): 3.1M step-level samples from 93K synthetic
     trajectories, the largest open desktop CUA training set — OS mix,
     dialect and contamination unchecked.
   - **GroundCUA** (CUA-Suite): 3.6M UI-element annotations on 56K
     screenshots — not trajectories but the desktop version of MolmoWeb's
     perception ingredient; feeds the grounding-fallback direction, not C.
   - VideoCUA (10K human tasks as 30fps video): heavy processing, back of
     the queue. OS-Genesis/ANCHOR: method references more than data.
   - Scale context: ProCUA's 3.1M steps exceeds MolmoWebMix's 2.2M — raw
     desktop volume has caught up with web; Ubuntu-fit volume has not.
3. Similarity filter to OUR distribution: instruction embeddings + app-domain
   match, as the user proposed (same family of technique OpenWebRL used for
   corpus dedup).
4. **Dialect conversion** into the internal tool-call format + our context
   construction, then the standard `pipeline.sh` with its verify gate — one
   converter per source, the main engineering cost.
5. C evaluates on the same frozen verified-eval-50; its delta over A/B is the
   single-variable answer to "does external data help".

## Qwen-CUA (2026-08-03, Qwen Team x XLang) — the desktop flagship's recipe

Two findings that reframe ours (arXiv 2608.02352):

1. **Our context construction is theirs, verbatim.** "Scales the active visual
   history to 20 screenshots per turn", boundary "advances by 10 steps",
   folded screenshots become "a fixed textual placeholder", and "reasoning and
   actions remain in the conversation" — i.e. image_max 20 / fold_size 10 /
   think-in-history. The upstream runner's mechanism IS the flagship's
   training mechanism (XLang = the OSWorld authors). The image-count question
   is now web-lineage (1 image: OpenWebRL, MolmoWeb) vs desktop-flagship
   (20 + folding) — genuinely open, ours to test, not to assume.
2. **Fold-aware slicing — the packing idea done right.** "Complete episodes
   are rendered as multiple context-bounded slices by advancing the
   folded-prefix boundary; each slice inherits the terminal reward, and only
   active model-generated tokens contribute to its loss." Slices along fold
   boundaries keep training context identical to inference context, which is
   exactly the equivalence CONTEXT.md §6 proved plain packing breaks. Builder
   v3 candidate, on record, not started.

Also noted: model-assisted CoT completion for reasoning-less human demos
(moot for us — teacher reasoning comes free), and iterative rounds that
retrain from the same mid-training checkpoint rather than continually
fine-tuning the previous agent (anti-drift; copy when we iterate).

Arm A dataset FINAL (pipeline run 2026-08-15): **69 trajectories → 1,196
samples, zero filter losses, verify 11,595 image refs / 0 missing.**
save_steps 150 (= 1196/8 per epoch). 10 samples estimated over max_length
65536 (the xhigh thinking tail — new; no prior dataset had any): confirm
swift's truncation strategy at launch so labels are never silently cut.

## How the two published recipes handle history thinking — verified, 2026-08-15

Question forced by our launch preflight: the student's template strips historical
`<think>` unconditionally (measured; no `preserve_thinking` var exists in its
jinja), so training must pick a side. What do Qwen-CUA and OpenWebRL do?

**OpenWebRL: lean SFT warm start, rich RL and rich eval — CORRECTED
2026-08-15** (an earlier revision of this section wrongly called them
lean/lean throughout). The template does strip history think — verified
behaviorally on their base-model lineage, all of default/`enable_thinking`
False/True — **but their rollout code defeats the template**:
`_restore_assistant_history_blocks_in_prompt` (`generate_browser.py:431`,
called at `:1775`) regex-replaces every templated assistant block with the
ORIGINAL content after rendering, with the comment "Some Qwen chat templates
discard visible `<think>...</think>` content from prior assistant turns...we
want the full historical assistant reasoning to remain visible". Their eval
(`run_evaluate.py`) imports the same code path. Their SFT Stage 2 has NO such
restore — it renders through the raw template, so the warm start trains on
lean history contexts. Net: **67% = lean-SFT warm start → rich RL → rich
eval**, and their −14.6 to −23.7 ablation for removing historical reasoning is
coherent: measured on a rich-trained model, at eval.

**Qwen-CUA: rich at inference (direct evidence), rich at training (inferred).**
Their own demo client re-embeds streamed reasoning into content exactly like our
`client.py:51` — `f"<think>\n{reasoning}\n</think>\n{content}"`
(`demo/src/qwen_cua/model_client.py:108`) — and replays it via `build_messages`;
with their backbone lineage's preserving template (we measured Qwen3.8's), the
model sees history reasoning at inference. Training-side rich is INFERRED, not
quoted: the paper's "reasoning and actions remain in the conversation" plus
slices rendering that same conversation; no sentence says "training context
keeps think" outright. Important wire-vs-token distinction the harness hides:
ALL three parties (teacher rollout, Qwen-CUA, our student eval) SEND think-in-
content over the wire; whether the model SEES it is decided by the serving
template — teacher and Qwen-CUA templates pass it through, the student's strips
it. The divergence lives inside vLLM's render, invisible to the harness.

**Nobody ships rich-train/lean-infer.** That cell is the bug: it is what our
e1/e3/more arms did (`--preserve_thinking true` in swift, then evaluation
through the student's stripping template with no switch to prevent it —
valpanel args confirm `preserve_thinking: False` and the jinja has no such
var anyway). `more3np` (false) was accidentally the only consistent arm.

| | SFT-stage history think | RL-stage | eval/infer | notes |
|---|---|---|---|---|
| Qwen-CUA | inferred rich | rich (iterative RL on the same conversation) | rich (direct code evidence) | template supports it natively |
| OpenWebRL | **lean** (raw template render) | **rich** (post-template restore) | **rich** (same restore path) | built machinery to defeat the template |
| our e1/e3/more | rich | — | lean (template strips, no switch) | the cell nobody publishes |
| more3np | lean | — | lean | accidentally consistent |

The arm-A flag is an open user decision; the three configurations and their
verified properties are laid out above. Constant across all of them: the label
turn's thinking is untouched — the model learns to produce reasoning either
way; the flag only decides whether it sees its own past reasoning.

## LAUNCHED 2026-08-15: both arms, rich and lean (user decision)

Jobs **232347 `sft-q38rich`** (`preserve_thinking true`) and **232348
`sft-q38lean`** (`false`), submitted together, identical otherwise: the
q38-v11100 dataset (69 trajs / 1,196 samples, verified), e3 recipe, 3 epochs,
epoch-boundary checkpoints, 9 h walls (~$8.10 each). Sbatch copies under
`sft/sbatch/`; the verified keepthink template (stock 4B jinja + one branch,
T1–T4 all green: history think kept, think-free renders byte-identical to
stock) is `eval/qwen35_4b_keepthink.jinja`, deployed at serve time via
`--chat-template`, the base model directory untouched.

**Eval matrix on verified-eval-50, user-ordered:**
1. base-4B · stock template
2. q38e3-**rich** · keepthink (rich/rich)
3. q38e3-**lean** · keepthink (OpenWebRL-style: lean-trained, rich-evaled)
4. q38e3-**lean** · stock (lean/lean)

Estimated ~5–6.5 h per run, 3 shared VMs, starts when v11-500 lands
(~Aug 16 morning). The lean arm evaluated both ways makes the serving-template
effect itself a measured variable on the same weights.

**FINAL rich-ep1 (2026-08-16 09:04): 13/50 = 26% — THE EPOCHS CURVE IS
FLAT-DAMAGED: base 38% → ep1 26% → ep3 28%.** One epoch loses as much as
three; the ~10–12-point regression is fully installed by the first epoch and
neither deepens nor heals after. Training depth is exonerated; the corpus
and its transfer to Verified carry the entire indictment. Per-domain (ep1):
chrome 3/3 (best of the three arms) · gimp 2/4 · calc 0/7 · impress 0/7 ·
writer 0/3 · multi_apps 1/12 · os 2/4 · thunderbird 1/3 · vlc 2/3 ·
vs_code 2/4, plus the same impress 0.903 near-pass base hit. Operational
footnote: the arm ran under mixed client timeouts (130s→300s→600s over the
first five tasks; 600s thereafter — 45 of 50 uniform), and its checkpoint's
half-migrated behavior (terse when confident, 20k-token deliberation when
lost) made it ~3x slower per hard task than either sibling. Consequence for
the plan: the B arm's question sharpens from "does more data help?" to "does
DIFFERENT data (harder, longer v11-500 trajectories) change the sign at
all?" — and the anti-forgetting levers (replay mix, LoRA, eval-aligned data)
move from options to the likely main line if B stays negative.

### Trajectory forensics at ep1's 7-task mark (2026-08-16 05:0x)

Three findings that change how the arm numbers should be read:

1. **The eval has a hidden 10% dimension: five `func:"infeasible"` tasks**
   (gimp svg-convert, calc 2bd59342, os a462a795, vlc 7882ed6e, vs_code
   7c4cc09e) where declaring FAIL is the correct answer. Surrender profiles:
   base declares once in 50 tasks (1/1 correct — never quits, so loses 4 of 5
   infeasible points by grinding to cap); ep3 declares 4 times (2 correct =
   os+vlc, 2 wrong — including impress 455d3c66, the task base nearly passed
   at 0.903); ep1 so far 1 true declaration, and it is the show-piece:
2. **ep1's svg "win" is a correct infeasibility deliberation** — 10 steps,
   ending in a 114k-char think that concludes the task cannot be done, then
   FAIL. base and ep3 both ground to the cap on it. The deep-thinking mode
   that makes ep1 slow is exactly what produced the benchmark's hardest
   judgment call.
3. **ep1's unique loss (transparent-background) was not a surrender — the
   harness killed it.** Step 4's think plans "zoom in to verify the
   selection"; the tool call emits `ctrl_scroll` — an action name NOT in the
   parser enum → empty parse → the upstream fallback (restored 08-14) ends
   the episode as FAIL. §3.1's hallucinated-action trap, now with
   instant-death semantics. Rules are equal across arms, but arms that
   hallucinate undeclared action names more (the半迁移态 ep1) pay more.
   Count per-arm empty-parse deaths at the full-50 mark.

Corpus-design implications, recorded for B/C: exact action-name fidelity is a
trainable/filterable property (one hallucinated name = one dead episode
upstream); and surrender calibration is worth 10% of the benchmark —
best-of-3 selection keeps correct-FAIL demos if the rerun corpus surfaces
any, and generated corpora should include infeasible tasks with FAIL demos.

**FINAL base/keepthink (2026-08-16 02:13): 19/50 = 38% — THE STOCK MODEL
BEATS THE SFT ARM BY 10 POINTS.** Identical serving (keepthink +
preserve_thinking), weights the only difference. Per-domain (base vs rich):
impress 2/7-vs-0/7 (+ one 0.903 near-pass) · thunderbird 2/3-vs-0/3 · vs_code
2/4-vs-1/4 · multi_apps 4/12-vs-3/12 · os 1/4-vs-2/4 (rich's only win) ·
chrome/gimp/calc/writer/vlc identical. Paired: both 12, base-only 7,
rich-only 2, neither 29 — McNemar 7:2, p≈0.18: not enough to convict "SFT
hurts" at n=50, decisive that **SFT did not help**. The damage concentrates
in domains thin or absent in the 69-trajectory corpus — the narrowing
signature, not a serving artifact. The model card's 35.6 self-report is
essentially reproduced on our stricter harness (38%): stock Qwen3.5-4B is
simply strong at Verified out of the box, and the bar arm A had to clear was
far higher than the 5–10% the protocol assumed. Arm B (v11-100 + v11-500,
~4x data) is now the pivotal test; the n=100 upgrade path exists if the
lean arms land within a few points.

**FINAL rich/rich (2026-08-15 23:30): 14/50 = 28%** — the pre-registered
central call (14/50) hit exactly. Per-domain: chrome 2/3 · gimp 2/4 · calc 2/7
· impress 0/7 · writer 1/3 · multi_apps 3/12 · os 2/4 · thunderbird 0/3 ·
vlc 1/3 · vs_code 1/4. Grading the forecast: impress collapse (0/7) and os
(2/4) called exactly; multi_apps finished 25% — its mid-run 3/6 heat fully
regressed (0/6 in the back half), landing between the prior (15%) and the
streak; vs_code and thunderbird over-predicted (corpus strength did not
transfer). One task (impress 70bca0cc) aborted on 5x LLM timeout at step 44
in pass 1; the driver's pass-2 retry scored it (fail) — 50/50 clean, no
denominator holes. The 28% now awaits the base/keepthink control: handover
was autonomous (rich serve cancelled 23:31:56, base serve 233022 submitted).

**Pre-registered prediction (2026-08-15 20:55 PT, rich/rich at 25/50 scored,
8 passed)**: final 13–15/50 (central 28%), band 11–18. Per-domain forecast:
impress ~10% (0/6 observed — domain collapse), multi_apps ~15% over its 10
remaining (the deciding block), os/vs_code ~40% (corpus-taught terminal and
settings.json routes), thunderbird ~25%, vlc ~30%. Logged before the fact so
the final readout can grade the model of the model.

**COMPLETED 2026-08-15 (both COMPLETED, exit 0:0)** — rich 5:19:53, lean
4:55:21 (~$5 each, under the 9 h wall). Checkpoints 150/300/450 (= epoch
boundaries) present for both under
`/gpfs/scrubbed/jy050706/sft/out/q38e3-{rich,lean}/v0-20260815-012706/`.

| arm | train loss first→last | token acc first→last |
|---|---|---|
| rich (232347) | 0.622 → **0.069** | 81.8% → **97.78%** |
| lean (232348) | 0.804 → **0.074** | 78.1% → **97.78%** |

Lean starts noticeably harder (0.80 vs 0.62 first-step loss, −3.7 pts acc):
predicting the same actions without the past-reasoning context is a harder
modeling problem, exactly the mechanism the rich/lean contrast is designed to
price. Both converge to the same endpoint (~0.07 / 97.78%) — training-side
metrics cannot separate the arms; only the eval matrix can.

### Qualitative read of the arm-A demonstrations (2026-08-15)

Four trajectories read step-by-step (min/median/max/random). What the
statistics cannot show: the corpus contains **root-cause fixes** (caught
autocorrect converting a hyphen to an en-dash, disabled Replace-dashes in
AutoCorrect options, retyped — rather than fighting the symptom), **real
recovery sequences** (a genuinely stuck Chrome dialog diagnosed through
hypothesis elimination and cleared by reload), and **programmatic
verification** (cat-ing Chrome's Bookmarks JSON in a terminal to check order
and URLs instead of trusting the rendered UI). Reasoning is grounded — quotes
actual on-screen content throughout; no fabricated state observed. Impurities:
verbose near-identical narration across mechanical loops (a 4x add-bookmark
cycle), and wrong-hypothesis chains during confusion that resolve correctly —
token inefficiency and mixed-value recovery text, not correctness problems.

### The length-quality tension, resolved into a different axis (2026-08-15)

User-raised paradox: short trajectories are accurate but teach no complex
behaviour; long ones carry complexity but risk low-quality actions. Position
taken: **length is a proxy; the real axis is per-step conditional correctness.**
Training is per-step (last-round loss), so a 50-step episode is 50 samples of
"given this state, what now" — good-long means every step defensible in
context (the audited 50-step bookmarks run), bad-long means steps of flailing
(the 43x Ctrl+S era). Our existing metrics (tail runs, state revisitation
0.02-pass vs 0.56-fail, screen-change-per-action) measure exactly this axis,
and the 3.8 corpus's long trajectories pass it.

Recipe placement: OpenWebRL's shortest-per-task rule is optimal for short web
tasks with RL following (complex behaviour comes from RL, not SFT) and should
NOT be copied here; Qwen-CUA keeps long demonstrations and refreshes them
iteratively as the model grows. Ours: success gate + pathology filters, no
length cuts — the mid/long trajectories carrying root-cause fixes and
verification are the desktop-domain asset. The running A/B is the direct test:
B adds harder, longer trajectories (3.6's v11-500 successes: median 27 steps);
sign(B - A) on the frozen eval-50 is this paradox's empirical answer here.
Future refinements if needed: weight by step-productivity, not length; and
teacher-regenerates-what-the-student-fails iteration.

### e1 vs e3, compiled; and the dissociation playbook (2026-08-15)

All 9-task panels, scores + per-step behaviour:

| panel | 1.0s | mean | med steps | repeat% | terminate% |
|---|---|---|---|---|---|
| q35-e1 (own 1-ep anneal) | 1/9 | 0.111 | 50 | 73.0 | 0 |
| q35-e3 seeds 1/2/3 | 3, 0, 0 | 0.333/0/0 | 50 | 41.5/48.1/36.8 | 44/0/0 |
| base-4B (topk panel) | 4/9 | 0.444 | 14 | 14.7 | 78 |

Scores: e1 vs e3 indistinguishable (both average 0.111 across seeds; the panel's
noise swallows everything — the reason eval-50 exists). Behaviour (per-step, so
better powered): e3 repeats less than e1 (~42% vs 73%) and one seed adopted
terminate (44% vs 0) — more epochs deepened absorption of the teacher's format
habits without converting to score. The base row is the indictment: healthier
on every axis. This IS the format-perfect/task-fails dissociation, archived.

Extended to 5 epochs (single panels, no seed replication): ep5pt (rich) 1/9,
rep 52%, term 22%; ep5np (lean) 2/9, rep 39%, term 33%; more3np (lean, 3ep,
more data) 1/9 with **rep 12% — the only SFT arm near base's 15%**. Readings:
the epoch axis is FLAT on scores from 1 through 5 (everything in the 0–3/9
noise band) while behavioural absorption rises monotonically — five epochs of
deeper imitation bought zero score. And the np/lean arms are systematically
the behaviourally healthiest SFT arms at both 3 and 5 epochs — the old data's
weak foreshadowing of the consistency finding, now being tested properly by
the rich/lean pair on eval-50.

Diagnosis playbook for that dissociation, all tooling on the shelf: layer 1
format health (parse rate, enum rate, coordinate range); layer 2 score; the
gap located by ① repeat + state-revisitation (looping) ② wall-rate + median
steps (grinding) ③ terminate calibration incl. false completion claims
④ screen-change-per-action (grounding) ⑤ divergence-point vs the teacher's
trajectory on the same task (`check.py --reference`) ⑥ think-action consistency
by reading ⑦ per-domain channel split. To be run on all four eval-50 arms the
day scores land.
