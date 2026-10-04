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
- ✅ **AUTO PLAY** (ICLR26, 苹果) — 探索后出题:探索模型带记忆铺满环境 →
  按四型指引出题(功能使用/信息检索/功能组合/批量重复),CRUD 参数写死、改删
  只碰真实条目;执行与验收全用 MLLM 判官(无特权信息)→ SFT +10.9%,判官当
  奖励再 RL +5.7%。v16 的两条铁律与判官制与其同构;"类别少而宽+素材源供多样性"
  的结论直接影响了 19 族设计。
- ✅ **AgentSynth** (ICLR26, 2506.14205, Berkeley) — 人设(PersonaHub 抽样)+
  链式子任务:逐步生成-执行-验收,总结代理把链缩写成长任务,难度=折叠子任务数,
  $0.60/轨迹。信息不对称(正向逐步易、整题倒解难)。二期候选:d3 链式拼装
  (IDEAS J4)。

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
the 444-task sample (docs/EXPERIMENTS.md, category analysis). The negative-control gap made precise:
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
我们的 20 图窗口 + 历史思考保留在两个维度上都 rich(历史思考的保留来自 stock 模板本身,不是 keepthink 带来的 —— 见 `sft/docs/RESULTS.md` §5.7)。两家 per-turn 展开的动机
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

## 动作级 reward model(ARM)与轨迹级视频 RM(2026-09-30 读)

两份材料讲的不是同一类 reward model:

| | 打分对象 | 输入 | 对 SFT 数据的作用 |
|---|---|---|---|
| 我们的 strongjudge | 整条轨迹 | 题面+末 8 帧+动作+自述 | 决定整条轨迹收不收 |
| ExeVRM(arXiv 2603.10178) | 整条轨迹 | 题面+1 FPS 关键帧视频 | 成功/失败 + 首错时间段;论文未用于筛数据/RL |
| **ARM**(github piotr-teterwak/action-reward-models) | **同一状态下的 K 个候选动作** | 截图+题面+5 个候选 | **决定这一步的训练目标写哪个动作** |

**ARM(原文 README / actor_distillation/RESULTS.md 核实)**:actor 每状态自采 5 个候选
(RM 训练数据 temp 0.7,蒸馏时 1.0),GPT-5.5 选一个作标签(~3k 状态重复采样→49.5k 组);
训两种 RM:selection ARM(看全部候选选一个)与 BT scalar(逐个打分)。推理时 best-of-5:
OM2W MolmoWeb-4B 25.1→37.1%,OpenWebRL-4B 33.8→51.1%(超过 GPT-5.5 教师 47.1%);
OSWorld Qwen3.5-4B 10.0→21.0% 是 **GPT-5.5 直接当选择器**,训练出的 ARM 没有 OSWorld 数字。

**蒸馏回 SFT(= RM 决定 SFT 数据)**:状态取自 gold 轨迹,目标 = 被选中的候选;
`--only-changed` 只留"选中 ≠ 学生多数票"的状态;预检 off-plurality <10% 不值得做,>25% 值得。
- 在线、训练的 4B ARM、无门槛:**−4.2pp**(31.1→26.8)。学会原地滚动不提交:终止率
  100%→27%,撞步数上限 7%→67%,scroll 占比 24%→61%。作者诊断:5 个都差时"最好的差动作"
  仍被训;局部评判下犹豫类动作看起来比提交类动作更安全。
- 离线、GPT-5.5 PRM 分数 argmax + **最佳分 <0.7 丢弃该状态** + 平局取学生多数票:
  **+8.7pp**(95% CI 2.4–15.0);对"同状态随机候选 SFT"对照 **+7.2pp,p≈0.001,n=190**,
  随机对照本身≈基线 → 收益来自"选择",不是来自"训学生自己的输出"。
- **混淆(我们的判断)**:成败两轮同时改了选择器、在线/离线、门槛、平局规则;作者说门槛
  贡献最大,但没有单独隔离。

