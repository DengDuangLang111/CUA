# IDEAS — 评估过的改进方向(候选实验档案)

> 定位:**候选实验的评估与排队区**。已排进执行的看 `PLAN-*.md`,已出结果的看
> `EXPERIMENTS.md` / `sft/TRAINING.md`。每条记:想法、评估、与现状的接线、
> 依赖与坑。来源不限(外部讨论、复盘、论文),入档前须经评估。

## 2026-09-01 批次(严格语料线出厂后)

### K1. 「只过滤 r5、不加 v16」对照臂,拆开 mixaw9b 与 a2 的差异 【优先级 2,语料现成】
- 动机:mixaw9b 相对 a2(r5 原样 6473 样本)同时动了两个变量 —— 加了 v16 strict
  半区,**且 r5 半区自身被 WebSTAR 砍掉 44%**(6473 → 3598)。两半留存率几乎相同
  (55.6% / 55.2%),但 eval 差异无法归因到"新数据"还是"步级过滤"。
- 做法:从 `mixa-webstar-v16strict/step_decisions.final.jsonl` 按 `source_build ∈
  {v11100, v11500}` 筛出 keep 行,`filter_copy` 只带这两个 source(图片复用
  `q38-Bhqs2t-r5nocapimg10-*`,零传输),同配方(9B / 3e-6 / 3ep / gb64)训一臂。
  3598 样本 / gb64 = 57 步/epoch(奇数,同 K 规矩取 save_steps=57)。
- 读法:a2 → 该臂 = 步级过滤的净效应;该臂 → mixaw9b = v16 strict 的净效应。
- 坑:与 mixaw9b 一样,`gen_meta` 要 pop;末步 362 条全 keep(overrides 里 18 条)。

## 2026-08-31 批次(v16 判官制开工期)

### G1. a1「明确档」的表达方式单一化 【优先级 3,下轮生成时改提示词】
- 实测(08-30):含 `/home/user` 绝对路径的任务 384/1627 = 23.6%,**其中 93.4%
  集中在 a1**(a2/a3/a4 各 0.0%,门闸生效)。官方 OSWorld-Verified 只有 7.3%
  (27/369,最高的 multi_apps 也只 15.8%),我们是官方的 3.2 倍。
- 问题不在比例,在**表达方式只有一种模板**:`/home/user/<行业目录>/<文件名>`,
  63% 还用引号包着,`~/` 零条、Desktop 零条。官方的明确指令是多样的
  ("the currently open presentation template"、`~/Documents/...xlsx`、
  "pic1.png to pic6.png saved on the Desktop")。风险是模型把"指令明确"与
  "给了绝对路径"绑定,遇到明确但不给路径的官方题落到模糊策略上。
- 做法:提示词里给 a1 一个表达方式轮盘(绝对路径 / `~/` / Desktop+文件名 /
  当前打开的文档 / 只给文件名不给目录),按抽签分配,不改门闸。
- 不返工:已生成的 1386 条保留,a1 只占 25%,其余 75% 从不给路径,覆盖够。

### J2. rollout 收尾收割最终磁盘状态,给判官补一只眼 【优先级 1,须用户批 harness 魔改】
- 动机:仲裁实锤 16 条判官被骗几乎全是"看不到磁盘"(保存未发生/文件名与格式
  不符/文本文档冒充演示稿);pass 侧 4 条疑似错杀同根(要求保存证据反误杀)。
- 做法:轨迹跑完、评测前执行通用收割(开机后 mtime 变更的 /home/user 文件:
  文本直存、办公文件转录成文字、目录树清单)→ 结果目录 final_state/;强判官
  证据袋加一节"最终磁盘转录"。需 harness 魔改(入 OPS §1 账本)+ AWS runner
  同步补丁,rollout 开跑前定最好。
### J3. 判官提示词加固(对着 16 条被骗模式写) 【优先级 2】
- 模式清单:轻信 agent 自报的终端 dump/文件名/现编算术;漏读环境里的 policy
  文件;把打开的缓冲区当成已存盘。加固语向:"agent 的输出只证明命令执行过,
  不证明内容正确;文件名不证明格式"。加固后重考 66 条与仲裁对表。
### J4. AgentSynth 式链式 d3 【二期】
- 逐子任务生成-执行-验收、总结成长任务,难度可控、组合爆炸;代价是生成时要
  真执行(贵)。AWS 管道稳定后做对照臂。

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

### K. 终止信号修复(2026-08-17,已从设想进入执行)

