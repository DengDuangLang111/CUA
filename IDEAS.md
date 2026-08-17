# IDEAS — 评估过的改进方向(候选实验档案)

> 定位:**候选实验的评估与排队区**。已排进执行的看 `PLAN-*.md`,已出结果的看
> `EXPERIMENTS.md` / `sft/TRAINING.md`。每条记:想法、评估、与现状的接线、
> 依赖与坑。来源不限(外部讨论、复盘、论文),入档前须经评估。

## 2026-08-17 批次(来源:用户与外部 LLM 的讨论截图,当夜评估)

### 病理总图:两种病、两种药

eval-50 的损伤(base 38% > 全部 SFT 臂)分解为两个独立机制:

| 病 | 症状 | 药 |
|---|---|---|
| **遗忘/收窄** | SFT 后**跌破 base**;损伤集中在语料稀薄域 | replay(下述 A) |
| **Exposure bias / covariate shift** | 克隆**涨不上去**:学生一步偏离即掉出教师状态流形,面对训练中不存在的 state(ep1 的 ctrl_scroll→崩盘 = 实测案例) | 学生失败态收割(下述 B) |

关键区分:exposure bias 解释不了"低于 base"(base 也没见过教师数据),
跌破部分归遗忘;两药互补不互替。

### A. Base replay + token 配平因果实验 【优先级 1,B/C 裁决后开】

- 设计(采纳外部建议):纯 SFT vs SFT+25%/50% replay,**总 optimizer
  token 配平**(不配平则"replay 有效"与"训得多"混淆)。
- 分两阶段:
  1. **自 replay**(先做):base Qwen3.5-4B 自己在生成任务池上的通过轨迹,
     census→整条过滤→build,全走现有 pipeline;分布锚定最准、零污染风险;
  2. **broad replay**(后做):外部桌面轨迹数据集;**必须先过
     OSWorld-Verified 污染筛查**(cuagym-contamination-corpus 规矩)。
- 附加成分候选(外部建议):domain-balanced 桌面轨迹、tool-format/
  termination 校准样本——termination 校准与我们 infeasible-5 题的
  surrender-calibration 观察直接对应。

### B. 学生失败态收割 = CUA 版 DAgger/GKD 【优先级 2,重放臂之后】

- 环路:学生 rollout → 首次 divergence/loop/假终止检测 → 学生当时
  screenshot+history 拼 prompt 问教师(诊断/纠正动作/替代路线/该不该
  terminate)→ 纠正样本回流训练。
- **on-policy 辨析**:状态分布 on-policy(学生自己的),监督 off-policy
  (教师标注)= DAgger 经典配方;不是 RL(无 reward 优化)。
- 我们的现成零件:失败检测 = traj.identical_runs(loop)+ DONE+0分
  (假终止)+ cap-hit;教师查询不需要 VM(纯 prompt);样本构建 =
  build.py 机械。
- **质控坑(外部讨论未提)**:教师隔截图开药方,无环境验证,
  plausible-but-wrong 纠正 = 新毒药。解法:两级样本——纠正后**续跑到底、
  checker 判过**为金级(进主训练集),未验证为银级(只做消融)。
- 外部讨论的正确洞察:对 4B 学生,失败态纠正样本 > 教师前几步的
  nominal action(后者 base 多半已会)——与 channel loss 显示的
  易域高 acc 一致;也与我们保护 recovery_samples(207 个)同一哲学。

### C. 跨代 teacher intersection 实验 【论文级,数据部分现成】

- 设计:I = {两代 teacher 都成功的任务};逐项配平(步数/target token/
  schema/渲染/评分器/域分布)后三臂:Arm Old(3.5/3.6 traces→4B)、
  Arm New(3.8 traces→4B)、Arm Mixed(50/50)。分离"新 teacher 行为
  更好"vs"新 reasoning style 更难被旧 student 吸收"。
- 我们的存量:3.6 时代 rollout 在盘上,交集可先 census 不必全新跑。
- **NLL 探针先行**(便宜,纯前向):同一 base 学生算
  NLL(D_old) vs NLL(D_3.8),量化"3.8 输出对 3.5-4B 多陌生";按动作
  类别分解(click/type/hotkey/terminal/recovery/multi-app/infeasible)
  看 mismatch 聚集处——"跨代蒸馏难"从叙事变数字的最短路径。
  与 wandb 讨论中的遗忘探针(driftprobe)共享基建。

