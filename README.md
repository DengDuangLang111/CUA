# CUA

Generated desktop tasks, teacher trajectories, SFT data/training recipes, evaluation tooling and result viewers. This repository contains source mirrors and documentation; live Windows/WSL and cluster deployments have not been moved by this layout change.

## Start here

| Work | Entry |
|---|---|
| Agent instructions and runtime boundaries | [AGENTS.md](AGENTS.md), [CLAUDE.root.md](CLAUDE.root.md), [runtime mirror mapping](docs/RUNTIME_MIRRORS.md) |
| SFT: data, quality, training, evaluation | [sft/README.md](sft/README.md) |
| Task generation and validation | [taskgen/README.md](taskgen/README.md) |
| RL (GRPO) design and progress | [docs/RL_EXPERIMENT_DESIGN.md](docs/RL_EXPERIMENT_DESIGN.md), [docs/RL_ENV_PLAN.md](docs/RL_ENV_PLAN.md); code and evidence in the sibling `cua-rl-local/` git repository |
| Model/corpus naming | [docs/NAMING.md](docs/NAMING.md), [sft/armname.py](sft/armname.py) |
| Latest recorded status | [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md), with its evidence date; not a live job query |
| Recorded evaluation results | [sft/docs/RESULTS.md](sft/docs/RESULTS.md), section 12 |
| SFT → serving → evaluation | [Checkpoint transfer, Klone serving, model registry, VM allocation, TMAX example and recovery](sft/docs/EVAL_AUTOMATION.md) · [prepare_model.py](sft/scripts/serve/prepare_model.py) · [run_eval.py](sft/scripts/eval/run_eval.py) |
| Trajectory inspection pipeline | [Default workflow for every eval](sft/docs/TRAINING.md#default-evaluation-workflow) · [pipeline, unified catalog and recovery](sft/docs/TRAJECTORY_PIPELINE.md) · [automatic per-task callback](sft/scripts/eval/after_task.py) |
| Operations and shared documentation | [docs/README.md](docs/README.md) |
| Dashboard | [dashboard/README.md](dashboard/README.md) |
| Historical/superseded material | [outdated/README.md](outdated/README.md) |

## Responsibilities

| Area | What belongs here |
|---|---|
| `sft/data/` | Trajectory parsing, dataset construction, integrity checks and format conversion |
| `sft/quality/` | Judging, arbitration, curation and terminal rewriting |
| `sft/analysis/` | Evaluation behavior, thinking/token/action-flow measurements and probes |
| `sft/training/`, `sft/experiments/` | Training adaptations and isolated experiments |
| `sft/scripts/` | Data, train, eval, monitoring and cluster drivers, grouped by purpose |
| `taskgen/generation/` | Taxonomy, generation, shipping and merging |
| `taskgen/validation/`, `taskgen/fixtures/` | Static/VM checks and fixture preparation |
| `taskgen/analysis/`, `taskgen/scripts/` | Coverage analysis and rollout/monitoring drivers |
| `docs/`, domain `docs/`, `reports/`, `reference/` | Shared contracts, domain guides, dated evidence and frozen references |
| `outdated/` | Historical documents, with original evidence retained; archived scripts stay under their domain's `scripts/*/archive/` |
| `dashboard/scripts/` | Shared dashboard health/watchdog helpers; domain-specific publishers live with SFT/taskgen |
| `scripts/`, `tests/` | Only repository-wide maintenance and layout regression checks |

There is no top-level `tools/` or `control/` catch-all. Shared API/legacy trajectory-rendering code remains at `llm.py` and `traj_html.py`. The historical research-report website remains in the sibling `computeragent/cua-experiment-report/` project. The new **standalone trajectory debugger** lives entirely in `sft/analysis/` and uses `sft/scripts/eval/after_task.py`; it has no dependency on that report website.

## Code and runtime boundaries

- Local task-generation code includes historical snapshots. The documented v16 `gen16.py`, `strongjudge.py` and `curate16.py` are not included here; their presence in prose is not evidence that they are implemented locally.
- Source Python modules use the `ostg` package namespace from the live project. This directory is a mirror named CUA; a folder move alone does not install a Python package or update a remote environment.
- `sft/data/build.py` uses the external OSWorld Qwen context/image code. Run runtime-sensitive checks against the correct WSL version.
- Existing remote result/checkpoint paths, flat control-script basenames, datasets and screenshots are unchanged. Follow [docs/RUNTIME_MIRRORS.md](docs/RUNTIME_MIRRORS.md) before deployment.
- Old training/context/failure ledgers and the completed-era strict-corpus plan are under `outdated/`. Their conclusions and commands retain their original scope/date; use the maintained entry guides to select relevant evidence.

## Maintain this layout

Update the owning document rather than creating another summary/status file. Keep active implementation plans in the domain's `plans/`; move completed or superseded records to `outdated/` only after checking their status. Keep agent entry files short and read detailed documents on demand.

The complete source tree below is generated from Git-tracked and non-ignored new files that exist on disk. It excludes Git internals, caches and ignored generated trajectory/report trees. Refresh it after adding or moving a source file:

```bash
python3 scripts/update_readme_tree.py
python3 scripts/update_readme_tree.py --check
python3 -m unittest discover -s tests -v
python3 sft/armname.py selftest
```

These local checks do not launch APIs, VMs, Slurm jobs or model inference. Windows/GPU behavior still requires its actual environment.

## Complete repository structure

<!-- BEGIN REPO TREE -->
```text
CUA/
├── dashboard/
│   ├── scripts/
│   │   ├── dash_probe.sh
│   │   └── dash_watchdog.sh
│   ├── DEPLOY_TRIGGER
│   ├── README.md
│   ├── index.html
│   ├── sft.html
│   ├── sft.json
│   ├── status.json
│   └── vercel.json
├── docs/
│   ├── EXPERIMENTS.md
│   ├── GLOSSARY.md
│   ├── IDEAS.md
│   ├── NAMING.md
│   ├── OPS.md
│   ├── READING.md
│   ├── README.md
│   ├── RL_ENV_PLAN.md
│   ├── RL_EXPERIMENT_DESIGN.md
│   └── RUNTIME_MIRRORS.md
├── eval/
│   ├── qwen35_4b_keepthink.jinja
│   ├── verified_eval100_nonproxy.json
│   └── verified_eval50_nonproxy.json
├── outdated/
│   ├── docs/
│   │   ├── SFT_CONTEXT_20260813.md
│   │   ├── SFT_TRAINING_20260822.md
│   │   ├── TASKGEN_GIT_HISTORY_20260815.md
│   │   └── TASKGEN_SNAPSHOT_20260815.md
│   ├── plans/
│   │   ├── PLAN-20260815-rollout2vm-richrich-eval.md
│   │   ├── PLAN-20260816-armB-bestof3-armC.md
│   │   ├── PLAN-20260818-datagenv12-fmt-w1.md
│   │   ├── PLAN-20260820-targeted100.md
│   │   ├── PLAN-20260822-datagen-v13.md
│   │   ├── PLAN-20260825-datagen-v14.md
│   │   ├── PLAN-20260825-v14-impl.md
│   │   ├── PLAN-20260825-v14-offpolicy-roi.md
│   │   ├── PLAN-20260828-v14g-gold.md
│   │   ├── PLAN-20260829-aws-rollout.md
│   │   ├── PLAN-20260830-v15.md
│   │   ├── PLAN-20260901-strict-corpus.md
│   │   └── V11.md
│   ├── reports/
│   │   └── SFT_FAILURE_ANATOMY_20260903.md
│   ├── OSWORLD_EXPERIMENT_STATUS.md
│   ├── PAIRED_GROUP_EXPERIMENT.md
│   ├── README.md
│   ├── SAMPLING.md
│   ├── TASK_GENERATION_PLAN.md
│   ├── V3_RUN.md
│   └── eval_actions.py
├── reference/
│   ├── osworld-author-runs/
│   │   ├── README.md
│   │   ├── mano-qwen25vl-verified361.args.json
│   │   ├── qwen35-rl-tools_def.json
│   │   ├── qwen36-nothink-v2-300steps.args.json
│   │   ├── qwen36-think-v2-300steps.args.json
│   │   └── qwen37plus-verified361-100steps.args.json
│   ├── EVAL_FAMILY_TAXONOMY.md
│   ├── OSWORLD_V2_RUNTIME_REQUIREMENTS.md
│   └── OSWORLD_VERIFIED_RUNTIME_REQUIREMENTS.md
├── reports/
│   ├── a100-length-probe-20260917/
│   │   ├── results/
│   │   │   ├── cap32k_zero2/
│   │   │   │   ├── exit_code.txt
│   │   │   │   ├── gpu.csv
│   │   │   │   └── train.log
│   │   │   ├── cap48k_zero2/
│   │   │   │   ├── exit_code.txt
│   │   │   │   ├── gpu.csv
│   │   │   │   └── train.log
│   │   │   └── cap64k_frozen_nograd/
│   │   │       ├── train/
│   │   │       │   └── v0-20260917-064332/
│   │   │       │       ├── checkpoint-2/
│   │   │       │       │   └── trainer_state.json
│   │   │       │       ├── args.json
│   │   │       │       └── logging.jsonl
│   │   │       ├── case.txt
│   │   │       ├── exit_code.txt
│   │   │       ├── gpu.csv
│   │   │       ├── sitecustomize.py
│   │   │       └── train.log
│   │   ├── cap32k_actual_selection.json
│   │   ├── checkpoint_verification.json
│   │   ├── length_summary.json
│   │   ├── media_validation.json
│   │   ├── row_lengths.jsonl
│   │   ├── smoke_summary.json
│   │   └── whole_trajectory_retention.json
│   ├── a100-nograd-full-20260917/
│   │   ├── args.json
│   │   ├── launch_validation.json
│   │   ├── status_1306.json
│   │   └── wandb_validation.json
│   ├── histcomp-first50-20260917/
│   │   ├── compression-geometry.json
│   │   ├── doctor.json
│   │   ├── expected-first50.json
│   │   ├── final-scores.json
│   │   ├── launch.json
│   │   ├── plan.json
│   │   ├── previous-first50.json
│   │   ├── regression-diagnosis-17tasks.json
│   │   ├── regression-diagnosis.json
│   │   ├── request.json
│   │   ├── rollout-verification.json
│   │   ├── serving-launch.json
│   │   ├── serving-ready.json
│   │   └── status-at-launch.json
│   ├── klone-krishna-20260917/
│   │   ├── after.json
│   │   ├── before.json
│   │   ├── group_usage_after.json
│   │   ├── hold-a100-1x4-7d.sbatch
│   │   ├── hold-a40-1x3-7d.sbatch
│   │   ├── hold-l40s-1x8-7d.sbatch
│   │   ├── l40s_a40_submissions.json
│   │   └── physical_free_summary.json
│   ├── pipeline-optimization-20260917/
│   │   ├── benchmark.py
│   │   ├── deployment-validation.json
│   │   └── evidence.json
│   ├── r5-v16save143-eval100-20260919/
│   │   ├── average-steps-20tasks.json
│   │   ├── doctor.json
│   │   ├── gpu-before.json
│   │   ├── launch.json
│   │   ├── model-preparation.jsonl
│   │   ├── plan.json
│   │   ├── progress-20260919-1640.json
│   │   ├── progress-20260919-2005.json
│   │   ├── progress-latest.json
│   │   ├── regression-diagnosis-38tasks.json
│   │   ├── regression-diagnosis-90tasks.json
│   │   ├── request.json
│   │   ├── serving-launch.json
│   │   ├── serving-ready.json
│   │   ├── speed-20260919-1646.json
│   │   ├── stall-check-20260919-1745.json
│   │   ├── status-after-start.json
│   │   ├── training-completion.json
│   │   ├── windows-before.json
│   │   ├── windows-benchmark.json
│   │   ├── windows-image-check.json
│   │   ├── windows-initial-capture.json
│   │   ├── workstation-before.json
│   │   ├── workstation-benchmark.json
│   │   ├── workstation-image-check.json
│   │   └── workstation-initial-capture.json
│   ├── r5-v16save143-tf-20260917/
│   │   ├── corpus_manifest.json
│   │   ├── four_job_snapshot.json
│   │   ├── keep_2x8_only.json
│   │   ├── queue_full_20260917.json
│   │   ├── queue_snapshot.json
│   │   ├── squeue_complete.txt
│   │   ├── squeue_default.txt
│   │   ├── submission-1x4.json
│   │   ├── submission-2x2.json
│   │   ├── submission-2x4.json
│   │   └── submission-2x8.json
│   ├── sft-pattern-evidence-20260904/
│   │   ├── portrait-final.png
│   │   ├── six-slides-step80.png
│   │   └── source-pic4.png
│   ├── v16-save-audit-20260917/
│   │   ├── composition/
│   │   │   ├── comparison.json
│   │   │   ├── joined_tasks.jsonl
│   │   │   ├── outcome_evidence_shares.json
│   │   │   ├── sft_sample_shares.json
│   │   │   ├── sources.json
│   │   │   └── v11_admission_audit.json
│   │   ├── full/
│   │   │   ├── audit.json
│   │   │   └── screen.py
│   │   ├── proposed_r5_mix/
│   │   │   ├── criteria.md
│   │   │   ├── multi_review_candidates.jsonl
│   │   │   ├── proposal_counts.json
│   │   │   └── v16_review_candidates.jsonl
│   │   ├── screened554/
│   │   │   ├── audit.json
│   │   │   ├── candidate_ids.jsonl
│   │   │   ├── delivery_requirement_review.jsonl
│   │   │   ├── disk_readback_candidate.jsonl
│   │   │   ├── file_presence_candidate.jsonl
│   │   │   ├── latest_judge_not_admitted.jsonl
│   │   │   ├── review.md
│   │   │   ├── save_action_or_claim_only.jsonl
│   │   │   ├── save_evidence_candidates.jsonl
│   │   │   ├── screen.py
│   │   │   ├── summary.json
│   │   │   └── ui_completion_candidate.jsonl
│   │   ├── audit.json
│   │   ├── gimp-save.png
│   │   ├── latest_judge_not_admitted.jsonl
│   │   ├── manual_save_examples.jsonl
│   │   ├── pdf-save.png
│   │   ├── save_inferred_review_candidate.jsonl
│   │   ├── save_seen_review_candidate.jsonl
│   │   └── text-save.png
│   ├── weekly-20260917/
│   │   ├── assets/
│   │   │   ├── bluetooth-case.png
│   │   │   ├── clickloop-case.png
│   │   │   ├── failure-6.png
│   │   │   ├── failure-9.png
│   │   │   ├── freeze-Freeze_row_column.xlsx
│   │   │   ├── freeze-Freeze_row_column_gold.xlsx
│   │   │   ├── freeze-case.png
│   │   │   ├── paragraph-CCCH9003_Tutorial_guidelines.docx
│   │   │   ├── paragraph-CCCH9003_Tutorial_guidelines_Gold_1.docx
│   │   │   ├── paragraph-CCCH9003_Tutorial_guidelines_Gold_2.docx
│   │   │   ├── paragraph-CCCH9003_Tutorial_guidelines_Gold_3.docx
│   │   │   ├── paragraph-CCCH9003_Tutorial_guidelines_Gold_4.docx
│   │   │   ├── paragraph-case.png
│   │   │   ├── paragraph-repair.png
│   │   │   ├── scrollloop-case.png
│   │   │   ├── subscript-H2O_Factsheet_WA.docx
│   │   │   ├── subscript-H2O_Factsheet_WA_Gold.docx
│   │   │   ├── subscript-case.png
│   │   │   ├── subscript-old.png
│   │   │   ├── success-0.png
│   │   │   ├── success-1.png
│   │   │   ├── table-Table_Of_Work_Effort_Instructions.docx
│   │   │   ├── table-Table_Of_Work_Effort_Instructions_Gold.docx
│   │   │   ├── table-case.png
│   │   │   ├── table-close.png
│   │   │   └── terminal-case.png
│   │   ├── README.md
│   │   ├── additional-failure-evidence.json
│   │   ├── attention-cohort.json
│   │   ├── evidence.json
│   │   ├── failure-analysis.json
│   │   ├── failure-signals.json
│   │   ├── index.html
│   │   ├── repetition-audit.json
│   │   ├── speaker-notes.md
│   │   └── subscript-evidence.json
│   ├── A100_SFT_LENGTH_PROBE_20260917.md
│   ├── ATTENTION_ASYNC_DOWNLOAD_20260917.validation.json
│   ├── CAPTURE_SERVER_OPTIMIZATION_20260917.validation.json
│   ├── FOLDING_SETUPS.md
│   ├── OSWORLD_V2_HARNESS_DIFF_20260915.md
│   ├── OSWORLD_V2_OFFICIAL_0808_WORKSTATION_20260915.patch
│   ├── OSWORLD_V2_REMAINING_20260916.json
│   ├── OSWORLD_V2_THINK_HISTORY_20260915.md
│   ├── OSWORLD_V2_THINK_SHARED_20260915.json
│   ├── OSWORLD_V2_THINK_SHARED_20260915.md
│   ├── OSWORLD_V2_THINK_TWO_HOSTS_20260915.entry.py
│   ├── OSWORLD_V2_THINK_TWO_HOSTS_20260915.sh
│   ├── OSWORLD_V2_THREE_OFFICIAL_REVERTS_20260915.patch
│   ├── OSWORLD_V2_THREE_OFFICIAL_REVERTS_20260915.validation.json
│   ├── OSWORLD_V2_TRAJECTORY_PIPELINE_20260915.md
│   ├── PIPELINE_OPTIMIZATION_REVIEW_20260917.md
│   ├── SFT_DIAGNOSIS_20260904.md
│   ├── SFT_FAILURE_INVENTORY_20260904.json
│   ├── SFT_FAILURE_PATTERNS_20260904.md
│   ├── SIMPLE_EVAL_ROUTING_20260916.validation.json
│   ├── SIX_GPU_IMAGE_CAPTURE_20260917.validation.json
│   ├── THINK_LENGTH_TAKEAWAYS.md
│   ├── TMAX_10F1_VS_20F10_SCORE_STORAGE_20260917.json
│   ├── TMAX_R5_PAIRED_PROGRESS_20260917.json
│   ├── TMAX_SIGNAL_AUDIT_20260917.json
│   ├── TMAX_VERIFIED100_LAUNCH_20260917.validation.json
│   ├── TMAX_VERIFIED100_PROGRESS_20260917.json
│   ├── TMAX_VS_R5_SPEED_20260917.json
│   ├── TRAJECTORY_EXPORT_OPTIMIZATION_20260916.validation.json
│   ├── TRAJECTORY_GROUPING_20260917.validation.json
│   ├── TRAJECTORY_RETENTION_20260916.validation.json
│   ├── TRAJECTORY_STORAGE_20260916.json
│   ├── V11_R5_HYAK_COPY_20260918.json
│   ├── V11_R5_TILLICUM_MERGE_20260919.json
│   └── WSL_OOM_FIX_20260916.validation.json
├── scripts/
│   └── update_readme_tree.py
├── sft/
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── action_acc.py
│   │   ├── attention_download.py
│   │   ├── attention_store.py
│   │   ├── capture.py
│   │   ├── ckptprobe.py
│   │   ├── corpus_tokens.py
│   │   ├── eval_emit_compare.py
│   │   ├── eval_think_dist.py
│   │   ├── flowsim.py
│   │   ├── intervene.py
│   │   ├── panel_difficulty.py
│   │   ├── retention.py
│   │   ├── staircase.py
│   │   ├── termprobe.py
│   │   ├── think_degen.py
│   │   ├── trajectory_catalog.py
│   │   ├── trajectory_index.html
│   │   ├── trajectory_viewer.html
│   │   ├── trajectory_viewer.py
│   │   ├── visual_signals.py
│   │   └── vllm_capture.py
│   ├── data/
│   │   ├── __init__.py
│   │   ├── build.py
│   │   ├── build_truemulti_subset.py
│   │   ├── census.py
│   │   ├── corpusaudit.py
│   │   ├── export.py
│   │   ├── mk_imgwindow_smoke.py
│   │   ├── restore_vision.py
│   │   ├── task_weights.py
│   │   ├── to_swift.py
│   │   ├── traj.py
│   │   ├── verify.py
│   │   └── zip_reader.py
│   ├── docs/
│   │   ├── CHECKPOINTS.md
│   │   ├── CONTEXT.md
│   │   ├── DATA_PIPELINE.md
│   │   ├── DATA_PIPELINE_V16.md
│   │   ├── EVAL_AUTOMATION.md
│   │   ├── JUDGING.md
│   │   ├── KLONE.md
│   │   ├── RESULTS.md
│   │   ├── SFT_DATA.md
│   │   ├── TRAINING.md
│   │   └── TRAJECTORY_PIPELINE.md
│   ├── experiments/
│   │   ├── a100-length-probe-20260917/
│   │   │   ├── profile_lengths.py
│   │   │   ├── sitecustomize.py
│   │   │   ├── smoke.sh
│   │   │   └── verify_checkpoint.py
│   │   ├── a100-nograd-full-20260917/
│   │   │   ├── deployment.json
│   │   │   ├── preflight.py
│   │   │   ├── sitecustomize.py
│   │   │   ├── sync-wandb.py
│   │   │   ├── sync-wandb.sh
│   │   │   └── train-held.sh
│   │   ├── r5-v16save143-tf-20260917/
│   │   │   ├── deployment-4gpu.json
│   │   │   ├── deployment.json
│   │   │   ├── preflight.py
│   │   │   ├── prepare.py
│   │   │   ├── selection.json
│   │   │   ├── train-1x4.sbatch
│   │   │   ├── train-2x2.sbatch
│   │   │   ├── train-2x4.sbatch
│   │   │   └── train-2x8.sbatch
│   │   └── swe_mem/
│   │       ├── README.md
│   │       ├── __init__.py
│   │       ├── prepare_copy.py
│   │       └── test_prepare_copy.py
│   ├── plans/
│   │   ├── PLAN-20260914-visual-signal-monitoring.md
│   │   └── PLAN-20260915-tmax9b-r5-cua-sft.md
│   ├── quality/
│   │   ├── __init__.py
│   │   ├── arb.py
│   │   ├── check.py
│   │   ├── curate.py
│   │   ├── stepaudit.py
│   │   ├── terminalfix.py
│   │   └── trajaudit.py
│   ├── scripts/
│   │   ├── archive/
│   │   │   ├── README.md
│   │   │   ├── chain_eval_btf.sh
│   │   │   ├── chain_eval_cap1p5.sh
│   │   │   ├── chain_eval_lr.sh
│   │   │   ├── chain_eval_lr1e6.sh
│   │   │   ├── chain_eval_r5m.sh
│   │   │   ├── chain_eval_rest.sh
│   │   │   ├── chain_eval_w20.sh
│   │   │   ├── chain_eval_w20f.sh
│   │   │   ├── chain_eval_w20g.sh
│   │   │   ├── run_eval50_b1ep.sh
│   │   │   ├── run_eval50_bhqs.sh
│   │   │   ├── run_eval50_bhqs2lr.sh
│   │   │   ├── run_eval50_bs.sh
│   │   │   ├── run_eval50_bs_resume.sh
│   │   │   ├── run_eval50_gb128.sh
│   │   │   ├── run_eval50_gb128ep2.sh
│   │   │   ├── run_eval50_gb64_early.sh
│   │   │   ├── run_eval50_gb64_phaseB.sh
│   │   │   ├── run_eval50_klone.sh
│   │   │   ├── run_eval50_lean_stock.sh
│   │   │   ├── run_eval50_lora.sh
│   │   │   ├── run_eval50_mixb4b.sh
│   │   │   ├── run_eval50_mixc9b.sh
│   │   │   ├── run_eval50_richstock.sh
│   │   │   └── run_eval50_stock.sh
│   │   ├── cluster/
│   │   │   ├── gpufree.awk
│   │   │   └── gpus.sh
│   │   ├── data/
│   │   │   ├── arb_stream.sh
│   │   │   ├── pipeline.sh
│   │   │   └── ship_dataset.sh
│   │   ├── eval/
│   │   │   ├── capture_runtime/
│   │   │   │   └── sitecustomize.py
│   │   │   ├── after_task.py
│   │   │   ├── chain_eval.sh
│   │   │   ├── chain_eval_arms.tsv
│   │   │   ├── cleanup_capture.py
│   │   │   ├── eval_more3_pair.sh
│   │   │   ├── eval_registry.example.json
│   │   │   ├── final_evals.sh
│   │   │   ├── launch_captured.py
│   │   │   ├── maintenance.py
│   │   │   ├── run_arm.sh
│   │   │   └── run_eval.py
│   │   ├── monitor/
│   │   │   ├── sft_dash.py
│   │   │   └── sft_dash_daemon.sh
│   │   ├── serve/
│   │   │   ├── visual_capture/
│   │   │   │   └── sitecustomize.py
│   │   │   ├── prepare_model.example.json
│   │   │   └── prepare_model.py
│   │   ├── train/
│   │   │   ├── archive/
│   │   │   │   ├── README.md
│   │   │   │   ├── ckptprobe-all.sbatch
│   │   │   │   ├── merge-lora-bs.sbatch
│   │   │   │   ├── mixA-9b-resume.sbatch
│   │   │   │   ├── mixB-9b-resume.sbatch
│   │   │   │   ├── mixbtf4b-cap2x-sp2-smoke.sbatch
│   │   │   │   ├── mixbtf9b-2x4-lr1e5-resume.sbatch
│   │   │   │   ├── mixbtf9b-2x4-resume.sbatch
│   │   │   │   ├── mixbtf9b-histcomp-smoke.sbatch
│   │   │   │   ├── mixbtf9b-taskw-smoke.sbatch
│   │   │   │   ├── probe-z3a16.sbatch
│   │   │   │   ├── serve-chain-38-i-261.sbatch
│   │   │   │   ├── serve-chain-38-i.sbatch
│   │   │   │   ├── serve-chain-4b-b1ep.sbatch
│   │   │   │   ├── serve-chain-4b-base-stock.sbatch
│   │   │   │   ├── serve-chain-4b-bhqs.sbatch
│   │   │   │   ├── serve-chain-4b-bhqs2lr.sbatch
│   │   │   │   ├── serve-chain-4b-bs-stock.sbatch
│   │   │   │   ├── serve-chain-4b-bs.sbatch
│   │   │   │   ├── serve-chain-4b-gb128.sbatch
│   │   │   │   ├── serve-chain-4b-gb128ep2.sbatch
│   │   │   │   ├── serve-chain-4b-gb64e15-stock.sbatch
│   │   │   │   ├── serve-chain-4b-img3-stock.sbatch
│   │   │   │   ├── serve-chain-4b-lean-stock.sbatch
│   │   │   │   ├── serve-chain-4b-lora-stock.sbatch
│   │   │   │   ├── serve-chain-4b-lora.sbatch
│   │   │   │   ├── serve-chain-4b-loralean-stock.sbatch
│   │   │   │   ├── serve-chain-4b-loranp-stock.sbatch
│   │   │   │   ├── serve-chain-4b-lr3e6-stock.sbatch
│   │   │   │   ├── serve-chain-4b-nocap-stock.sbatch
│   │   │   │   ├── serve-chain-4b-rich-official.sbatch
│   │   │   │   ├── serve-chain-4b-rich150.sbatch
│   │   │   │   ├── serve-chain-9b-base-261.sbatch
│   │   │   │   ├── serve-chain-img10-a2261.sbatch
│   │   │   │   ├── serve-chain-vl-base-stock.sbatch
│   │   │   │   ├── serve-chain-vl-r5vl-stock.sbatch
│   │   │   │   ├── serve-chain-vl20-stock.sbatch
│   │   │   │   ├── serve-chain-vl20g-stock.sbatch
│   │   │   │   ├── serve-chain-vl3b-stock.sbatch
│   │   │   │   ├── serve-chain-vl3gb128-stock.sbatch
│   │   │   │   ├── serve-klone-a100-mixb4b.sbatch
│   │   │   │   ├── sft-q38B-gb128.sbatch
│   │   │   │   ├── sft-q38B-gb128o.sbatch
│   │   │   │   ├── sft-q38B-gb64o.sbatch
│   │   │   │   ├── sft-q38B.sbatch
│   │   │   │   ├── sft-q38Bhqs-gb64.sbatch
│   │   │   │   ├── sft-q38Bhqs-lr3e6.sbatch
│   │   │   │   ├── sft-q38Bhqs-lr5e6.sbatch
│   │   │   │   ├── sft-q38Bhqs2t-g8.sbatch
│   │   │   │   ├── sft-q38Bhqs2t-gb64-r5.sbatch
│   │   │   │   ├── sft-q38Bhqs2t-gb64.sbatch
│   │   │   │   ├── sft-q38Bhqs2t-lora-g8.sbatch
│   │   │   │   ├── sft-q38Bhqs2t-lora-lean-g8.sbatch
│   │   │   │   ├── sft-q38Bhqs2t-lora-noprose-g8.sbatch
│   │   │   │   ├── sft-q38Bhqs2t-lr3e6-gb64.sbatch
│   │   │   │   ├── sft-q38Bs-gb64.sbatch
│   │   │   │   ├── sft-q38Bs-lora.sbatch
│   │   │   │   ├── sft-q38e1B.sbatch
│   │   │   │   ├── sft-q38lean.sbatch
│   │   │   │   ├── sft-q38rich.sbatch
│   │   │   │   ├── sft-vl20pic-gb128-lr1e5.sbatch
│   │   │   │   ├── sft-vl20pic-gb128-resume.sbatch
│   │   │   │   ├── sft-vl20pic-lr1e5.sbatch
│   │   │   │   ├── sft-vl3pic-base.sbatch
│   │   │   │   └── sft-vl3pic-gb128-lr1e5.sbatch
│   │   │   ├── mixA-4b.sbatch
│   │   │   ├── mixA-9b.sbatch
│   │   │   ├── mixB-4b.sbatch
│   │   │   ├── mixB-9b-lr1e5-1ep.sbatch
│   │   │   ├── mixB-9b-lr1e5-b999.sbatch
│   │   │   ├── mixB-9b-lr2e5-1ep.sbatch
│   │   │   ├── mixB-9b-lr2e5-gb128.sbatch
│   │   │   ├── mixB-9b-swemem.sbatch
│   │   │   ├── mixB-9b.sbatch
│   │   │   ├── mixC-9b.sbatch
│   │   │   ├── mixR5M-9b.sbatch
│   │   │   ├── mixaw9b.sbatch
│   │   │   ├── mixbtf4b-cap1p5.sbatch
│   │   │   ├── mixbtf4b-cap2x-ml65k.sbatch
│   │   │   ├── mixbtf4b-cap2x.sbatch
│   │   │   ├── mixbtf9b-2x4-lr1e5.sbatch
│   │   │   ├── mixbtf9b-2x4-lr1e6.sbatch
│   │   │   ├── mixbtf9b-2x4.sbatch
│   │   │   ├── mixbtf9b-histcomp.sbatch
│   │   │   ├── mixbtf9b-taskw.sbatch
│   │   │   ├── mixbtf9b.sbatch
│   │   │   ├── pick_ckpt.sh
│   │   │   ├── tillicum_chain.sh
│   │   │   └── tmax9b-r5.sbatch
│   │   └── README.md
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── benchmark_capture_overhead.py
│   │   ├── test_attention_download.py
│   │   ├── test_attention_store.py
│   │   ├── test_capture.py
│   │   ├── test_export_memory.py
│   │   ├── test_export_optimization.py
│   │   ├── test_filters.py
│   │   ├── test_image_only_capture.py
│   │   ├── test_maintenance.py
│   │   ├── test_pipeline_workers.py
│   │   ├── test_prepare_model.py
│   │   ├── test_restore_vision.py
│   │   ├── test_retention.py
│   │   ├── test_run_eval.py
│   │   ├── test_teacher_routing.py
│   │   ├── test_trajectory_catalog.py
│   │   ├── test_visual_signals.py
│   │   ├── test_vllm_capture.py
│   │   └── typefix_gate.py
│   ├── training/
│   │   ├── histcomp/
│   │   │   └── sitecustomize.py
│   │   └── __init__.py
│   ├── README.md
│   ├── __init__.py
│   └── armname.py
├── taskgen/
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── coverage_audit.py
│   │   ├── family_census.py
│   │   ├── fixture_type_audit.py
│   │   ├── pool_vet.py
│   │   ├── taskfit.py
│   │   └── taxonomy_tag.py
│   ├── docs/
│   │   ├── PIPELINE.md
│   │   └── RUNBOOK.md
│   ├── fixtures/
│   │   ├── __init__.py
│   │   ├── deck_fixtures_v11.py
│   │   └── prebuild.py
│   ├── generation/
│   │   ├── __init__.py
│   │   ├── gen.py
│   │   ├── merge.py
│   │   ├── ship.py
│   │   └── taxonomy.py
│   ├── prompts/
│   │   └── single_json.txt
│   ├── scripts/
│   │   ├── archive/
│   │   │   ├── README.md
│   │   │   ├── tools_pilot_fold.sh
│   │   │   ├── tools_pilot_fold2.sh
│   │   │   ├── tools_pilot_fold3.sh
│   │   │   ├── tools_pilot_fold4.sh
│   │   │   ├── tools_pilot_fold5.sh
│   │   │   ├── tools_pilot_fold6.sh
│   │   │   ├── tools_pilot_status.sh
│   │   │   └── tools_v11_reroll.sh
│   │   ├── monitor/
│   │   │   └── dash_status_daemon.sh
│   │   ├── rollout/
│   │   │   └── v11_500_fp8.sh
│   │   └── README.md
│   ├── validation/
│   │   ├── __init__.py
│   │   ├── accept.py
│   │   ├── audit.py
│   │   ├── control.py
│   │   ├── gold.py
│   │   └── scan.py
│   ├── README.md
│   └── __init__.py
├── tests/
│   └── test_repo_layout.py
├── .gitignore
├── .vercelignore
├── AGENTS.md
├── CLAUDE.root.md
├── README.md
├── __init__.py
├── llm.py
├── traj_html.py
└── vercel.json
```
<!-- END REPO TREE -->
