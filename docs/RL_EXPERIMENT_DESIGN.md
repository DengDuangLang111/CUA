# 桌面 CUA RL 实验设计：Qwen3.5-9B SFT → GRPO

日期：2026-09-18(09-22 更新)。状态：**P0 已完成**(09-22：π1 发布为新服务 → π1 在策略采样 16 回合 → 从 step1 恢复并更新到 step2 → 独立校验通过，得到 π2)；**P1 已完成并过关**(09-22 23:57)；P2 题单已定(train 64 / dev 24)；持续 online RL 尚未启动，上游源码未改。**训练题来源已改为 CUA-Gym 去除与 OSWorld-Verified 重叠的部分**(用户 09-22 选方案 a)。

**最新进度**：普通r5-9B checkpoint-306已完成16条真实轨迹；其中Writer完整四轨迹group已完成一次HF/DeepSpeed GRPO更新，原生clipped loss复用OpenWebRL。127次输入匹配、33次backward、global_step1、独立权重变化/视觉冻结/重新加载均通过。采用训练侧old-policy重算。09-22 已验收：新权重发布为新服务并做 VM rollout、从 checkpoint 恢复后第二次更新；仍未做：跨后端采样一致性(vLLM 与 HF 的 logprob 差异仍存在)、不重启服务的在线权重同步。精确结果和运行证据见[环境进度MD顶部](RL_ENV_PLAN.md)。以下较早执行说明保留历史背景，以最新记录为准。

**执行进度更新**：用户授权试跑后，已按其指定在 workstation 完成 Calc 的 P0 环境/评分/重置检查（0 → 0.7 → 1 → reset 后 0），原始任务/evaluator 未改；测试 VM 已全部停止。此为 scripted fixture 资格检查，不是模型 rollout 或 RL update。完整事实与文件证据只记录在 [环境进度 MD](RL_ENV_PLAN.md)。后续 P0 优先使用 workstation 的独立空闲 slot，Windows 既有评测保持不动。

**后续真实模型试跑已完成**：普通 r5-9B checkpoint-306 已核实、发布并以单 L40S 服务；一个 Calc task 在原 GUI agent 下完成9次决策，reward=0，采集与页面验证通过。最可能的失败原因是未保存；另有第三项评分要求未明确写在指令中的疑点。该次只是单条可记录的真实 rollout，尚未完成本设计的16任务信号探测或参数更新。执行细节与原始成绩仍以环境进度 MD 为准。

用户已确认初始模型：**现有 Qwen3.5-9B CUA SFT**。普通r5 checkpoint-306已核对并以校验后的推理文件部署，路径和发布清单见环境进度MD。主 benchmark 已由用户于 2026-09-22 确认为 **OSWorld-Verified**(官方 361 题)；OSWorld-V2 仍只作后续迁移检查。

本文件是实验问题、对照和预算的权威设计；环境事实与操作历史见 [RL_ENV_PLAN.md](RL_ENV_PLAN.md)。

## 1. 要回答的一个问题

**在相同桌面交互预算下，保留程序 evaluator 的部分完成分，是否比仅使用完整成功/失败的 GRPO 更有效地提升桌面 CUA，并迁移到 OSWorld？**

假设：部分分让原本“全失败”的 trajectory group 产生可区分的 advantage，提高有效训练信号利用率；如果只是提高可刷取的部分分，却没有提高完整任务通过率，则不支持这个假设。

**实际优势差异也要检查**：标准化 GRPO 对组内 reward 的正仿射变换近似不变（忽略 epsilon）。例如只有0.4/1两档且分别对应失败/成功时，Partial 与 Binary 的优势可能几乎相同；出现部分分本身不是额外训练信号的证据。pilot 同时记录两种 reward 的有效组比例、标准化优势和差值；重点看 binary 全0而 partial 有方差的组，或多档 reward 真正改变了组内比较的组。

先验证能否正确训练，再检验研究假设。首轮不同时研究 ARM、GiGPO、TMAX 初始化、长 history、新图像压缩、多 agent、curriculum 或 Orchard 扩容。

## 2. 三个对照

| 标识（设计标签，非已登记 run ID） | 初始化 | 更新方式 | 训练 reward |
|---|---|---|---|
| A：SFT baseline | 同一个冻结的 9B CUA SFT | 不更新 | 无 |
| B：Binary-GRPO | 同上 | OpenWebRL/slime GRPO | 原 task 的完整成功判定，合格任务中通常为 `1[r >= 1 - 1e-6]` |
| C：Partial-GRPO | 同上 | 与 B 完全相同 | 原 task 的终局分数 `r ∈ [0,1]` |

