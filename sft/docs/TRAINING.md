# Training and evaluation: current entry guide

Updated on 2026-09-16, including checkpoint preparation and the user's default evaluation workflow. This guide describes where to find the code and configuration; it does not assert that any job is running or that old results have been re-evaluated.

## Inputs and configuration

1. Resolve model/corpus names with [armname.py](../armname.py) and the [naming contract](../../docs/NAMING.md).
2. Use [data preparation](DATA_PIPELINE.md), or [the v16-specific contract](DATA_PIPELINE_V16.md), for the relevant corpus version.
3. Read the actual recipe in [scripts/train/](../scripts/train/) and the chosen checkpoint's saved args. The recipe name does not uniquely identify weights or a dataset revision.
4. Use [KLONE.md](KLONE.md) and [operations](../../docs/OPS.md) for the target environment. Machine/port/job values in dated records require fresh verification.

## SFT recipe reference

Common values of the Tillicum H200 arms through 2026-09-02 (for example `mixB-9b.sbatch`, `mixbtf9b*.sbatch`). They are not a description of any single checkpoint: confirm an arm against its sbatch and the checkpoint's `args.json`. Flags that an sbatch does not set take framework defaults, and early arms differ there (`weight_decay 0.1` / `adam_beta2 0.95` before the gb64o arm). Klone runs the same recipe with different sharding ([KLONE.md](KLONE.md)).