**发现**:DONE 有三条来路——`terminate` 工具调用、`call_user`(也判 DONE)、
**"没有任何工具调用"的 harness 兜底**。实测(仓库 parser 重放,非正则):
生成语料 72% 散文兜底 / 13% call_user / 15% 显式 terminate;**4B 学生 SFT 前
eval-50 上 100% 显式终止,SFT 后 0%**,撞上限 28%→34%。

**归因**:同一批 v11-100 任务上,Qwen3.6 用 terminate 96%,Qwen3.8 只有 13%
—— **是教师模型版本(和采样温度 0.6 vs 1.0,两者混杂),不是任务集**。
base-vs-SFT 那一对无混杂,坐实语料的责任。

**已执行**:`terminalfix` 模块(教师写理由 + 确定性 terminate + auto 尾巴
策略)、build `--terminal-rewrite`、verify `--require-terminate`。
第一个臂 = **Bhqs-2-terminal**(rev2 筛选 + 终止规范化,两个变量同时变;
用户决定跳过 plain 臂以省 eval 槽位,分解留待后补)。

**待验证**:温度重放实验(末步上下文在 temp 1.0 与 0.6 各采一次)。若 0.6
下 terminate 率回到 80%+,则未来 rollout 改温度即可,不必长期依赖事后重写;
若不回,则 rollout prompt 需硬约束"末步必须 terminate"。

**下一步指标**(eval 侧要新增,尚未实现):显式 terminate 率、
**terminate precision(发了 terminate 后 checker 通过率)**、terminate recall、
call_user 率、散文率、撞上限率、成功任务平均步数。**precision 必须与 rate
同看**——只追 terminate 率会训出早停,那比现状更糟。

## 2026-08-24 批次(来源:用户追问 SFT 各域提升差异,查到 datagen 结构性缺口)

### L. taskgen 缺一个"无产物系统设置"任务类,os 域被 files/terminal 冒名 【优先级 1,下一次开 pipeline 分支就该带上】

**发现链路**(9B eval100 各域提升分解 → app 级拆分 multi_apps → 查 pipeline 源码):

1. eval 的 `multi_apps` 拆到具体 app 后,**`os` 是最大的搭档 app(27.5% 命中)**,
   训练语料里跨应用任务(`difficulty≥3`,204/362 = 56.4%)的 `related_apps`
   **一次都没出现过 `"os"`**(0/446 次命中)。
2. 查 `ostg-v11.1/ostg/taskgen/gen.py:39-49`,`APPS` 字典是喂给生成 LLM 的
   **闭合可选目录**(schema 里 `"apps": {"items": {"enum": list(APPS)}}`):

   ```python
   APPS = {
       "libreoffice_calc": "libreoffice_calc", "libreoffice_writer": "libreoffice_writer",
       "libreoffice_impress": "libreoffice_impress", "chrome": "chrome", "gimp": "gimp",
       "vlc": "vlc", "thunderbird": "thunderbird", "vscode": "vs_code",
       "files": "os", "terminal": "os",
   }
   ```

   **`"os"` 不是这 10 个 key 之一**——它只作为 `files`/`terminal` 两个 key 的
   **值**(它们跑在裸桌面快照里)出现。LLM 在语法上**不可能**生成一个
   `related_apps` 含字面量 `"os"` 的任务,因为这个词根本不在枚举里。
3. **更深一层坑**:`gen.py:324` `domain = APPS.get(apps[0], "os")`——主 app 是
   `files`/`terminal` 时,任务被归到 `os` 这个 channel。**这就是训练语料里
   43 道"os 域"任务的真实身份**——抽查 15 条,清一色是"文件按年份分类"
   "从文件夹整理 CSV""批量重命名",**没有一条是"开蓝牙""调字体""设默认
   Python 版本"这种系统设置任务**。对照 eval 的 8 道 `os` 题(开蓝牙、调
   字体、切用户、自动锁屏、设默认 Python、显示电量……),**只有 1/8 是文件
   管理风味,其余 7 题训练语料里没有对应物**。
   ⚠ **两边共用 `os` 这个 channel 名字,内容却几乎不相交**——比 `multi_apps`
   缺失更隐蔽,因为它不会在任何按 channel 名字做的统计表里露出破绽
   (§5.20 之前那张训练/eval 占比对照表就被这个假匹配骗过了)。
4. 再往上查 `taxonomy.py:83-99` 的 `ARTIFACT_HOSTS`,确认这是**范式级**问题:
   整条 pipeline 建立在"每个任务操作一个**产物**(文档/表格/图片/浏览器标签),
   产物挂在某个 app 上"这个假设上。连 `desktop_session` 这个产物类的宿主列表
   `["vlc","thunderbird","vscode","libreoffice_impress","gimp","files"]`
   也没有系统设置的位置——**因为"开蓝牙""调字体"这类任务没有持久化产物**,
   操作完就是一次状态切换,这套"产物→宿主 app"的生成范式设计上就没地方
   安放它们。