B 与 C 唯一研究变量是 reward 是否保留部分分。相同的任务候选顺序、reset seed、初始化、prompt、动作 parser、模型图像预算、步数、采样温度、optimizer、loss weighting 和原始环境尝试预算。

Binary 判定以任务实际满分规范为准，不复用 Arijit `won >= 0.5` 的标签。只用可核实 reward 已归一到 [0,1] 的任务；不静默裁剪异常分数或重新定义满分。

A→B/C 回答继续 RL 的增量；B→C 回答部分分是否有用。它们不能单独证明 RL 优于所有继续 SFT 方法；若后续要提出这种主张，再补 continued-SFT 对照，不把它塞进第一轮。

## 3. 模型与协议冻结

### 已定与未定

- 模型家族：Qwen3.5-9B；初始化是用户已有的 CUA SFT，不换成 web SFT，也不混入 TMAX。
- 已固定普通r5 checkpoint-306（epoch3），延续真实rollout已核验的同一初始化。
- 已通过现有registry登记 `9b-full-r5--train20260822--s306`，本批16条使用该模型服务。
- 每个对照从同一权重重新开始；不能 B 训练后接着训 C。

### 启动前冻结的内容

权重及 tokenizer/processor/chat-template 哈希；完整模型配置；SFT 训练来源清单；system prompt；tool schema / action parser；原生截图尺寸、模型实际输入尺寸、图像 token 数、history 处理、thinking 序列化、终止语义。

优先沿用该 SFT 模型已经验证的 CUA 格式，不能直接把 OpenWebRL 的 browser 工具定义或 Arijit 的 `computer_use` prompt 拼进去。底层实际执行仍是 OSWorld PyAutoGUI。

设计起点：1920×1080 原生桌面；图像 history 10 张 / fold 1；每轮最多 4,096 个生成 token、总 context 65,536；训练最多 30 个 environment steps，temperature 0.8 / top-p 0.95。除原生桌面尺寸外，以上均为待显存/截断测量确认的起点，不冒充已核实的旧 SFT 配置。若必须降低预算，应在三个臂的正式 baseline 前统一冻结并重新测 baseline。

最终 OSWorld 评测保留选定 benchmark 的统一任务预算；可以与训练的 30 steps 不同，但 A/B/C 的评测预算必须一致。不能把当前 27B Teacher 的 81,920-token 上限照搬给学生。

### Qwen3.5 训练后端是硬门槛

2026-09-18接入检查：已复用现有HF完整多模态模型验证127次真实输入token与图像网格。现有vLLM保存的是temperature前raw logprob，与上游loss的temperature缩放口径不能直接混用；当前单步资格测试采用上游支持的训练侧old-policy重算（`use_rollout_logprobs=False`语义），old/new同为temperature0.8，原始rollout logprob保留诊断。此为HF+DeepSpeed独立短测，未完成OpenWebRL在线调度和权重同步；跨后端数值差异仍需在正式训练前处理并明确重要性采样口径。结果以环境进度MD为准。

Zixian fork 的现有主要 launcher / model presets 是 Qwen3-VL 路线；README 中的 Qwen3.5-9B RL 链接指向另一个 `MSR-Orchard/slime` 分支。仓库里有 Qwen3.5 权重映射代码，不等于当前整套 Python/CUDA/Megatron/SGLang 组合已验证可训练 9B。

在独立 GPU 环境中先验证：9B checkpoint 无意外 missing keys 地加载；原生图像/工具输出正常；训练前后 logprob 与模板一致；一次 backward/update 成功；权重同步后 policy version 改变。失败时先修这一个兼容问题，不偷偷改成 4B 或同时换算法。

## 4. 训练数据与留出集

### 现有数据

四类候选 7,249 个：Calc 2,576、Writer 2,093、Impress 1,402、VS Code 1,178。

其中 **6,391** 个使用 Python 初始化：Calc 2,540、Writer 1,791、Impress 1,039、VS Code 1,021。其余 **858** 个为 xlsx/docx/pptx/sh 等初始化。当前 Arijit bridge 有把首个 setup 文件当 Python 执行的路径，因此首轮只从 6,391 个 `.py` setup 候选中筛选，暂不增加异构初始化适配。

这些是候选数量，不是已经在 Windows VM 上通过验收的数量。已落盘的四个 desktop pilot 仅做接入检查，固定归入工程/训练侧，不进入最终 holdout。

