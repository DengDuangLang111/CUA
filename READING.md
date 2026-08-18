# CUA reading list & innovation candidates (2026-08-15)

Curated for the innovation-point search. ✅ = verified this session (paper/code
actually read); 🔎 = from memory, verify before citing.

## A. Task generation (our home turf)
- ✅ **Qwen-CUA** (2608.02352) — 40K verifiable tasks, iterative teacher-regen;
  generation pipeline CLOSED. Our evaluator-compilation is the gap they left.
- 🔎 **OS-Genesis** — reverse synthesis (explore → derive tasks); the dual of
  our forward-generate + layered-verify.
- ✅ **ANCHOR** (2602.07153) — branch-point task generation from human trajs.
- 🔎 **AgentTrek / Synatra / NNetNav** — tutorials / text / exploration as
  task sources.

## B. Training recipes & consistency (today's vein)
- ✅ **OpenWebRL** (2606.02031) — the −14.6…−23.7 history-reasoning ablation is
  buried here; they patch reasoning back with a regex and never study it.
- 🔎 **How to Train Your LLM Web Agent: A Statistical Diagnosis** (2507.04103)
  — experimental power for agent evals; we lived the 9-task-panel lesson.
- ✅ **OpenCUA** (2508.09123) — AgentNet 22.5K human tasks; their CoT is
  model-backfilled, ours is teacher-native.

## C. Data quality & scale
- ✅ **MolmoWeb** (2604.08516) — 2.2M steps + 10.5M perception, pure SFT;
  "human data limited gains".
- ✅ **ProCUA-SFT** (2606.17321) — 93K synthetic trajs → 3.1M samples; the
  scaled-up version of our shape.
- ✅ **CUA-Suite / GroundCUA** (2603.24440) — 3.6M desktop element annotations.

## D. RL follow-on
- 🔎 **WebRL**, **DigiRL** — online RL recipes; Qwen-CUA's 1–7/8-success task
  retention rule pairs naturally with our difficulty-graded generation.

## E. Benchmarks
- ✅ **OSWorld** (2404.07972) §4 + appendix; AndroidWorld/WebArena as design
  references.

## Innovation candidates (ranked by current evidence)
1. **What should a small student see** — systematic context-config study for
   CUA distillation (history reasoning rich/lean × image budget). The
   rich/lean arms + keepthink template + frozen eval-50 already form the
   skeleton; nobody has published this axis.
2. **Open verifiable-task generation with compiled evaluators + difficulty
   curriculum** — our core asset; Qwen-CUA proved the fuel matters and kept it
   closed; OS-Genesis judges with LLMs. Teacher-pass-rate as difficulty scale.
3. **Step-level conditional-correctness metrics for demonstration quality**
   (state revisitation 0.02-pass vs 0.56-fail, screen-change rate, tail runs)
   — judge-free trajectory quality, cross-model validation data in hand.

1+2 compose: the pipeline produces the corpus; the context study consumes it;
together they are "how to distill desktop competence into a small model".

## Positioning: our generation vs the two paradigms (2026-08-15)

| axis | evaluator-first (Qwen-CUA, AndroidWorld) | task-first (OS-Genesis) | ours (co-gen + admission + validation) |
|---|---|---|---|
| verifiability | by construction | derived, often degrades to LLM judge | constrained AND empirically tested (positive control must score 1.0) |
| naturalness | low (checkability warps tasks) | high | mid-high (user-voice instruction, program-decidable gate) |
| grader | handwritten / closed | LLM judge (~90% at best) | compiled deterministic probe |
| idle-agent zero | usually | often missing | rule-enforced (probe FAILs on setup state) |
| path independence | yes | unguaranteed | rule-enforced (machine state only) |
| difficulty scale | no | no | teacher pass-rate gradient, RL-curriculum-ready |
| openness | closed / small | open + judge-bound | ours, openable |

Update 2026-08-15 (corrected same day — the user caught a confound):
difficulty and app_count are perfectly confounded by design (1–2=1app,
3–4=2app, 5=3app). Validated: the app-count ladder's monotone-cliff effect and
the direction of within-tier grading; within-tier independent validity awaits
the 444-task sample (EXPERIMENTS.md, category analysis). The negative-control gap made precise:
positive control (gold→PASS) and trivial negative (initial-state→FAIL) are
systematic; **near-miss negatives (mutated gold end-states that must all
FAIL) are not** — they test probe specificity, and the two known
wrong-answer-scored-1 leaks are exactly what they would catch. Design: k
generic mutators (drop row, reorder, right-content-wrong-name, partial) + an
LLM-crafted trap per task, specificity column in the control report.