**作者 dashboard 补充(weekly-dashboard-inky.vercel.app,2026-09-30 读)**:
- OSWorld 页("selection doubles a CUA",更新 2026-09-02):Qwen3.5-4B,全 369 题,30 步上限,AWS VM;
  每步 temp 0.7 采 5 个,**GPT-5.5 看截图当选择器**(推理时选择,非蒸馏)。配对 n=290:10.0% → 21.0%,
  翻转 36:4,符号检验 p≈1.86e-7。5,785 个选择步里 70% 有 ≥2 种不同候选(平均 2.51 种),59% 选了非第一个;
  20 帧历史 vs 4 帧无帮助(10.9% vs 8.4%,p≈0.29)。分域:multi_apps 4→9%、chrome 9→24%、
  impress 16→34%、calc 9→26%、os 4→26%、thunderbird 7→36%、gimp/writer 不变。
- 9.1 页(OM2W,GPT-4.1 判官复判,240 题交集):n=1 41.2% / 训练的 ARM 60.0% / GPT-5.5 选 54.6% /
  BT 打分器 57.1%;ARM vs GPT-5.5 翻转 36:23,p≈0.12(不显著)。
- **蒸馏成功那版用了多少状态,仓库与 dashboard 都没写**;已知只有:失败的在线版 8k 状态,
  ARM 训练标签 ~3k 状态 × 重复抽样 → 49.5k 组。

**David An(Klone `dan29`)的 OM2W ARM 实验(2026-09-30 只读核查 `/gscratch/krishna/dan29/evals/om2w/*score*.json`)**:
- **Full / Valid 定义**:GPT-4.1 判官版(`armsel_score_20260926.json`,即 Slack 9-24 数字出处):Full = 成功/300
  (中止算失败);Valid = "v2" = 成功/(300 − 中止 − confirmed_excluded)。Zixian 正式口径(o4-mini + OSU
  AgentTrek prompt,Zixian `850d33b`;`armzx_*`、`selectorzx_score_20260927.json`):Full = 成功/300,
  Valid = 成功/(300 − 中止 − 缺失 − 判官失败)。
- Slack "SFT + GPT-6:Full 41% +8.2 / Valid 49.4% +9.4" = GPT-6 选择器单次 123/300、123/249(中止 30、排除 21),
  对 3 次 n=1 基线均值 32.78 / 40.0。
- **正式判官下 GPT-6 ≈ GPT-5.5 当选择器**:SFT ckpt 42.67 vs 43.67(full,Δ −1.0,p=0.79);4B RL ckpt
  58.33 vs 58.33;GPT-6 每题成本约 2 倍($0.67 vs $0.33,SFT)。
- 蒸馏成 4B 选择器:GPT-6 标签 37.56/41.57、GPT-5.5 标签 38.44/42.61、Piotr 公开 ARM 39.22/43.58,均低于
  Zixian 参考 SelectionARM 42.67/50.0(参考基线 30.0/33.71)。
- `arm_gpt6/ckpts/relabel_*` 7 个 checkpoint 全是**选择器**:LoRA,起点 OpenWebRL-4B-SFT,数据
  `owrl_selection_*`(截图+5 候选→选第几个),标签分别来自 GPT-6 / GPT-5.5 / teacher126 / student126 候选。
  **未见用选中动作训练 actor 的产物**;`teacher_takeover/`(09-29/30,t8b 与 student)在数据收集阶段。
- 8,731 个选择样本上 **GPT-6 与 GPT-5.5 选同一候选仅 4,788(55%)**,而两者当选择器的成功率几乎相同 →
  多数状态的候选差别不大,"5 选 1"的标签噪声高。Piotr 公开标签的目标位置偏向第 1 个(2,778 vs 第 5 个 1,253),
  David 打乱后均匀。

**ExeVRM 要点(HTML 版经摘要读取,未逐表核对)**:ExeVR-53k = OSWorld 23k(361 题、30 个
agent、规则判分)+ AgentNet 23k + ScaleCUA 7k;负样本 = 对成功片段改写一个"界面上合理但
不匹配"的指令,并标出第几步开始不匹配 → 首错时间标签;时空 token 裁剪;Qwen3-VL-4B/8B;
8B acc 84.7 / P 82.9 / R 87.7(GPT-5.2 75.0,Gemini-3 Pro 75.1)。**对我们**:训练集用了
OSWorld 361 题,拿它评 OSWorld 轨迹有污染;标签继承 checker 过严的 bug(JUDGING §6)。

<!-- REPO NAV -->
[Repository map](../README.md)
<!-- /REPO NAV -->