### 划分提案

| 集合 | 目标规模 | 每应用目标 | 用途 |
|---|---:|---:|---|
| Engineering pilot | 16 | 4 | 初始化、评分、轨迹与训练链路排错；视为 train-side 数据 |
| Train | 256 | 64 | 正式 B/C 训练；pilot 尽可能属于本集合 |
| Dev | 64 | 16 | 固定预算节点的运行诊断；不读取 final holdout 来调参 |
| CUA-Gym holdout | 128 | 32 | 一次冻结的独立最终域内测试 |
| OSWorld benchmark | 默认 361；V2 另计 | 按官方 manifest | 外部迁移；不加入 RL 训练 |

上述规模是验收后的目标，不是已经生成的名单。如果去重后不足，按实际 family 数缩小并记录，不拆开同 family 来凑整数。

### 先去重，再按 family 分配

不能仅对 task id 随机分割。结合指令近似度、初始化产物/模板、setup 和 reward 的结构，识别同模板改名字/数字的任务；人工复核跨 split 最近邻。一个 family 整体放在同一 split，尽量保持应用和操作类型覆盖。难度标签缺失较多，仅作辅助分层，不伪造 easy/medium/hard。

额外核对新增 RL 数据与目标 OSWorld benchmark，以及已有 SFT 数据的任务/资产近重复。已有 SFT 对 benchmark 的历史接触不能被新的 split 消除：若无法证明未接触，只能称“固定已有 SFT 初始化上的 RL 增量”，不能声称完全未见 benchmark 泛化。保存 `split_manifest`、family id、筛选理由与文件哈希。

### 任务入池门槛

1. 在独立桌面 VM 中两次 reset，关键初始文件与设置一致；setup 成功可见，截图非空。
2. 不做动作的初始 reward 接近 0；首轮对意外初始满分/部分分先隔离分析，不擅自减 baseline 或修 grader。
3. 确认完成状态能给满分，未完成/部分完成状态分数有合理区分。没有公开 golden 文件时，用独立核对的脚本解或人工解验证，明确其只属于环境资格检查。
4. evaluator 无异常、无缺文件被误当普通 0 分；任务脚本只在 disposable VM 内执行。
5. 数据中的初始化所需应用/包实际存在；不以本机 `pip check` 代替 VM 验收。

入池按环境可执行性和 reward 有效性筛选，不根据最终 benchmark 表现选训练任务。不删除“模型不会做但环境有效”的任务来美化评测。

## 5. 训练配方（启动提案，不是已运行参数）

| 项目 | 首轮设置 |
|---|---|
| 框架 | OpenWebRL/slime，保留 GRPO 主干 |
| 模型更新 | 语言模型全参数；冻结 vision encoder/merger，冻结行为需逐模块核对 |
| Group size | 每个 task **4 条**独立 trajectory |
| 分组 | 同 task、同 reset seed / 初始状态、同 policy version；单 VM 串行也可 |
| 训练样本 | turn-level；终局 reward 传播给该 trajectory 的各 turn |
| 归一化 | 按 task group 中的独立 trajectory 分数归一化；不能把 30 个 turn 当 30 条独立 episode |
| 长轨迹权重 | B/C 同时启用现有 `turn_level_loss_weight_by_num_turns`；检查 sample_weights 真的进入 loss，避免长轨迹仅因 turn 多获得更多权重 |
| PPO epochs | **1**，先减少同批旧策略数据复用 |
| Learning rate | **5e-7**，constant；第一轮不扫 LR |
| Clip | 0.2，B/C 相同 |
| KL / entropy | 初版系数均为 0，与 Zixian outcome baseline 的零系数路线一致；如 pilot 显示明显漂移，先修改统一协议再重跑 A/B/C，不只给某一臂补约束 |
| 采样和上下文 | 按 §3 冻结；token limit 与 max_steps 分开记 |
| Optimizer batch | 目标每次更新收集 4 个有效 task groups；实际 turn 数可变，不照搬 web launcher 的 global_batch_size=256 |
| 动态采样 | 使用组内 reward 非零方差过滤，但必须设置原始尝试上限并记录所有被过滤组 |

组数据不能跨权重更新拼接。收集不足时使用当前后端支持的较小完整 group batch，或跳过并记录；不得为满足 batch 整除静默复制样本、拆散 group 或丢失部分 trajectory。批次/DP 整除和 turn weighting 在 pilot 先验收。

