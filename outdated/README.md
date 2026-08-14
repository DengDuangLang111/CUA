# outdated/

Historical documents kept for the record, superseded by current docs at the
repo root. Nothing here describes the current pipeline.

| file | era | superseded by |
|---|---|---|
| V3_RUN.md | v3 generation round (2026-08-08) | EXPERIMENTS.md + V11.md |
| SAMPLING.md | v3-era sampling/contamination boundary (中文, pre-English repo) | EXPERIMENTS.md taxonomy sections |
| eval_actions.py | the teacher-forced action exam (2026-08-13) | tier-3 rollout on held-out tasks |

**Why the action exam was retired (2026-08-13):** teacher forcing hands the
model a correct history at every step, so a policy that has stopped reading its
observation still scores well. It ranked the checkpoint that solved 1/9 real
tasks as the best model on its panel (0.800 action-type accuracy, above the
stock model's 0.775), and rendered the fatal copy-previous-response defect as a
benign "phase lag" — a reading that the rollout then falsified. Its two think
metrics were both artifacts (tag placement, then hallucinated extra rounds).
Kept here because the code is a serviceable format smoke-test; it is not a
quality measurement. See sft/TRAINING.md, "Which number decides what".