### D. 前置验证事项

- [x] **tokenizer 一致性(2026-08-17 验毕:完全相同)**——vocab dict 相等、
  探针编码(think 标签/tool_call/中文/动作词/特殊 token)逐 token 相等,
  md5 差异仅文件格式。**logit 级 OPD/KL 蒸馏技术可行**。
- [ ] 3.6 时代 rollout 与 v11 任务集的重叠面(intersection 可行性 census)。
- [ ] 外部桌面轨迹数据集候选清单 + 污染筛查协议。

### E. Teacher intervention(DAgger 落地形态)【2026-08-17 深夜评估】

外部讨论给出三种干预策略,采纳其推荐 + 我方修正:

| 方案 | 形态 | 判决 |
|---|---|---|
| A 教师接管到底 | 错误点后教师跑完 | 只作"可救性验证/完整参考"独立桶,**不当主训练数据**(后缀重新 off-policy 化) |
| B 教师只纠一步 | 单步纠正即交还 | 默认起点,但 GUI 错误常需连招(关弹窗→切 app→恢复焦点) |
| **C 恢复即交还(主推)** | 教师做最短恢复段(预算 3-5 步)→ 学生续跑 | on-policy 保留最多 + 可测"被救后能否自主完成";教师干预长度本身是指标 |

**采纳的设计件**:交还判据用可观测条件(无阻塞弹窗/app-tab 对/上一动作改变了画面/学生下一步不再重复或幻觉),不信教师自我宣告;触发分三层(确定性检测→规则+LLM→离线回溯),第一层就是我们现成的检测器(enum 违例/连续重复/截图不变/假终止=DONE+0分);学生错误动作存 negative bucket(rejected/chosen/error_type)——**天然是 DPO 三元组**;效率指标用 autonomy-adjusted success(成功率 − λ·教师步占比),防"教师强≠学生学会";迭代轮次 π0→π1→π2 每轮必须用当前学生重采样,旧轮次降权。

**二次评估(2026-08-17,外部 GPT 方案的可行性审查后并入)**:
- **三元组必存**:(s_pre, a_bad, s_bad)——我们的轨迹逐步存截图,离线即可
  全量提取,零成本;由此分两支:**correction**(s_pre→教师应做动作,纯
  prompt,免费)与 **recovery**(s_bad→教师救场腿)。
- **成本不对称(方案书未写明)**:recovery 必须让环境真处于 s_bad——离线
  = 重置+回放学生动作到位(每例 2-4 分钟 VM,动画/时钟类任务保真度
  打折),在线 = round-1 harness。correction 免费,recovery 付费。
- **交还判据的观察力上限**:纯截图观察下"无阻塞弹窗/app-tab 正确"只能
  截图启发式+judge 软判;硬判据 = 动作合法/截图变化/精确重复/假终止四项。
- **三桶训练集**:D_corr / D_rec / D_retain(IWR 式配平,intervention 与
  非 intervention 约各半);λ 加权在**数据构成层**实现(份数+token 配平),
  不改 swift loss。
- **RaC 式 truncate-vs-handoff 对照臂**:登记不排期(rollout 预算×2,
  主臂出信号后再议)。
- **学术定位**(外部分析,方向可信):HG-DAgger 式门控接管 + IWR 式
  intervention 配平 + 短教师腿后交还;**引文核实红线**:HG-DAgger
  (1810.02890)、IWR(2012.06733)可背书;RaC(2509.07953)与
  "Relay-OPD"(2607.26057)未核实,引用前必查。
- 流程优化:correction 查询移出在线循环(bundle 落盘后离线补收),
  在线只做 recovery 腿。
- round-0 试点指标:教师隔屏纠正靠谱率 + 回放保真度(各 ~30 例),
  两个数字决定 round-1 是否立项。

**我方修正/现实约束**:
1. **round-0 可以离线白嫖**:历年 eval 的失败轨迹(ep1/ep3/lean/richstock
   各 ~36-39 条,含完整截图+历史)就是现成的学生失败态库——教师纠正 =
   纯 prompt 查询,**零新 harness、零 VM**,先出第一批金/银级纠正样本;