Honest weaknesses to preempt: (1) **same-head co-generation has correlated
blind spots** — a misunderstanding of app behaviour infects task and probe
coherently; positive control catches evaluator-broken cases (did: 6 right-
answer-scored-0 + 2 wrong-answer-scored-1) but **negative control is not yet
systematic** — the pipeline's most paper-critical gap. (2) Free-form probes
mean every grader is fresh code; the control layer is load-bearing.

One-line positioning: co-generate the triple, admit only the program-decidable,
then prove the grader itself correct by experiment — scalable verified
programmatic grading, which neither existing lane offers, with teacher
pass-rate as a free difficulty scale.

## How to compare our data against others (2026-08-15)

Datasets are not comparable as artifacts (environments, grading semantics,
granularity, scale all differ). Three comparisons that ARE sound:

1. **Functional (gold standard): fixed student + budget + recipe + benchmark,
   swap only the data source.** Qwen3.5-4B, e3 recipe, ~1.2k-sample budget,
   verified-eval-50; rows = ours / AgentNet-Ubuntu / ProCUA subset, each
   through the dialect converter and the same pipeline filters. Measures
   value-per-sample. Precedented (MolmoWeb human-vs-synthetic, OpenWebRL
   0.4K-vs-1.9K). Declared confound: conversion quality — mitigate by passing
   our own data through the same converter. This is arm C generalised.
2. **Intrinsic: transferable rulers applied to everyone.** Our judge-free
   trajectory metrics (repeat, revisitation, tail runs, screen-change) run
   unchanged on their trajectories; plus instruction-embedding dispersion and
   app coverage. Fair because the ruler belongs to no dataset.
3. **Categorical: axes with no competitor.** Grader form (compiled probe vs
   judge vs human), grader-validated (positive/negative control) — unique,
   teacher-pass-rate difficulty scale — unique, contamination-by-construction
   status. The narrative axis is "the corpus knows its own reliability", not
   volume.