**归类**:不是配额没调对、不是抽样运气差,是**当前 schema 结构性地无法生成
"无产物系统设置切换"这一整个任务类**,无论作为主任务还是作为跨应用副 app。
这条和 §5.20(RESULTS.md,`multi_apps` 组合风味错配,交集覆盖率 17.6%)是
同一个根因家族的两层:§5.20 量的是"跨应用组合对不上",这条量的是
"某个任务类型从 schema 层面就生成不出来"。

**可执行的改进方向**(未评估优先级细节,留给下次开 pipeline 分支时定):

1. **`APPS` 字典加一个 `"settings"` / `"os_settings"` 类**,不映射到任何
   现有 app,而是映射到裸 `os` 快照,允许 LLM 显式选它作为主 app 或副 app。
2. **给 `taxonomy.py` 加一个不挂产物的任务生成路径**——现有 `grade` 体系
   (browser/table/rules)可能已经够用(`rules` 分支就是纯 probe,不依赖
   `open_path` flush),缺的只是 §1 里的 app 目录准入,不一定要动 evaluator
   逻辑。
3. **种子任务来源**:eval-50/100 面板里那 8 道真实 `os` 题就是现成的种子——
   蓝牙、字体缩放、锁屏、Python 版本切换、终端持久化设置、电量显示,
   都是"读一个系统偏好项 → probe 检查该项的值"这个模式,评估器复杂度低于
   文档类任务。
4. **验证方式**:加完新类后,重新跑一遍本节 §1 的 app-touch 统计
   (`tools/` 下可以固化成一个复用脚本,见"待办"),`os` 命中次数从 0
   变为非零即为验证通过;再跑一次 eval-50/100 的 `os` 域配对分数确认
   是否真的迁移过去了。

**待办**:把"训练语料 app-touch 统计"(见对话记录里的 `lookup_ma.py` 方法:
image path slug → 任务池 json → `ostg.difficulty`/`related_apps`)固化成
`tools/corpus_app_touch.py`,和 `coverage_audit.py` 并列进数据质量检验
流水线,而不是留作一次性脚本(参照 [[quality-checks-ride-the-pipeline]] 的
教训)。当前证据是手工跑的,没有固化,下次语料改版后这个对照会过期。

## 2026-08-30 批次(来源:AWS 主跑首日,image 族 92% 通过率溯源)

### image 族内判据分布配平(4 种 → 官方 15 种)

**归因勘误(08-30 深夜)**:表格规则 58% 垄断的真凶是提示词明文指令
"Use sheet_data as the backbone"(single_json.txt:228),非此前记的"示例引力"——
示例本身只有结构无内容(用户记忆正确,原文核实)。修错地方警告:改示例治不了这个。

**发现**(AWS session 实查官方 26 条 gimp 任务;数字详 PLAN-20260829-aws-rollout):
官方 image 族用 15 种判据,方向判据(亮度/对比/饱和/镜像)只占 15%;v14g 的
`IMAGE_FUNCS` 白名单只取了这 4 个方向函数铺满全族 —— **族规模配平了(8.8% vs
官方 7.0%),族内构成没有**。后果:92% 通过率(方向严格不等式,幅度不设限,
1/255 也算过)+ 成功语料里超配 1.5 倍 + 轨迹全是"拖滑块"最窄操作面。

**为什么当初只取 4 个**:机器层约束,不是失察 —— v14g image 族走"seedful 方向
判据"gold 机型(expected=种子图,无需生成 gold 文件)。官方其余 11 种各要
不同机器:gold 参照物类(palette / green_background / structure_sim_resized)、
参数化规则类(image_size / triangle_position / textbox_on_leftside)。

**修法**(下一轮 gen 立项时做):给 image 族扩 2-3 个 gold 机型
(规则类最便宜,先做 image_size/triangle_position/textbox 三个;参照物类
沿用现有"执行后收割"机器,transform 脚本产出参照图),`IMAGE_FUNCS`
白名单随机型扩容,配方里按官方族内比例配权。验证:family_census 加
族内 func 直方图一列,对官方逐 func 对照。

**当下处置**(已定,不等下一轮):curate 阶段 image 族成功轨迹按池占比 8.8%
封顶 + 子模式去重,并在 SFT_DATA 注明"子模式天花板=4 种滑块动作"。

### 高难度任务的"旅程绕过"漏洞与复合判据(同批次追加,2026-08-30 凌晨实锤)

