# outdated/

Historical documents kept for the record, superseded by maintained guides under
`docs/`, `sft/docs/` and `taskgen/docs/`. Nothing here describes the current pipeline.

| file | era | superseded by |
|---|---|---|
| V3_RUN.md | v3 generation round (2026-08-08) | docs/EXPERIMENTS.md + plans/V11.md |
| SAMPLING.md | v3-era sampling/contamination boundary (中文, pre-English repo) | docs/EXPERIMENTS.md taxonomy sections |
| eval_actions.py | the teacher-forced action exam (2026-08-13) | tier-3 rollout on held-out tasks |
| TASK_GENERATION_PLAN.md | v7-era 方案记录(顶层收编, 2026-08-15) | taskgen/docs/PIPELINE.md + taskgen/docs/RUNBOOK.md + docs/EXPERIMENTS.md |
| PAIRED_GROUP_EXPERIMENT.md | 配对组实验草案(暂缓) | docs/EXPERIMENTS.md 主线 |
| OSWORLD_EXPERIMENT_STATUS.md | 官方 361 campaign 状态页(停在 07-31) | docs/EXPERIMENTS.md 顶部现状块 |

**Why the action exam was retired (2026-08-13):** teacher forcing hands the
model a correct history at every step, so a policy that has stopped reading its
observation still scores well. It ranked the checkpoint that solved 1/9 real
tasks as the best model on its panel (0.800 action-type accuracy, above the
stock model's 0.775), and rendered the fatal copy-previous-response defect as a
benign "phase lag" — a reading that the rollout then falsified. Its two think
metrics were both artifacts (tag placement, then hallucinated extra rounds).
Kept here because the code is a serviceable format smoke-test; it is not a
quality measurement. See outdated/docs/SFT_TRAINING_20260822.md, "Which number decides what".

## plans/ —— 时效性方案(2026-09-09 归档)

方案文档只描述"当时打算怎么做";执行完或被后续版本取代后就不再是现状。
09-01 严格语料方案已归档为设计/执行历史；当前检查工具方案见 `sft/plans/PLAN-20260914-visual-signal-monitoring.md`。

| file | era | superseded by |
|---|---|---|
| plans/V11.md | v11 设计/运行/检查状态页(2026-08-09) | taskgen/docs/PIPELINE.md + docs/EXPERIMENTS.md |
| plans/PLAN-20260815-rollout2vm-richrich-eval.md | rollout 降 2 VM 腾 1 VM 跑 eval(08-15) | 已执行;docs/EXPERIMENTS.md |
| plans/PLAN-20260816-armB-bestof3-armC.md | B 臂 → ep1 曲线 → best-of-3(08-16) | 已执行;sft/docs/RESULTS.md §6 |
| plans/PLAN-20260818-datagenv12-fmt-w1.md | datagen v12 首波:补格式类任务(08-18) | 被 v13/v14 取代;taskgen/docs/PIPELINE.md |
| plans/PLAN-20260820-targeted100.md | 定向补 ~100 条成功轨迹(08-20) | 被 v13 取代;docs/EXPERIMENTS.md |
| plans/PLAN-20260822-datagen-v13.md | v13 语料工程:五条缺口(08-22) | 被 v14 取代;taskgen/docs/RUNBOOK.md |
| plans/PLAN-20260825-datagen-v14.md | v14 datagen 改进白皮书(08-25) | 被 v16 判官制取代;taskgen/docs/PIPELINE.md · docs/GLOSSARY.md |
| plans/PLAN-20260825-v14-impl.md | v14 实施手册 0-5 项(08-25) | 同上 |
| plans/PLAN-20260825-v14-offpolicy-roi.md | v14 off-policy 数据还能提多少(08-25) | 同上;docs/IDEAS.md |
| plans/PLAN-20260828-v14g-gold.md | v14g 配方层 + gold-file 判据扩展(08-28) | 被 v16 判官制取代;docs/GLOSSARY.md |
| plans/PLAN-20260829-aws-rollout.md | v14g 教师 rollout 搬上 AWS(08-29) | 踩点完成、未执行;AWS 侧结果 sft/docs/RESULTS.md §5.33 |
| plans/PLAN-20260830-v15.md | v15 可验证空间扩容与判据根治(08-30) | 被 v16 取代;taskgen/docs/PIPELINE.md |


## Archived during the 2026-09-14 layout cleanup

These files retain the old evidence and procedures; layout edits are not a live-status refresh.

| File | Why archived | Maintained entry |
|---|---|---|
| [outdated/plans/PLAN-20260901-strict-corpus.md](plans/PLAN-20260901-strict-corpus.md) | Completed-era strict-corpus design and subsequent execution log | [README.md](../sft/README.md) |
| [TASKGEN_SNAPSHOT_20260815.md](docs/TASKGEN_SNAPSHOT_20260815.md) | Explicitly superseded generator snapshot note | [README.md](../taskgen/README.md) |
| [TASKGEN_GIT_HISTORY_20260815.md](docs/TASKGEN_GIT_HISTORY_20260815.md) | Dated repository/worktree history | [README.md](../taskgen/README.md) |
| [SFT_TRAINING_20260822.md](docs/SFT_TRAINING_20260822.md) | Mixed early training guide and dated experiment ledger | [TRAINING.md](../sft/docs/TRAINING.md) |
| [SFT_CONTEXT_20260813.md](docs/SFT_CONTEXT_20260813.md) | Campaign-specific context/defaults | [CONTEXT.md](../sft/docs/CONTEXT.md) |
| [SFT_FAILURE_ANATOMY_20260903.md](reports/SFT_FAILURE_ANATOMY_20260903.md) | Historical failure ledger; later investigations qualify its claims | [SFT_FAILURE_PATTERNS_20260904.md](../reports/SFT_FAILURE_PATTERNS_20260904.md) |

<!-- REPO NAV -->
Archived record · [Repository map](../README.md) · [Archive index](README.md)
<!-- /REPO NAV -->
