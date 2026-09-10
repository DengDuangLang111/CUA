# outdated/

Historical documents kept for the record, superseded by current docs at the
repo root. Nothing here describes the current pipeline.

| file | era | superseded by |
|---|---|---|
| V3_RUN.md | v3 generation round (2026-08-08) | EXPERIMENTS.md + plans/V11.md |
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

## plans/ —— 时效性方案(2026-09-09 归档)

方案文档只描述"当时打算怎么做";执行完或被后续版本取代后就不再是现状。
唯一还在执行中的方案 `PLAN-20260901-strict-corpus.md` 留在仓库根。

| file | era | superseded by |
|---|---|---|
| plans/V11.md | v11 设计/运行/检查状态页(2026-08-09) | TASKGEN_PIPELINE.md + EXPERIMENTS.md |
| plans/PLAN-20260815-rollout2vm-richrich-eval.md | rollout 降 2 VM 腾 1 VM 跑 eval(08-15) | 已执行;EXPERIMENTS.md |
| plans/PLAN-20260816-armB-bestof3-armC.md | B 臂 → ep1 曲线 → best-of-3(08-16) | 已执行;sft/RESULTS.md §6 |
| plans/PLAN-20260818-datagenv12-fmt-w1.md | datagen v12 首波:补格式类任务(08-18) | 被 v13/v14 取代;TASKGEN_PIPELINE.md |
| plans/PLAN-20260820-targeted100.md | 定向补 ~100 条成功轨迹(08-20) | 被 v13 取代;EXPERIMENTS.md |
| plans/PLAN-20260822-datagen-v13.md | v13 语料工程:五条缺口(08-22) | 被 v14 取代;RUNBOOK.md |
| plans/PLAN-20260825-datagen-v14.md | v14 datagen 改进白皮书(08-25) | 被 v16 判官制取代;TASKGEN_PIPELINE.md · GLOSSARY.md |
| plans/PLAN-20260825-v14-impl.md | v14 实施手册 0-5 项(08-25) | 同上 |
| plans/PLAN-20260825-v14-offpolicy-roi.md | v14 off-policy 数据还能提多少(08-25) | 同上;IDEAS.md |
| plans/PLAN-20260828-v14g-gold.md | v14g 配方层 + gold-file 判据扩展(08-28) | 被 v16 判官制取代;GLOSSARY.md |
| plans/PLAN-20260829-aws-rollout.md | v14g 教师 rollout 搬上 AWS(08-29) | 踩点完成、未执行;AWS 侧结果 sft/RESULTS.md §5.33 |
| plans/PLAN-20260830-v15.md | v15 可验证空间扩容与判据根治(08-30) | 被 v16 取代;TASKGEN_PIPELINE.md |