2. 交互式中途换手(episode 内 student↔teacher 端点切换)需要 harness
   动刀(agent 按触发条件换 base_url + 记录归属)——round-1 再建;
3. 反事实定位(VM snapshot 回滚验证 causal step)在 docker 栈上偏重,
   先用三层触发的离线回溯替代;
4. 起点模型用 base(38%)而非窄 SFT checkpoint(22-28%)——采纳;
5. 训练纠正数据只用生成任务池,**永不碰冻结 eval-50**——采纳(污染红线)。

### F. 严格 OPD(Thinking Machines 式 reverse-KL)【远期,闸门陆续开】

学生自己跑完整轨迹(环境不被教师触碰),教师只对学生每个 token 打
logprob,按 reverse KL 更新;retention 可加第二通道(冻结 base 的 KL,
λ_new·KL(π_S‖π_3.8) + λ_retain·KL(π_S‖π_base))——比 replay 更直接的
防遗忘机制(在学生当前分布上持续回拉,而非模仿固定样本)。
**闸门清单**:tokenizer ✓(已验相同);教师多模态 logprob 前向(vLLM
prompt_logprobs 回放学生上下文,技术可行未打通);RL 式训练环
(ms-swift 无现成 OPD trainer,自建工作量最大);每轮学生重采样的 VM
预算(我们的真瓶颈)。cookbook 已有 multi-turn tool-use 版本
(on_policy_distillation_harbor_multi_turn.py)可作参考实现。
**排序**:E 的 round-0(离线)→ E 的 round-1(交互式)→ F。

### G. 薄 adapter harness / 防 harness 过拟合【2026-08-17 评估:架构对,时序缓】

外部方案:canonical policy 接口 + 各 benchmark 薄包装(内部仍调官方
reset/step/executor/evaluator)+ 官方口径复验;三层分离(policy /
env adapter / evaluator adapter);最小共享动作核 + capability manifest;
parity test 把关。原则:**Normalize the interface, not the semantics**。

**定位判断**:harness 过拟合**不是我们当前的病**——base 同 harness 38% >
SFT 22-28%(学生没学好自家 harness,谈不上过拟合);richstock 消融实测
serving 层 surface 扰动 = ±1 题。全面 adapter 化 phase-gate 在 B 裁决 +
intervention round-0 之后;其价值兑现场景 = intervention 跨环境复用 +
论文 generalization 断言。

**立刻白捡的三样(与 adapter 无关,独立有价值)**:
- [ ] **Official parity test**:固定动作脚本在魔改 harness vs 纯净
  upstream worktree 双跑,逐步比对截图/评分/终止——把"披露魔改"升级为
  "等价性证据",一个下午成本;
- [ ] 轨迹 provenance 字段(benchmark_commit/adapter_commit/
  harness_profile)——MODEL_BOUNDARY.json 实践的逐轨迹化;
- [x] Model+Harness 报告口径(已在执行:魔改披露/keepthink 注记/
  serving 消融)。

**缓行项**:统一动作空间、多 renderer、多 benchmark 接入。真到 Phase 2,
第一个 adapter 目标 = Mac 上现成的 **OSWorld-V2**(同源异 benchmark,
抽象试金石),不外求。先例纪律:build.py import agent 构建器 = "接口归一
语义不动"的既有成功样板。**引文红线**:Harness-Bench(2605.27922)、
AgentCompass(2607.13705)、Qwen-CUA(2608.02352)均未核实,引用前必查。

### H. Prompt 三层解剖与长尾根因序(2026-08-17)

**三层分解**(我们与 OpenWebRL 同构):benchmark 只给 task instruction;
agent policy prompt(角色/推理要求/动作协议)与 runtime 序列化(工具
schema/历史/折叠/终止/模板)都是各家 harness 自己的设计。报告口径必须写
"Qwen3.5-4B + OSWorld Verified + upstream Qwen agent harness + 我方设置"。