**计费单位是原始环境尝试，不是被保留的训练样本。** Binary 更容易产生全 0 组，Partial 更容易有分差；若二者都收集相同“accepted groups”而不限尝试数，会给 Binary 额外环境预算。因此相同候选 task 顺序、同总 attempt 上限，允许有效更新次数不同并如实报告。这是待检验的样本利用率机制。

模型造成的失败/非法动作/正常步数耗尽得实际终局任务分数（解析无法继续时记模型失败 0）；两臂不加额外 -1 格式奖励或步数惩罚，以免混入第二种 reward 差异。

VM crash、reset 失败、截图服务不可用、evaluator crash 标为 infrastructure-invalid，保留日志并按预设最多重试一次；失败尝试仍计入资源账。无效 episode 不伪装成 task reward=0。若某组被基础设施打断，重试/丢弃以整个 group 的规则执行，不能只保留高分成员。

## 6. 运行阶段与预算

### P0：环境与模型链路验收

- 先用已准备的 4 个应用 pilot，独立 reset → scripted action → evaluator → cleanup；此阶段不训练。
- 为一条实际模型轨迹保存 token IDs、每个生成 token 的 rollout logprob、图片输入身份、loss mask、原生/模型坐标、turn/trajectory/group ID、policy version。
- 完整 assistant reasoning+action 的训练边界与 SFT 一致；截图/工具反馈的生成损失 mask 为 0。查真实序列化，不靠参数名推断。
- 构造 0 / 0.3 / 0.7 / 1 的合成 reward group 验证分组与优势；验证全等 reward 组被正确统计/处理。
- 一个小 batch 的 backward、optimizer step、checkpoint 保存和 rollout 权重同步均通过才进入 P1。

### P1：16 个任务的训练信号探测

- 4 个应用各 4 task，基于冻结 SFT 每 task 4 rollout，共 **64 episodes**。
- 统计完整成功率、原始部分分、全 0 / 全 1 / mixed groups、模型失败与环境失败。
- 若环境无效率 >5%，先排环境；若格式无效率 >5%，先排模型模板/parser。
- 若 fewer than 4 / 16 groups 有任务奖励差异，不直接扩算力；先看初始化、grader、任务难度与 SFT 能力，形成改动理由。阈值是本次工程决策门槛，不是算法定律。
- P0/P1 整体模型 rollout 初始预算上限 **128 episodes**；超出前重新估算，不无上限重采样。

### P2：小规模 B/C 对照，决定是否继续

- 使用 Train 中固定的 64 tasks（每应用 16）作为小规模子集。
- B、C 各 **256 原始 episode attempts**（无重试时为 64 groups × 4）；重试占同一预算并减少最终完整组数。相同起点、候选任务顺序与尝试预算。
- 每臂保存预算中点和末点 checkpoint；以最终预算点作比较，不用 final test 挑最好 checkpoint。
- 只用 Dev 中固定的 32 tasks 评 A、B、C，各一条 rollout；**32 题仅看故障/退化/学习迹象，不做可靠提升或显著性结论**。
- 若训练样本全无有效 reward 差异、梯度/权重不更新、终止/格式崩坏，停止进入 P3。

### P3：正式单 seed 对照（只有 P2 通过后）

- 扩到 Train 256 / Dev 64 / CUA holdout 128。
- B/C **各 1,280 原始 episode attempts**（无重试时为 320 groups）；从同一冻结 SFT 重新开始，P2 权重不作为正式初始化。
- 在 320 / 640 / 1,280 attempts 附近保存并评 Dev；组边界对齐，不拆组。主比较使用最后预算点，较早 checkpoint 只作学习曲线。
- 最后对 A/B/C 跑 CUA holdout 128；通过预先冻结的正式评测入口，运行主 OSWorld benchmark。
- 一次训练 seed 仅产生探索性结论。若有希望，再以另外两个训练 seed 重复 B/C，并按同一 benchmark/decoding 协议复核，不把首次最佳 seed 当最终结果。

### 预算算账