| Setting | Value | Note |
|---|---|---|
| Tuning | `--tuner_type full` | Full-parameter. |
| Loss | `--loss_scale last_round` | Loss only on the final assistant turn: its `<think>`, reasoning, `</think>`, answer, `<tool_call>` and closing `<\|im_end\|>`. System prompt, images, user/tool turns and all earlier assistant turns have weight 0. Each step of a trajectory is its own sample with the earlier steps as weight-0 context, so weight 0 on history does not lose supervision (measured: 100% of steps supervised on v11100, 99.7% on v11500). ms-swift appends `+ignore_empty_think` automatically; our corpora contain 0 empty think blocks, so it never changes the loss. img10 (6,474 rows): supervised tokens per sample median 147, mean 319, max 9,712. |
| Learning rate | `3e-6`, cosine, `--warmup_ratio 0.1` | The cosine spans the run's total steps. |
| Epochs | 3 | Validation-loss checkpoint selection was retired on 2026-08-25 (it did not pick the better checkpoint in three comparisons); new corpora are built without `--val-ratio`, and the default checkpoint is the epoch-3 endpoint. |
| Global batch | 64, per-device batch 1 | Global batch = ranks × 1 × accum. |
| Optimizer | `--weight_decay 0.0 --adam_beta2 0.999` | Set explicitly from gb64o on to match OpenWebRL; no clean arm has tested whether this helps. `max_grad_norm 1.0`: the measured pre-clip gradient norm was always above 1 (2026-08-17 runs), so every update is clipped. |
| Memory | bf16, `--deepspeed zero2_offload`, `--attn_impl sdpa`, `--gradient_checkpointing true` | See [Batch, accumulation and memory](#batch-accumulation-and-memory). |
| Images | `IMAGE_MAX_TOKEN_NUM=2048` | A 1920×1088 screenshot is 2040 visual tokens; 1024 would downsample training images relative to rollout. The image window (img10 = 10 screenshots) is fixed when the corpus is built, not in the sbatch. |
| `--max_length` | 65536 is enough for img10; 20-image windows need 81920 | img10 longest sample 58,047 (v16 at img10: 53,859); 20-image corpora had 11–14 samples above 65536 (max 72,594). Some sbatches keep 81920 on img10 as a safety margin. Over-length samples are dropped without a log line (`truncation_strategy=delete`, [DATA_PIPELINE.md §5](DATA_PIPELINE.md)). |
| Logging | `--logging_steps 1` | User rule 2026-09-02. Older templates (`img10-*`, `mixaw9b`) use 2; change it when deriving a new sbatch. |
| Topology | At most 2 nodes (user rule 2026-09-01): gb64 = 2 nodes × 2 GPUs × accum 16, or 2 × 4 × accum 8 | Change `#SBATCH --nodes`, `NNODES` and `srun --ntasks` together. Derive `MASTER_PORT=$((20000 + SLURM_JOB_ID % 9000))`; a fixed port collides on shared nodes. `--mem` is limited to 240G per GPU and CPUs to 8 per GPU. |

Environment (Tillicum, `$B` = `/gpfs/scrubbed/jy050706/sft`): uv venv with Python 3.11; ms-swift from git (4.5.0.dev0, because PyPI 4.4.2 fails with transformers 5.x); `zero2_offload` builds DeepSpeed CPU Adam with nvcc from a user-space CUDA 13 (`CUDA_HOME=$B/cuda13`), because the cluster provides no CUDA toolkit; flash-attn is not installed, so attention is `sdpa` and `padding_free` is unavailable. Package versions: [KLONE.md §2](KLONE.md). Package installs, model downloads and training run inside sbatch jobs; the login node only edits files and submits jobs.

### Steps and checkpoints

- `per_rank = N // ranks`, then `steps_per_epoch = ceil(per_rank / accum)`, where N is the row count of the corpus actually launched. Example: 6,474 rows, 8 ranks, accum 8 → 102 steps/epoch, 306 for 3 epochs. Steps/epoch ≈ N / global batch for any rank × accum split. `preflight.py` checks this before launch ([DATA_PIPELINE.md §9.1](DATA_PIPELINE.md)).
- `save_steps` must divide steps/epoch. Default: two checkpoints per epoch (`save_steps = steps_per_epoch / 2`), which needs an even steps/epoch. If a global batch fixed for comparison gives an odd value, keep the global batch and save once per epoch (`save_steps = steps_per_epoch`; e.g. 7,311 rows at gb64 → 115). Every epoch boundary must have a checkpoint. Print steps/epoch and `save_steps` in the job log.
- `save_total_limit` must be at least the number of checkpoints + 1; otherwise rotation deletes the epoch-1 checkpoint first, without an error.
- A mid-run checkpoint of a longer run is not equivalent to a shorter run, because the cosine spans the total steps: a 5-epoch run's epoch-3 checkpoint was at 38% of peak LR, while a 3-epoch run ends at 0.
- A 9B checkpoint is 136 GB: 18.8 GB weights + 119 GB DeepSpeed optimizer state. `--save_only_model true` keeps only the 18.8 GB but disables `--resume_from_checkpoint`.

### Batch, accumulation and memory

- At the same global batch, the split between ranks, per-device batch and accumulation does not change the gradient: swift divides the summed loss by the number of supervised tokens all-reduced over the whole global batch (`average_tokens_across_devices=True`, `seq2seq_trainer.py:196-202`). Only bf16 summation order and RNG differ.
- Peak GPU memory is set by per-device batch and sequence length, not by accumulation (8 GPUs, bs2: accum 4 → 108,617 MiB, accum 8 → 109,763 MiB). The exception is the external loss path, which keeps about 250 MB per micro-batch (about the size of the response logits). That path is forced by `enable_channel_loss` (`seq2seq_trainer.py:134`, and by non-binary `loss_scale` values such as `hermes`), not by `last_round`, which uses the internal path (source reading, 2026-08-22). `enable_channel_loss` does not enter the gradient; it only logs per-domain `loss_<channel>` metrics (`:175-181`).
- Feasible region measured on H200 on 2026-08-17 (gb128 attempts): accum 4 → 131.9 GiB, stable; accum 16 → died at steps 8–13 near 137 GiB; accum 32/64 → died before step 1 at 137.6–137.9 GiB; the same with any GPU count and with ZeRO-3. Result: per-device batch 1 and accum ≤ 8. One accum-64 run with `enable_channel_loss` off still peaked at 137.87 GiB, which contradicts the 2026-08-22 source reading; it has not been re-measured.
- The image window is the effective memory lever. Same topology (4 nodes × 2 GPUs, accum 8): 4B with 20 images 136.70 GiB (97.8%), 4B img10 89.66 GiB, 9B img10 115.80 GiB (82.8%). ZeRO-3 ran out of memory before step 1 on long sequences (job 249480); the Liger kernel saves only 0.5–1 GB; sequence parallel is capped at 4 by the KV heads and turns off `use_logits_to_keep`.
- 2 nodes × 4 GPUs with `sdpa`: the cuDNN SDPA kernel failed twice on rank 6 (`mha_graph.execute(...)` error; job 272551 at step 458/870, 272837 at 541/870; 4 × 2 arms never hit it; cause not investigated). Fix without code changes: a `sitecustomize.py` calling `torch.backends.cuda.enable_cudnn_sdp(False)` on `PYTHONPATH` (`$B/nocudnn`). sacct reports such a job as COMPLETED 0:0; check the `.0` step or the `EXIT_<arm>` line in the log.

### Reading throughput

- tqdm `s/it` on a resumed job divides the wall time by all steps, including the skipped ones (job 249176: 323 s/it real, 88.03 displayed; [DATA_PIPELINE.md §8](DATA_PIPELINE.md)). Confirm a job is not resumed before citing its `s/it`.
- The 2026-08-19 data did not establish any effect of topology on throughput at the same global batch. The established difference was scheduling: with 22 idle GPUs spread over 11 nodes, an 8 nodes × 1 GPU job started in 19 s, while 2 nodes × 8 GPUs was predicted to wait 8 h.
- 2026-09-01, same 9B gb64 recipe: 4 nodes × 2 GPUs × accum 8 → 70.6–72.4 s/it; 2 × 2 × accum 16 → 130–133 s/it (half the GPUs, about twice the step time; 870 steps ≈ 32 h, over a 24 h job limit). The 2-node limit is a user rule; only the user can relax it.

## Local code route

`data/traj.py -> data/build.py -> data/verify.py -> data/to_swift.py` is the basic sample-building route. [scripts/data/pipeline.sh](../scripts/data/pipeline.sh) invokes it, with census first. Audits and curation live under [quality/](../quality/); they are separate from neutral format conversion.

The builder imports context/image functions from the external OSWorld Qwen harness. Match that runtime to the evaluated/trained setup; a local source relocation does not update either Windows machine. [Context contract](CONTEXT.md).

Training is launched through [scripts/train/](../scripts/train/) recipes. Evaluation orchestration is under [scripts/eval/](../scripts/eval/). These paths are the reorganized repository layout, not proof of remote deployment.

## Default evaluation workflow

For a newly trained model, begin with [从 SFT 到评测：复用入口](EVAL_AUTOMATION.md#从-sft-到评测复用入口): select the exact completed checkpoint, use `prepare_model.py` on Tillicum for verified transfer and one Klone serving submission, then register the ready endpoint for the selected Windows hosts. The guide contains the TMAX step306 → Verified100 example and recovery table. Preparation and evaluation use the same unique model ID; new models do not need custom transfer, serving or eval scripts. The preparation helper has local tests; actual remote deployment/readiness must still be verified.

For new campaigns, follow [EVAL_AUTOMATION.md](EVAL_AUTOMATION.md): one registry and `run_eval.py` handle model identity, pinned task panels, host allocation, preflight, isolated task execution and resume. Existing running native batches are not silently replaced.

**User instruction, 2026-09-15: every new or resumed CUA evaluation must enable the standalone trajectory pipeline by default, unless the user explicitly opts out for that run.** Treat this as part of running the evaluation, not an optional follow-up requiring another request.

After **each task finishes**, [after_task.py](../scripts/eval/after_task.py) publishes a durable ready record. Rollout saves raw data first. Its separate `process-pending` worker generates the full trajectory graph, original screenshot/action views, evaluator evidence, task JSON/HTML and shared Index. Run the worker later, or use `--watch` as a separate process for automatic per-task updates. Use the existing callback and templates; do not write task-specific pages or wait until the entire evaluation finishes. Do not run the whole-site `refresh` command after every task: the worker uses `render_task` for each ready task.

The authoritative commands and field definitions are in the [trajectory pipeline guide](TRAJECTORY_PIPELINE.md). Before each launch:

1. Verify the actual host, native task function and result root. Both Verified and V2 native runners support the idempotent startup hook; verify it in the actual worker environment. Earlier historical-only exports do not prove a live hook is installed.
2. Reuse the host's registered result/output roots. Set `collection: "eval"` for real evaluations, including the eight-task OSWorld2 run; use `collection: "test"` only for developing/debugging new features. Do not create a new website for each model/run.
3. Set `CUA_INSPECTION_CONFIG` and the startup-hook PYTHONPATH before workers start. Prefer native runners with `capture_runtime/sitecustomize.py`; do not add a second wrapper to an already wrapped launcher. Actual attention also requires the matching instrumented model server.
4. Run a separate `process-pending --watch` worker and the source viewer. The fixed catalog merges registered viewers automatically; completed tasks appear in its formal/test section. Verify the first task's raw artifacts, integrity report, screenshots and catalog membership.
5. Recover page failures with `render` / `render-run` from saved files. Legacy `refresh` / `refresh-pages` reconstruct evaluator descriptions from current JSON configs and are not generic refresh commands for newly captured V2 runs.

The recorder retains existing interrupted trajectory rows when capture is enabled on resume. It hashes the original prefix and keeps the native log unchanged. Runtime capture failures are logged and do not substitute scores or model actions. Check both raw request artifacts and the generated page after the first task; a valid HTML page by itself is not proof that attention was collected.

Keep screenshots on their original Windows/WSL host. Generate only source-backed evidence: missing attention or evaluator input artifacts stay unavailable. Enabling webpage generation does not itself collect attention or recover historical comparison files.

## Results and evidence

- [RESULTS.md](RESULTS.md), section 12, indexes experiment purposes and recorded results.
- [sft/docs/CHECKPOINTS.md](CHECKPOINTS.md) maps historical artifacts; verify the selected artifact itself.
- [Current dated investigations](../../reports/) qualify older failure claims.

## Checks after code changes

Run the focused [filter tests](../tests/test_filters.py), relevant dataset verification, and the naming self-test for recipe changes. Run on the actual intended environment for runtime/GPU behavior. Documentation-only changes do not require a GPU job.

<!-- REPO NAV -->
[Repository map](../../README.md)
<!-- /REPO NAV -->