**实锤样本**(wave2-all 抽 d4/d5 image 任务):`spectro-plate-contrast-log`(d5,
app_count=3)指令 = GIMP 调对比度 **+ 在校准表追加 plate id/字节数行**,判据 =
`check_contrast_increase_and_structure_sim` 单函数 —— **旅程后半段(表格)零验证**。
d4 两条同型(QC 笔记/SHA-256 证据日志均不验)。

**机理**:ostg 的 difficulty 语义 = 旅程复杂度(d>=3 即 multi-app 约定),判据强度
是独立维度。table_gold 等族的终点(整簿字节)自带旅程背书;image 族方向判据只有
1 bit,d5 的复杂度在判分时蒸发,教师可只拖滑块跳过旅程照样得分 —— "d5 标签 +
6 步滑块轨迹"会污染语料的难度语义。

**修法(下一轮 gen,优先级高于扩 15 种 func)**:d>=3 的任务判据一律**复合**
(官方 evaluator.func 本就支持列表):终点判据 + 旅程副产物判据(表格行/日志文
件/侧产物,gold 机型现成)。image 族最急;config/browser 等窄终点族次之排查。

**本轮处置**:build 时对 image 族 d4/d5 成功轨迹抽检旅程完成度(第二应用的文件
被碰过没),跳过旅程的样本剔除或按 d1 口径记账,不让假 d5 进语料。AWS 轨迹
rsync 回来后先量一版跳过率。

### L. 把"操作"变成可称量的轴(2026-08-31 实锤;下一轮配方的主改动)

**病**:配方能称量的最细的轴是 family/intent16(≈10 个判据一组),而"这条任务
要求做哪个具体操作"比它细一级 —— **不受控,塌向生成器的众数**。三个域独立实锤:

| 域 | 表现 |
|---|---|
| calc | "做图表" **0/76**(官方 47 条里占 13%);"新建工作表" 3%(官方 28%) |
| impress | 85% 是改文字;格式 3.6% / 备注 2.0% / 版面尺寸 1.6% |
| image | 15 个判据维度里只有 4 个被碰过 |

**同一批数据里的对照实验(这是最硬的证据)**:v16-main-1 的 1195 条里,
**被抽取的五个轴一个都没塌**——

```
difficulty  33.8 / 33.2 / 33.0 %          目标 1/3 各一份
voice       contextful 33.6 · terse 32.4 · polite 23.2 · sloppy 10.8   目标 35/30/25/10
intent16    19 个意图族,每族 4.7-6.0%    极均匀
ambiguity   27.3 / 25.1 / 23.3 / 24.4
primary     9 个应用全覆盖
```

**结论**:同一套代码里,**抽取的轴全部忠实,留给提示词的东西全部塌陷**。
所以"在提示词里多给几个示范操作"是错的解法 —— few-shot 的引力会把所有调用
拉向那几个例子(生成侧上午刚栽过一次:一个 `sheet_data` 示范压塌了规则白名单)。

**药**:把操作放进坐标,不放进提示词。

```
coords = {..., "operation": "create_chart"}
提示词只说:"这个任务必须要求:{operation}"
每次调用只看到一个取值 → 不同调用看到不同的 → 分布由权重保证
```

`intent16` 就是这么加的(19 个取值,跑出来 4.7-6.0%),照抄那条路。

**操作清单从哪来**(量过,规模可管理):

| 来源 | 规模 | 说明 |
|---|---:|---|
| 官方 369 的判据 func+options 组合 | **171 种** | 机器可 derive,不依赖语言判断 |
| 官方 369 指令里的动作动词 | **41 种** | 粗但够用,和 intent16 的 19 同量级 |
| 动词 × 应用 | 约 60-100 | 折中 |

**v16 对官方操作面的覆盖率(动词口径,已量)**:

```
chrome 75% · impress 62% · calc 61% · vlc 56% · thunderbird 53%
vs_code 43% · writer 40% · gimp 27% · os 27%
```

缺口举例:calc 缺 `create/calculate/merge/filter`,gimp 缺 `convert/rotate/fill`,
os 缺 `install/configure/count/append`。反过来 v16 在 calc 里多出
`save(36) open(20)` —— 官方指令里"保存"是隐含的,v16 把它写成了显式要求,
这也是 calc 显得简单的原因之一。

**三条设计约束(讨论中定的,别丢)**:

1. **取清单,不取权重。** 用官方去*发现*有哪些操作是合理的(人工策展的"值得测"
   清单);用官方的*频次*当权重就是 fit 测试集。权重该按能力面配,不按官方考了几次。
   而且官方 369 本来就不是评测目标(撞题风险在 CUA-Gym,见 memory)。