Paper shape: main = the transplant table (3 rows suffice); support = the
metric table (doubles as innovation #3); positioning = the categorical table.
None of the three requires datasets to be commensurable — only the rulers.

## Why OpenWebRL's 0.4K worked — CORRECTED same day (user caught it)

First version of this section called the 0.4K "ignition, not engine". Table 2
refutes that: base 39.3% avg → **SFT-only 52.0%** → RL 68.4% ("SFT improves
the average success rate from 39.3% to 52.0%, while MM-GRPO further increases
it to 68.4%"). Pure SFT contributed +12.7 points — 44% of the total climb.
SFT walks the first half of the mountain, RL the second.

What the +13 stood on, versus our old arms: a base already at 32% on the
target benchmark (tuning, not teaching), 412 tasks / 70 sites of diversity
(vs our 39-69), in-distribution eval (web-trained, web-tested; ours crosses
generated→Verified), and 7.5-step tasks. Notable honest wrinkle: their SFT
render is lean-history while their eval restores rich — they gained 13 points
DESPITE a train-lean/eval-rich mismatch, so consistency is not a universal
life-or-death line; on 7.5-step tasks history is small. Its importance should
scale with horizon — our domain, not theirs.

Calibration for A/B, revised: pure SFT has precedent for double-digit gains;
the OpenWebRL-analog success bar is base-4B-on-eval-50 + ~10 points. The 1.9K
lesson's precise scope is that heavier SFT hurt POST-RL performance — it does
not forbid heavier SFT helping SFT-only, so arm B stands. Unchanged: the
scarce asset remains the verifiable RL task pool, which our generator
manufactures with a difficulty scale.

Released SFT config(2026-08-16 核实,repo 脚本 + 论文附录 A.5 原文互证):
**8 张数据并行卡,全局 batch 128**(paper:per-device 2 × accum 8;repo 默认
per-device 1 × accum 16 —— 每卡有效 16 一致)、peak lr 1e-5 cosine、
**warmup 0.1**、3 epochs、cutoff_len **36,864**、ZeRO-2、
**image_max_pixels 262,144(≈512²)** —— 图片预算是我们 1920×1088(≈2.09M
像素)的 1/8:web 任务耐得住狠降采样,OS 桌面点击耐不住。算术冲击:3,085
样本 ÷ 128 ≈ **每 epoch 24 个优化步,3ep 总共 ~72 步**拿到 +12.7 —— 对照我们
B 的 708 步/ep、2,124 总步(全局 batch 8)。8B 变体同配方,仅数据 +500 条
InSTA-v3(共 912 轨迹)。他们 eval 解码:temp 0.6 / top-p 0.95 / **top-k 20** /
max response 4096 / rep-pen 1.0(top-k 20 与我们同,max response 比我们的
81920 狠 20 倍 —— 他们根本不给长思考留空间)。

Paper↔repo audit (2026-08-16 深夜,论文 PDF 逐节 vs 本地 clone 逐行):
**一致**——K=1 截图窗论文页 5 明文申报("retaining only the current
screenshot (K = 1)",训练 eval 双侧同款);per-turn 损失掩码(页 6);
3ep/lr 1e-5/cosine/warmup 10%;历史 reasoning 保留(−14.6…−23.7 消融
的默认侧);412 轨迹/70 站,8B=+500 InSTA-v3=912;每 worker 有效 batch 16。
**矛盾**——eval 解码:论文 A.6 申报随机采样 temp 0.6/top-p .95/top-k 20/
max 4096(还引文献论证随机优于确定),但 released 评测脚本
`run_evaluation_local.sh:57` 默认 **TEMPERATURE=0.0(贪心)**;引用他们
分数时注意口径。batch 拆法字面不同(paper: 2×8;repo: 1×16;有效等价)。
**论文未申报、仓库才有**——cutoff_len 36,864;image_max_pixels 262,144
(512²);**vision tower+projector 冻结**("freeze"全篇未出现);
apply_chat_template 逐字节一致机制。开发残留:4B RL 脚本 save-dir 命名
含 "fromSFT912",与正文"4B 默认 412"叙事有出入(非声明,存疑不定罪)。

Primary-source pass (2026-08-16 深夜,本地 clone 逐文件读完,不再经摘要器):
launcher `run_sft_with_llamafactory.sh:76` **PER_TURN 默认 1**,注释原文
"reproducing the released recipe" —— 发布模型 = per-turn 训练实锤;
`prepare_openai_for_llamafactory.py:167` keep_flags 只留最后一张图(当前
截图)。**冻结方案**(launcher 95-97):vision tower + projector 冻结,只训
语言模型 —— 与我们 swift 默认(freeze_vit/aligner true, freeze_llm false,
已从 q38e3B args.json 核实)**完全一致**,此轴无差异。他们 Stage-2 用模型
官方 apply_chat_template 渲染以与推理逐字节一致 —— 与我们 build.py import
agent 自身构建器同一哲学。SFT 语料已公开:HF dataset
`OpenWebRL/OpenWebRL-SFT-Trajectories`(移植对照实验的数据来源,现成可下)。
save_strategy 也是 epoch。

Context handling (2026-08-16 核实,repo sft/README + generate_browser.py):
训练默认 **PER_TURN=1 = 每轮一个样本**(与我们同粒度),**历史截图全剥、每样本
只带当前 1 张图**,mask_history=true(loss 只在当轮)——"整集截图全保留"是
备选 PER_TURN=0 模式(mask_history=false,loss 全轮)。**Eval/rollout 默认
`context_num_screenshots=1`:评测时也只看当前 1 张截图**;文本史默认
`turn_history_reasoning_mode="full"`(**历史 thinking 保留**,另有
hide_thinking/action_only 档,`browser_history_reasoning_max_turns` 限制
更老回合)。即:他们的"lean"是图片维度的(1 张图),文本+思考维度反而 rich;
我们的 20 图窗口 + 历史思考保留在两个维度上都 rich(历史思考的保留来自 stock 模板本身,不是 keepthink 带来的 —— 见 `sft/RESULTS.md` §5.7)。两家 per-turn 展开的动机
相同:历史渲染都不是 append-only(他们剥旧图,我们折叠旧图),打包不等价。

Teacher provenance note (2026-08-15): OpenWebRL's demonstrations came from
Qwen3-VL-235B, 4 independent rollouts per task, GPT-4.1-judged, then curated
to 412. Same-family same-generation distillation gave them template
consistency by construction — the entire cross-template problem we hit is
specific to cross-generation distillation and also our research material.
Actionable borrow: best-of-4 harvesting on our failed tasks (especially the
11 failed diff-5s, whose passes are the corpus's most precious
demonstrations) — 3–4 rerolls per failed task, shortest-success curation,
zero pipeline change, run when VMs free up.
