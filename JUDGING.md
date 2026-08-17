# JUDGING — rollout 打分体系(judge / 仲裁 / 筛选)

> 本文件只讲一件事:**一条 rollout 轨迹是怎么被打分、被复核、被分类的**。
> 命令行速查在 `RUNBOOK.md`「质量审计三命令 / 筛选四步全流水」;
> 具体测量结果在 `SFT_DATA.md`;候选实验在 `IDEAS.md` §J。
> 代码:`ostg/sft/{trajaudit,stepaudit,arb,curate}.py`(canonical 在 WSL)。

## 1 三种打分,互不替代

| 名称 | 模块 | 打分对象 | 看得到 checker 吗 | 用途 |
|---|---|---|---|---|
| checker(程序评分) | OSWorld harness | 整条轨迹 | 它自己就是 | 真值(**但有 bug,见 §6**) |
| 盲评判官 | `trajaudit` | 整条轨迹 0-10 | **否** | 提名嫌疑、给成功轨迹分层 |
| 步级判官 | `stepaudit` | 单步 0-2 × 3 维 | 否 | 找弱步/长考病理 |
| 仲裁 | `arb` | 分歧轨迹 | **是(亮代码)** | **唯一有权定罪的环节** |

铁律:**判官提名,仲裁定罪**。判官分数不得单独移动任何轨迹的去留。

## 2 盲评判官(trajaudit)

**输入(每条轨迹一次独立 API 调用,无跨样本上下文):**
- 任务原文;
- 10 张截图 = 初始帧 + 均匀取样的步后帧 + 末帧(v2 起每帧带编号与"第几步之后"标签);
- 全部步骤的动作列表;
- 每步 90 字思考摘要(v1/v2/v2req 均只给摘要)。
- **不给**:checker 判决、评分代码、任何 pass/fail 字样、结果目录名。

**completion 0-10 刻度(写死在系统提示):**
| 分档 | 含义 |
|---|---|
| 0-2 | 明显失败或方向错 |
| 3-4 | 重大缺口,不太可能完成 |
| 5-6 | 部分完成,或证据不足以判断 |
| 7-8 | 大概完成,有小瑕疵(绕路、冗余) |
| 9-10 | 干净完成,且有可见验证 |

**副分**:efficiency 0-3(绕路/浪费)、grounded 0-3(动作是否贴合画面)、
termination 0-3(停得对不对)、confidence 0-2(判官对自己的信心)。

**三种问卷(rubric)**
| 版本 | 差异 | 状态 |
|---|---|---|
| v1 | 直接给 0-10,提示词简短 | **冻结基线**,默认值,复跑逐字节一致 |
| v2 | 标号帧、"截图压倒自述"规则、XML 围栏、temp 0 | A/B 对照用,Opus 卷收尾后退役 |
| v2req | v2 + **先拆 requirement 再打分** | **生产问卷** |

**v2req 的 requirement 清单(每条要求一行):**
- `id` / `text` / `critical`(缺它任务即失败);
- `status` 六档:`satisfied` `mostly_satisfied` `partial` `weak_evidence` `not_satisfied` `unverifiable`;
- `evidence_steps` / `evidence_frames`:必须引用**真实存在**的步号与帧号;
- 脚本侧派生:
  - `j_derived` = 10 × Σ(权重×分值)/Σ权重,critical 权重 2,**unverifiable 不计入分母**(不当 0 分);
  - status→分值映射:satisfied 1.0 / mostly .75 / partial .5 / weak .25 / not_satisfied 0;
  - `j_score_gap` = 自由分 − 推导分(自一致探针);
  - `j_evidence_violations` = 引用了不存在的步/帧的次数(幻觉计数,不信任只记录)。

**生成参数**:temperature 0(两侧均钉死);Anthropic 侧 thinking 关闭 + 强制工具;
本地 Qwen 侧无工具通道,v2* 自动换"只回一个 JSON"契约,`--effort` 默认 low。
**参数政策**:Qwen 判官 **不得**调到 medium(实测掉 AUC,见 §5)。

## 3 步级判官(stepaudit)

**输入**:任务原文 + **动作前截图** + 该步 think(截断 1500 字)+ 执行的动作 + **动作后截图**。
后帧只用于判断动作结果,不得视为当时可见的决策依据。

**输出**:`action_grounded` 0-2、`outcome_intended` 0-2、`necessary` 0-2、
`is_recovery` bool、`lucky` bool、note。