- P2 主体：512 个训练 attempts + 96 个 Dev eval = **608 episodes**（不含 P0/P1）。
- P3 训练：2 × 1,280 = **2,560 attempts**。
- P3 Dev：A 64 + B/C 各 3 × 64 = **448 episodes**。
- P3 CUA holdout：3 × 128 = **384 episodes**。
- 默认 Verified 主评测：3 × 361 = **1,083 episodes**。
- P3 单 seed 合计 **4,475 episodes**；这不是建议立刻全跑。若改以 V2 108 为主，对应主评测 324、合计 3,716，但 V2 每任务成本可能明显更高，不能按题数比例估算时间。
- 以上不包含任务资格检查、额外种子、VM 镜像准备和模型转换：Train/Dev/Holdout 目标共 448 tasks，若逐题做两次初始 reset，至少另有 **896 次 reset 检查**，以及每题的完成状态评分验证。应分批验收（P2 只先验收其所需子集），记录成本，不能把这些当免费数据准备。

先在 P0/P1 测包含 reset 和评分的每 episode 平均/长尾耗时 `t`，分离 GPU inference、VM 等待与 optimizer 用时。环境侧粗略下界 `N*t/concurrency`；加上训练/保存/服务切换和失败成本后再承诺时间。

例如仅作预算演示：4,475 episodes，平均 2 分钟，独占 3 个 VM 时理想环境时间约 49.7 小时；10 分钟则约 248.6 小时。实际当前 VM 可能被已有实验占用，不能当成已有 3 个空闲 slot。GPU 数量/显存不从 SFT 资源直接推定，需测 actor+rollout+optimizer 峰值后确定。

## 7. 怎么判断实验成败

### 效果指标

- **主要迁移指标**：固定官方 manifest、固定 evaluator 与相同 agent 协议下的 OSWorld 完整成功率，C−B 和 C−A 都报告。
- **域内主要指标**：CUA holdout 完整成功率；原始 reward 均值与各应用结果作为辅助。
- **效率指标**：每 100 个原始 attempts 得到的有效非零方差 groups、达到固定成功率所需 attempts；同时给每 GPU-hour / VM-hour 成本。
- **行为指标**：步数、生成/think token、格式错误、重复动作、结束方式、max-step/token/context 截断率。不能用“平均 reward 上涨”代替完整成功提升。
- **数据质量指标**：reset / evaluator / 截图错误率；所有预定任务的完成覆盖率；重试次数。

固定 N 个任务同时报告有效评分覆盖率、完整成功/N 的端到端下界，以及 valid-only 诊断。不能只删除异常任务后报更好看的成功率。正式目标覆盖率 ≥98%；不足时结论标记不完整并先排基础设施，不改变 N。

### 对照与统计

- A/B/C 用相同 task ID、初始化 seed、模型调用设置、步数和 evaluator。每个任务尽量交错评三个模型，降低服务状态/时间漂移；不能拿历史 SFT 分数直接相减。
- 每 task 保留可配对 verdict 与原始轨迹。二值成功可做 paired McNemar，分数差可做按 task/family 的 paired bootstrap；多训练 seed 后同时展示 seed 方差，不能把多个 seed 下的同一 task 当成完全独立样本。
- 预先指定 C−B 为部分分假设的主比较，C−A 为 RL 增量的第二比较；其他比较为探索性，或做多重比较校正。
- **工程目标**可设 holdout 完整成功率提高 ≥5 个百分点，但这不是承诺，也不代表该样本规模一定有统计功效。只有配对区间与复现实验支持，才称为稳定提升。

### 结果如何解释

| 观察 | 解释 / 下一步 |
|---|---|
| C 比 B 多有效 groups，且完整成功更高 | 支持部分分改善稀疏奖励下的训练效率；再做 seed 复核 |
| C 部分分更高，但完整成功不升 | 可能只学会容易得分的子目标；不称任务能力提升 |
| B/C 在 CUA holdout 提升，OSWorld 不升 | 域内学习成立，跨任务/应用迁移尚未成立 |
| 训练 reward 涨，holdout 降 | 检查模板过拟合、reward 利用、模型漂移 |
| 全等组太多，几乎无有效更新 | 先排任务/初始化/评分与初始策略能力，不能用 loss=0 当训练成功 |

## 8. 部署与代码边界