2. **留自由档,枚举表是地板不是天花板。** 70-80% 从表里抽保证覆盖,20-30% 抽到
   `operation=<free>`(提示词对操作只字不提)让生成器自由发挥;**把自由档产出的
   操作回收、去重、补进表** —— 表自己长大,长的是真实产出过的操作。
3. **未验证可生成的操作,能列不能称量**(vocab 那条规矩的延伸)。给一个机器做不出
   的操作赋权,等于让它执行一个做不到的政策。

**LLM judge 解除了一个旧约束**:官方那 171 种判据组合是被"`compare_table` 能不能
验"框住的。判官能看截图 + 磁盘状态,可验的操作面宽得多 —— **做图表就是典型**:
官方几乎没有判据能验图表(要读 xlsx 里的 chart XML),而判官看一眼就知道。
所以扩写应该往**应用能力面 × 判官可见性**扩,官方清单只是起点。

**排期**:下一轮 gen 的主改动。优先级高于扩 func 白名单 —— 因为这条是
"图表/多表构建/格式操作全缺"的共同根因,补它一次能同时修三个域。

### 教师显式自检臂(2026-08-30,候选实验;不动 v15/在跑线)
系统提示加一句"宣告完成前逐条核对题面要求",eval-50 加一臂(~2h)。
靶:假 DONE 12-28%、顶步数上限的绝望宣告。代价:每题多几步核对。
排期:补波收官后;若不掉分且假 DONE 降,进下一轮 rollout 候选配置(medium 路数)。


## 训练侧:按步/按轨迹归一化 loss,替代按 token 平均(2026-09-01 用户提出,待排)

**现状**:`--loss_scale last_round` + `average_tokens_across_devices=True`,分母是 global
batch 的目标 token 总数 → **按 token 平均**。一步 8K 字 think ≈ 30 步 250 字;一条 40 步轨迹
≈ 40 条 1 步轨迹。

**实测失衡(mixB 语料,18,576 步 / 866 轨迹)**:

| 量 | 中位 | p90 | p99/最大 |
|---|---|---|---|
| 每轨迹步数 | 18 | 42 | 50 |
| 每步目标长度(字符) | 552 | 1,853 | 5,832 / 31,700 |

按 token 平均时:**最长 10% 的步吃掉 38.8% 的 loss,最短 50% 的步只占 19.0%**;最长 10%
的轨迹占 31.1%(按轨迹等权应为 10%)。长轨迹的步还更长(>30 步的轨迹平均每步 865 字 vs
≤5 步的 683),两种偏置叠加。§8 的"学生 think 发散是训练动力学产物"与此直接相关:
长 think 的步在梯度里权重最大。

**三个归一化层级,回答的是不同问题**:

| 层级 | 权重 | 纠正的偏置 | 风险 |
|---|---|---|---|
| 按 token(现状) | 1 | — | 长 think / 长轨迹主导 |
| **按步**(每个样本等权,w=1/len) | 1/n_tok | 长短 think 等权 → 直接对准 §8 的发散 | 短步里的 terminate/单击目标权重上升,是否过拟合短模板待看 |
| 按轨迹(每条轨迹等权,w=1/(n_tok·n_steps)) | 1/(n_tok·n_steps) | 长任务过采样 | **反向压低 multi_apps 这类长任务**——恰是最弱的域;步级过滤后剩几步的轨迹每步权重反而暴涨 |

**用户问的"step filter 之后按实际步数归一化"**:按轨迹归一化用的是过滤后的存活步数 n。
它的副作用是被砍得只剩 3 步的轨迹,每步权重是 50 步轨迹的 17 倍——把噪声残片放大。
建议:**先做按步归一化(只动一个变量),按轨迹用 1/sqrt(n) 这类折中作第二臂**,并按域看
分数(multi_apps 是否掉)。

**机制**:swift 的 `loss_scale` 是正则→权重的逐 token 配置(`ignore_empty_think`、坐标
加权走的同一机制),**没有现成的"按样本 1/len"**;需要自定义 loss_scale 插件或在
`to_swift` 阶段给每行预算权重。落地前先在 Tillicum 的训练环境里核 `swift/plugin/loss_scale/`
接口(本日从 WSL 侧没找到 swift 安装路径,见 TRAINING「环境」)。

**臂设计**:以 mixB-9b 为基线,**只换加权**,其余(语料、lr 3e-6、gb64、3ep、img10/fold1)不动;
eval100 配对读,并附 §8.5 的 think 长度表(按步归一化若有效,p99/最大应明显下降)。