**长尾根因序(嫌疑从重到轻,自家证据背书)**:
1. **Qwen3.8 模板默认 `reasoning_effort='xhigh'`**(RUNBOOK:343-355 实证:
   三档中唯一无前导语的是 medium;我们的栈从未设置 → 全战役 xhigh)。
   内部对照:同一 harness prompt 下 3.6 vs 3.8 的 think p90 = 755 vs
   6,495 字符(9×)——协议不变、教师换代,尾巴爆炸 → 根因在教师生成策略
   不在 OSWorld prompt。**一行修复候选:未来 rollout 传
   `chat_template_kwargs: {reasoning_effort: "medium"}`,生成端直接产
   匀质思考,比事后清尾便宜**(当前 rollout 停摆中,记档待启用)。
2. 600s + 81920 budget 放行政策(有意取舍,已档)。
3. 无 shortest-success 策展(对照 OpenWebRL 每任务 4 选 1 最短)。
4. current-target 清尾(census/build 的 --think-cap 设计,见下)。
5. system policy 简洁化——最后才动。

**清尾 pipeline 设计(待用户点火)**:census 加 think 长度分层报告标准段;
build 加 `--think-cap 2048`(字符近似,quarantine 桶不销毁,>4096 的 28 个
强制人工审计);单边削尾不设下限(短 think 层 action 占比 29.8% 是最健康
地层);历史 think 不动(独立的 train-infer 一致性问题,先做 preserve_
thinking 渲染的字节级验证再裁决)。派生集 B-tailclean,raw 永不改。

**concise-policy 变体(下一批教师 rollout 用,不重写不换)**:附加软约束
"从当前截图与进度简洁推理;不复述任务;可行动作一旦可辨立即执行;仅
blocker/恢复/多约束校验允许加长"。不写死 token 上限(硬限会逼教师删证据
换速错)。**先行 2×2 因果试验**:{现行 policy, concise} × {xhigh, medium},
固定状态集比 p50/p90/p99、parse 率、动作接地、time-to-tool-call,选
"action 质量不降而 p99 大降"的格子,再 10-20 任务闭环确认。

**铁律**:teacher rollout prompt = SFT 渲染 = student eval prompt(policy/
工具/语法/坐标/历史可见性/折叠/终止/模板/思考序列化九层全等)。最危险的
操作 = 用一种风格生成训练、换另一种风格评测。跨 bench 的 canonical
contract 归 G 节 adapter 管,不让学生直接学各家方言。

### I. Tailclean 三阶段计划(2026-08-17,GPT 意见验收后定稿)

**Phase 0 验收(已满足,零返工)**:我们的 --think-cap 实现即 GPT 推荐的
step-level target masking——摘目标不摘环境步、历史保留被摘步原文、无重编号
无拼接、轨迹过滤先行、quarantine 不销毁(五条不变量逐条对照通过;哲学同
幻觉步过滤一脉)。整条删除的 B 型错误从未存在。

**Phase 1|tailclean-2048 消融臂**(用户批准执行):q38e3B-tc2048-* 语料,
gb64o 孪生配置(16卡 全局64、wd 0.0/β₂ 0.999、3ep、三存制),与 raw-gb64o
单变量对照 → 回答"摘极端 reasoning 监督改不改善"。token 差 −16.2% 如实
披露;loss 分母未验前不把 token 差等同梯度权重差。

**Phase 2|77 步语义 census**(待批):固化 `ostg.sft.tailaudit`——对
quarantine 逐条出审计表(动作/位置/后续步走势/judge 四分类初判:keep 原样
/rewrite/仅 mask/整条存疑),LLM 初判 + 人工终审(28 个 >4k 必过人眼)。

**Phase 3|rewrite 流程**(待批,production v2):对 rewrite 标签步,教师在
逐字节复刻的原上下文中产 ≤300 token 接地短推理;**tool_call 逐字节不变**
(校验 assert)+ 禁未来信息;产 `B-rewrite` = tailclean + 回填——赎回 77 个
困难态 action 决策("token 占比 2.9% ≠ action 无价值")。
优先级公式:rewrite > target-mask > 整条删;改 action 必须 replay,禁止
静态改 JSON(反事实不一致)。cap-1024 仅作二阶消融。
**pipeline 优化项(已实现,2026-08-17,CUA+ostg@0ee4f290)**:build
`--image-cache RAW_DIR` 硬链接复用 + pipeline `IMAGE_CACHE` 直通;命中记
`images_cache_hits`。派生构建图片阶段 15-45min → 秒级;自包含与溯源不变
(硬链接文件独立存在)。小文件跨机移动继续走 tar 流(ship_dataset 既有)。

