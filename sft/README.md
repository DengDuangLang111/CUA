# SFT: data, quality, training and evaluation

This directory contains local code mirrors and research tooling, organized by responsibility. Folder placement is not evidence that a job is currently running. Live harness/data changes still require a fresh Windows/WSL baseline; see [runtime ownership](../docs/RUNTIME_MIRRORS.md).

| Folder | Use it for |
|---|---|
| [data/](data/) | Reconstruct trajectories, build/verify/export datasets, make corpus variants |
| [quality/](quality/) | Trajectory/step audits, arbitration, curation and terminal normalization |
| [analysis/](analysis/) | Evaluation behavior, thinking/token measurements, action-flow comparisons and checkpoint probes |
| [training/](training/) | Training-time adaptations, currently history-image resolution |
| [experiments/](experiments/) | Isolated experimental methods, currently SWE-MeM weighting |
| [tests/](tests/) | Dataset/filter and harness-parser checks |
| [scripts/](scripts/) | Data shipping, Slurm recipes, evaluation and monitoring drivers |
| [docs/](docs/) | Data contracts, training guide, result ledger, judging and cluster procedures |
| [plans/](plans/) | Work that is still being designed/implemented |
| [armname.py](armname.py) | The existing model/corpus naming generator; [naming contract](../docs/NAMING.md) |

Start with [training](docs/TRAINING.md), [context](docs/CONTEXT.md), [v11 data preparation](docs/DATA_PIPELINE.md), [v16 differences](docs/DATA_PIPELINE_V16.md), or [results](docs/RESULTS.md).

[TMAX-9B → v11 r5 CUA SFT plan](plans/PLAN-20260915-tmax9b-r5-cua-sft.md) records the downloaded terminal-RL checkpoint, required visual-module restoration, frozen r5 corpus and matched SFT/evaluation protocol. Tillicum job 296948 requests four H200 GPUs for direct training; see the plan for its recorded status.

Use [EVAL_AUTOMATION.md](docs/EVAL_AUTOMATION.md) for the reusable model/benchmark/panel registry, unique run IDs, fixed two-host allocation, isolated task attempts, status and resume commands. Its preparation section covers [prepare_model.py](scripts/serve/prepare_model.py): explicit Tillicum checkpoint → resumable verified transfer → one Klone Slurm service. Register the ready endpoint once, then use the existing eval commands. Preparation does not launch evaluations.

For every new/resumed evaluation, use the [default evaluation workflow](docs/TRAINING.md#default-evaluation-workflow): save raw records and publish a ready entry after each task; use the separate `process-pending` worker for trajectory pages and Index updates. Verify/enable the real callback before launching workers.

The **standalone trajectory debugger** has one fixed catalog with **Formal Eval** and **Feature tests** sections. Formal Eval includes the historical six source runs (500 tasks) and the eight-task OSWorld2 evaluation; test runs exist only to develop/verify features. The catalog reads registered viewers automatically while original screenshots and attention files stay on Windows/WSL. Follow the [pipeline guide](docs/TRAJECTORY_PIPELINE.md) for launch profiles, the ready queue, serving, navigation, heatmap definitions, maintenance and recovery.

The [visual-signal plan](plans/PLAN-20260914-visual-signal-monitoring.md) retains design scope and dated validation, including historical v11/v16/teacher/MixB/history-compression imports. A recorded deployment or acceptance count is not a live availability check. Historical runs without attention or evaluator inputs remain explicitly unavailable for those fields.

The old mixed training/context/failure ledgers are preserved under [outdated/](../outdated/README.md). Exact checkpoint arguments and actual evaluation records take precedence over old prose or copied sbatch comments.

Swift message serialization is implemented once in [data/to_swift.py](data/to_swift.py). [data/export.py](data/export.py) keeps its legacy CLI/default fields, and the SWE-MeM adapter adds its own paths/weights; both reuse that serializer. See [the serialization contract](docs/SFT_DATA.md#serialization-implementation-2026-09-14).

<!-- REPO NAV -->
[Repository map](../README.md)
<!-- /REPO NAV -->