- 复用此前只读核实的 Windows → WSL Ubuntu → Docker/KVM 桌面路径；共享基线 `d552441` / v2026.08.08，正式运行前再确认实际 code/image/task/asset hash。
- 不操作另一个 agent 正在用的 VM。先分配 1 个独立 RL slot；是否增加并发要按当时空闲资源和实测吞吐决定。
- GPU 主机运行 trainable policy 推理与 OpenWebRL/slime 更新；Mac 只管理代码/记录。已有固定 teacher 服务不是正在更新的学生策略。
- 新代码预期只在独立 RL worktree 加环境服务、desktop rollout/reward adapter、配置；复用已有 screenshot/动作 parser/evaluator，不改正式评测行为。
- 不自动部署 Orchard；单 worker 训练闭环和效果均验证后，才讨论将相同接口放入 Orchard 扩容。
- 新 model/benchmark/panel 通过现有 `CUA/sft/scripts/eval/run_eval.py plan/doctor/run/status/resume` 体系登记与执行，不再造一套评测 launcher。正式 eval 默认接现有轨迹页面流水线；新接口排错归 `test`，正式比较归 `eval`。
- 模型转换、SGLang 权重同步、跨主机通信先各测一个小样本；endpoint 能返回模型名不等于截图和长消息请求正常。

## 9. 每次 run 必须能追溯

保存 code commits、checkpoint 哈希、task/family/split manifests、VM/image/asset hash、原始 reward 与 evaluator 输出、采样/图像/坐标协议、每组 policy version、attempt/valid/accepted/updated 计数、失败原因、每阶段耗时与峰值资源。

记录每条轨迹的真实输入、response token IDs/logprobs/mask、图像身份和动作，支持从某个 reward 回溯到具体文件与操作。复用现有日志结构和 renderer，不引入新 dashboard 或在线监控平台。

## 10. 当前进度与执行前剩余项

- [x] 用户确认 Qwen3.5-9B CUA SFT 初始化。
- [x] 任务候选数、Python 初始化子集、GRPO/GiGPO 区别与现有 Windows 路线已核对。
- [x] 明确 A/B/C、原始交互预算匹配、reward 与失败语义、数据划分和验收门槛。
- [x] 用户确定主 benchmark：OSWorld-Verified(官方 361 题，2026-09-22)。
- [x] 初始SFT checkpoint / model registry / 已执行采样协议冻结。
- [x] Qwen3.5-9B在HF/DeepSpeed完成加载、backward、单步更新、保存和独立重载。
- [x] 新权重发布为新服务、VM rollout、第二轮更新及 checkpoint resume 验收(09-22，π1 → π2)。
- [ ] 不重启服务的在线权重同步(目前每次更新后重新发布并起服务，加载约 3 分钟)。
- [x] 独立VM slot、SFT endpoint和单步训练GPU资源已验证；π1 endpoint 已部署(g3108 GPU3，端口 8083)。
- [~] 任务资格检查、family split 和与 benchmark 的重叠审计：P2 所需部分已完成(09-22)；与旧 SFT 数据的重叠未单独审(SFT 题生成时已按 CUA-Gym 文本相似度 <0.50 回避)；P3 规模的候选池不足，需扩池。
- [ ] 持续训练调度adapter待接入；原生VM任务adapter及离线训练样本导出已实现并运行。
- [x] P0 完成(09-22)。
- [x] P1：16 题 × 4 条 π0 采样完成(09-22)。环境无效 0/48，未检出格式无效；有差异组原始分 10/16、Binary 9/16，过关。只在 Partial 下才有差异的组仅 1 个(已被重叠审计排除)。详见 RL_ENV_PLAN。
- [x] 重叠审计(对 OSWorld-Verified)与家族划分(09-22)；P2 题单：train 64、dev 24(Impress dev 仅 1)，每题经审题、四态检查与 VM 往返检查。
- [ ] 按 P0/P1 实测吞吐批准 P2/P3 预算。

## 源码依据

- [Zixian OpenWebRL](https://github.com/zixianma/OpenWebRL)：固定 `9da6dc1`；主 launcher 的 GRPO/custom generate/custom rm，`slime/ray/rollout.py` 的 trajectory reward grouping 与 turn weighting。
- [Qwen3.5-9B RL 参考入口](https://github.com/MSR-Orchard/slime/blob/main/examples/orchard_gui/scripts/run_browser_qwen3.5_9b.sh)：是 OpenWebRL README 指向的另一仓库，尚未作为本实验运行基线。
- [CUA-Gym 公开数据](https://huggingface.co/datasets/xlangai/CUA-Gym)：本地 `tasks.parquet` 实测候选统计；这里只承诺读取到的数据规模。
- 本地 `cua-rl-local/sources/multi-agent-framework/.../cuagym/worker_bridge.py`：桌面初始化/执行/reward；AWS provider 与 v1 JSON 限制不能直接照搬。
- 本地 `OSWorld-V2-personal/local_eval/`：现有共享协议与 WSL 基线；`CUA/sft/docs/EVAL_AUTOMATION.md`：统一评测入口。