**Phase 1.5|训练仪表(探针式,twin 训练窗口内实现)**:在线全套需动 swift
训练器内部(魔改,不上对照臂);等价交付 = **离线 per-checkpoint 探针**
`ostg.sft.ckptprobe`(1-GPU 小作业):对每个 checkpoint 算 ①‖θ‖、
②‖θₖ−θₖ₋₁‖(位移理论直接度量)、③update/weight ratio、④固定探针集上的
think-loss / action-loss / action-token-acc(区域掩码分通道 CE),回填
wandb。三存制下曲线密度 = 9 点/3ep + init。派生指标 clip_scale /
post_clip_norm = min(1, 1/grad_norm) 由已记 grad_norm 后处理补写。

### 裁决后的优先级分叉(预登记)

若今日 B 四臂 eval 确认损伤依旧:静态语料扩张(含 best-of-3/C 臂)的
边际价值存疑,**A(replay)与 E(intervention)有资格插队到 C 臂之前**
——届时与用户重排,不默认执行。

### 排队关系(2026-08-17 时点)

主线不变:B 四臂 eval(量+优化域裁决)→ rerun3/best-of-3 → C 臂(质裁决)。
本档案的 A 在 C 臂裁决后第一顺位;B 在 A 之后;C/NLL 探针可与任何阶段
并行(只读+纯前向,不占 VM)。

### J. Judge 体系 v2 与 checker 仲裁(2026-08-17 晚,GPT 大方案裁剪后落地)

外部 LLM 提出全量 judge 研究计划(650-800 研究集/150 人工 gold/四消融/
12 指标);裁剪原则 = 判官是仪器不是课题,**人工环节全删(用户令:全 prompt)**。
吸收落地(代码 557e170b):①**v2req rubric**:先拆 requirement(六档
status、critical 加权、指认证据帧/步)再打分,脚本反算 derived 分,
free-vs-derived gap 当自一致探针,幻觉引用计数(evidence_violations);
②v2 rubric:标号帧 + 截图>自述规则 + XML 围栏,Claude 推荐写法;
③Opus 判官 temperature 钉 0(llm.py cfg 直通,thinking 时禁传);
④本地判官 vLLM guided_json 替代 regex 抠 JSON;⑤judge_status 字段,
error 永不计 0 分;⑥**arb.py 仲裁**:分歧集(fp/fn/duel 规则)亮 checker
evaluator 配置,Opus5+thinking 裁 checker_right_judge_fooled /
checker_bug_lenient / checker_bug_strict / ambiguous → checker 缺陷清单。
拒收/降级:人工 gold(→checker 真值+双判官交叉+temp0 重复一致性)、
四消融留 think 消融一个(**用户令:暂不做**)、Brier 全家桶(AUC 够用)、
650-800 拼集(v11 全量 ~550 成败混合已够)。
仲裁首战:chrome/04624efc 坐实 checker_bug_strict(硬编码 /370 违反
自家字母平局规则)= 被误标失败的成功轨迹;chrome/13594739 = 判官排序
算错,checker 无辜。**双向 bug 率待全裁决后入账**;若 strict-bug 率非零,
rollout pass 率系统性低估 → 生成侧 checker 质检(控制门)优先级上调。
待办:terminal 语义 parser(infeasible/cap-hit 区分,对 v11 无用、
eval-50 分析必要)排队;关键帧 diff 采样等 v2 错例证据再定(不为想象
中的病动手术);1k-2k 带补审 30-50 步加固 n=11 小样本。

**§J 战果更新(08-17 晨)**:仲裁 23/23 → 10 冤案(3/3 抽查坐实)/13 判官
失手/0 过松;真实 pass 率 ≈80%。**B-rescue 语料 = 新候选训练臂**(赎回
冤案轨迹 + 剔除假 pass,500 池仲裁后成形,数据白捡不费 VM)。问卷拆账:
措辞无效、medium 有害 → 弱判官上限在模型不在 prompt;v2req 因分层+可审计
证据留任生产问卷,v2 退役。checker 生成端静态检查清单(禁硬编码未给定
细节/round 语义/枚举核对/勿在应用运行时读配置)反哺 taskgen 控制门。
