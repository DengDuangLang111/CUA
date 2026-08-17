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

### 裁决后的优先级分叉(预登记)

若今日 B 四臂 eval 确认损伤依旧:静态语料扩张(含 best-of-3/C 臂)的
边际价值存疑,**A(replay)与 E(intervention)有资格插队到 C 臂之前**
——届时与用户重排,不默认执行。

### 排队关系(2026-08-17 时点)

主线不变:B 四臂 eval(量+优化域裁决)→ rerun3/best-of-3 → C 臂(质裁决)。
本档案的 A 在 C 臂裁决后第一顺位;B 在 A 之后;C/NLL 探针可与任何阶段
并行(只读+纯前向,不占 VM)。
