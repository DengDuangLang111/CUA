# Training and evaluation: current entry guide

Updated on 2026-09-16, including checkpoint preparation and the user's default evaluation workflow. This guide describes where to find the code and configuration; it does not assert that any job is running or that old results have been re-evaluated.

## Inputs and configuration

1. Resolve model/corpus names with [armname.py](../armname.py) and the [naming contract](../../docs/NAMING.md).
2. Use [data preparation](DATA_PIPELINE.md), or [the v16-specific contract](DATA_PIPELINE_V16.md), for the relevant corpus version.
3. Read the actual recipe in [scripts/train/](../scripts/train/) and the chosen checkpoint's saved args. The recipe name does not uniquely identify weights or a dataset revision.
4. Use [KLONE.md](KLONE.md) and [operations](../../docs/OPS.md) for the target environment. Machine/port/job values in dated records require fresh verification.

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
- [Historical training ledger](../../outdated/docs/SFT_TRAINING_20260822.md) preserves the earlier environment setup, flags, experiments and incidents without presenting its old status block as current.

## Checks after code changes

Run the focused [filter tests](../tests/test_filters.py), relevant dataset verification, and the naming self-test for recipe changes. Run on the actual intended environment for runtime/GPU behavior. Documentation-only changes do not require a GPU job.

<!-- REPO NAV -->
[Repository map](../../README.md)
<!-- /REPO NAV -->