**取样分层**:`--targets`(任意 jsonl 指定步,如 think 隔离清单)、
`--strata terminal`(每条 pass 轨迹的收尾步)、`recovery`(identical-run 逃逸点)。

## 4 仲裁(arb)

**触发规则**(自动从判官结果选分歧集):
| 标签 | 条件 |
|---|---|
| `fp` | checker 判败 ∧ (Qwen ≥8 或 Opus ≥7) |
| `fn` | checker 判过 ∧ 任一判官 ≤5 |
| `duel` | 两判官分差 ≥4 |
| `target` | `--targets` 指定(如 tier2 复核) |

**四值裁决**:`checker_right_judge_fooled` / `checker_bug_lenient` /
`checker_bug_strict` / `ambiguous`;附 `a_confidence` 0-2、
`what_checker_verifies`、`judge_miss`、`checker_flaw`、`decisive_evidence`。

**两种协议**
| | v1(冻结) | v2 |
|---|---|---|
| 调用次数 | 1 | 2 |
| checker 判决 | 一开始就给 | **阶段 A 不给,阶段 B 才给** |
| 判官批语 | 一开始就给 | 同上 |
| checker 代码上限 | 4000 字符(**静默截断**) | 12000,截断时记 `config_truncated` |
| 终局 3 步 think | 只有 90 字摘要 | **完整原文**(≤3000 字/步) |
| 额外字段 | — | `reversal_reason`(裁决与自身阶段 A 预测相反时必填)、`what_would_settle_it` |

**阶段 A(独立体检)输出**:逐条列出 checker 到底验了什么 ×
{`required`/`implied`/`not_required`(任务原文是否要求)} ×
{`satisfied`/`not_satisfied`/`cannot_tell`(画面证据)},外加
`missing_checks`(任务要求但 checker 没验的)与 `predicted_outcome`。
阶段 A 的复述可与代码机器对照,是仲裁自身的可验证锚点。

**模型**:Opus 5 + extended thinking(仲裁是唯一开思考的环节)。

## 5 判官族与配置对照(v11-100 同卷,n=100)

| 配置 | AUC | fail 中位 | 备注 |
|---|---|---|---|
| Qwen3.8-27B v1 + low | **.774** | 8 | 本地判官最优,生产用 |
| Qwen v2 + low | .759 | 8 | 问卷措辞对弱判官无效 |
| Qwen v2 + **medium** | .698 | 9 | **想得多→自我说服,禁用** |
| Opus 5 v1(不开 think) | .763 | 5 | 刻度舒展,更好用 |
| Opus 5 v1 @ v11-500(n=399) | .771 | 7 | 跨池稳定 |

两判官逐条相关 r = 0.810;n=100 噪声带 ±.03-.05。

## 6 已知结论(截至 2026-08-17)

- **自由分不能分层**:pass 轨迹 137/181 都打 9;分层必须靠 `j_derived` 与 status 标记。
- **fail 分布双峰**:低段(0-2)= 一眼可见的失败;高段(8-10,占 63%)= 冤案富矿。
- **checker 有 bug,且几乎全是"过严"**:v11-100 仲裁 23 条 → 10 冤案 / 0 过松;
  v11-500 首批 35 条 → 12 冤案。抽查 3/3 由人读代码坐实。
- **判官怀疑 pass 轨迹时,6/6 全是判官错**(排序算错、误读语义)。
- **cap-2048 断崖**:>2k think 的步弱步率 41%(Qwen)/25%(Opus),1k-2k 带 0%。
- **`ambiguous` 在 v1 协议下 0/58 次使用**——疑似提示词逼得过于果断,v2 给出使用条件。

## 7 已知缺口(未修)

- 轨迹级刻度**未提及重试/自我纠错**:重试只被 efficiency 隐式惩罚,
  completion 如何处理由模型自由发挥;拟加一句刻度 + `had_recovery` 字段,
  **只从下一池生效**(不回改在跑的卷)。
- 判官只看 10 帧、90 字 think 摘要——保存动作等瞬时状态可能落在采样缝隙。
- 关键帧仍是均匀采样,未做感知差分/事件对齐。
- 仲裁未在 held-out 集上验证,现有信心来自 3/3 人读代码抽查。
- 无重复运行一致性数字(temp 0 理论上确定,未实测)。
- 判官读的截图来自 rollout 目录(未经 build 处理),**不受 slug 冲突事故影响**;
  该事故只污染 SFT 语料的图片路径(`SFT_DATA.md` 事故章)。
