# outdated/

Historical documents kept for the record, superseded by current docs at the
repo root. Nothing here describes the current pipeline.

| file | era | superseded by |
|---|---|---|
| V3_RUN.md | v3 generation round (2026-08-08) | EXPERIMENTS.md + V11.md |
| SAMPLING.md | v3-era sampling/contamination boundary (中文, pre-English repo) | EXPERIMENTS.md taxonomy sections |
| eval_actions.py | the teacher-forced action exam (2026-08-13) | tier-3 rollout on held-out tasks |
| TASK_GENERATION_PLAN.md | v7-era 方案记录(顶层收编, 2026-08-15) | TASKGEN_PIPELINE.md + RUNBOOK.md + EXPERIMENTS.md |
| PAIRED_GROUP_EXPERIMENT.md | 配对组实验草案(暂缓) | EXPERIMENTS.md 主线 |
| OSWORLD_EXPERIMENT_STATUS.md | 官方 361 campaign 状态页(停在 07-31) | EXPERIMENTS.md 顶部现状块 |

**Why the action exam was retired (2026-08-13):** teacher forcing hands the
model a correct history at every step, so a policy that has stopped reading its
observation still scores well. It ranked the checkpoint that solved 1/9 real
tasks as the best model on its panel (0.800 action-type accuracy, above the
stock model's 0.775), and rendered the fatal copy-previous-response defect as a
benign "phase lag" — a reading that the rollout then falsified. Its two think
metrics were both artifacts (tag placement, then hallucinated extra rounds).
Kept here because the code is a serviceable format smoke-test; it is not a
quality measurement. See sft/TRAINING.md, "Which number decides what".
