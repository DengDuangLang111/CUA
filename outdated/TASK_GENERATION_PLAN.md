> **SUPERSEDED(2026-08-15 收编)**:v7 时代的方案记录。现行设计看 `TASKGEN_PIPELINE.md`,
> 操作看 `RUNBOOK.md`,结果与决策看 `EXPERIMENTS.md`。本文只作历史。

# 新一批 OSWorld 任务生成 —— 方案记录

> 创建：2026-08-07（America/Los_Angeles）｜最后更新：2026-08-08
> 状态：**管道已闭环**（生成 → 校验 → 素材/gold 构建 → 编译 → VM 实跑 → 判分，全链路跑通一次）。
> 现在的工作是**质量与覆盖**，不是打通。
> 本文只记录**决策和依据**，不记录尚未验证的结果。

---

## 一句话目标

用 Claude API 生成一批**比官方 OSWorld-Verified 更难**的任务，能直接回填进 OSWorld 环境跑出轨迹，
最终产出约 **100 条 SFT 训练轨迹**；同时把「跨应用数量」做成可统计的受控变量。

---

## 当前状态与下一步（2026-08-08）

管道已经闭环一次（§9.8）。**打通不再是问题，剩下的全部是"生成出来的任务够不够好"**。
按用户 2026-08-08 的口径，现在要解决的是五类问题，逐条对应到具体动作：

| 类别 | 现状 | 要做什么 | 状态 |
|---|---|---|---|
| **任务种类** | 新增 `operation`（判系统状态）与 `relational`（判方向）两种 gold 形态，六个方向映射全部实测（§9.11） | 探针的 **VM 初始态实跑**（静态约束已做，动态未做） | 🟢 大部分 |
| **多样性** | 主应用/主产物/步数带轮转已落地并**实测联合分布**：每个应用都覆盖三个步数带、五种 app_count、全部原生产物（§9.10 步数带锁死已修） | variant 机制（策略 B）—— 按拍板顺序排在种类之后 | 🟡 待 variant |
| **格式** | click-center 按域门控、LibreOffice 预先 `open`、`LAUNCH["files"]` 去掉失效 flag | `download` 步官方 278 次我们 0 次（**有意差异**，见 §9.9 末） | 🟢 已对齐 |
| **输出（判分）** | 修掉 6 条"正确答案判 0"和 2 条"错答案判 1"的路径；正例对照 4/4 判 1.0（§9.10） | 真实 VM 里注入 gold 验 getter 层 + postconfig 时序 | 🟡 差 getter 层 |
| **对齐官方** | `expected_shape` 按 metric 决定 getter 形状；`.pth` 改惰性注册（不再污染纯净 worktree 的溯源） | 真实网站任务（④，已决定但未做） | 🟡 差真实网站 |

### 执行顺序（2026-08-08 用户拍板）

```
① 补任务种类  →  ② variant 机制（策略 B）  →  ③ 铺量并量真实通过率
```

**为什么是这个顺序**：variant 是"同一逻辑换规模/条件/格式"的放大器。目前 100% 是 derived
一种形态，先做 variant 等于把同一种模式复制三遍——正是上一批变体指令 TF-IDF 相似度 0.987
的成因。先把形态补齐，variant 才有东西可放大。

**任务形态配比（拍板）**：

| 形态 | 占比 | 判分方式 | 新增代码量 |
|---|---:|---|---|
| **derived** 算文件对拍 | **60%** | `vm_file` + 冻结 gold 文件 | 已有 |
| **operation** 判系统状态 | **30%** | `vm_command_line` + `rule`，官方 getter/metric 全有 | **零** |
| **relational** 判方向 | **10%** | 与原始输入比较（更暗 + 结构相似），**无 gold 文件** | 词表 + prompt 分支 |

**family / variant 结构保留**（60–70 family × 2–3 variant），但在三种形态各自内部做变体，
差异维度由调用参数指定，不给模型自由发挥（策略 B，§9.7 末）。

---

**本次已落地的两项**（详见 §9.9）：

1. **click-center 按域补齐** —— 但**不是**原先以为的"官方几乎每个任务都有"。
   实测 369 个官方任务只有 **41 个**有这一步，且高度集中：`os` 19/24、`vlc` 14/17，
   而 chrome / calc / writer / gimp / thunderbird / vs_code **全域 0**。
   所以 emit 里按 domain 门控，只给 `os` / `vlc` 加，其余不加 —— 无条件加反而是偏离官方。
2. **`compare_table` 按 sheet 名选表** —— 首次闭环里 agent 在工作簿里多留了原始 sheet，
   `RI0`/`EI0` 按位置取表纯属碰运气。改成从构建好的 gold 文件读第一个 sheet 名，
   发 `RN<name>`/`EN<name>`。实测输出 `RNReorder`/`ENReorder`。

---

## 1. 已定的决策

| 项 | 决定 | 依据 |
|---|---|---|
| **用途** | SFT 训练数据，只收成功轨迹（rejection sampling） | 与上一批 100 条同一逻辑；不作为测试集，避免训练污染 |
| **难度方向** | ① 跨应用信息流转 ② 检索与推理 ③ 长程多阶段 | 拒答类暂缓（见 §6 风险） |
| **难度目标** | 单次通过率 20–25% | 锚点：Qwen3.6-27B 在官方 312 个任务上均分 46.62%（141 满分 / 163 零分 / 8 部分分） |
| **evaluator 策略** | 自由出题 → 生成后归并 → 砍长尾，预算 25–35 个函数 | 官方 369 任务用 111 个函数，其中 59% 只用一次，长尾是纯浪费 |
| **形状** | 60–70 family × 2–3 variant | 上一批 30 family × 8 variant，有效技能签名只有 15 个 |
| **variant 要求** | 变体之间必须有**实质差异**（数据规模 / 条件结构 / 文件格式），不只是换名字 | 上一批同 family 变体指令 TF-IDF 相似度 0.987 |
| **素材** | Claude 写场景与内容，`gold.impl` 算 gold；**构建期不注入任何噪声**（已推翻原方案，§9.4） | 见 §4 |
| **规模** | 先做 10 个垂直切片打通链路，量出真实通过率后再定总量（预估 180–200 个任务） | 100 个任务收不到 100 条轨迹 |
| **max_steps** | **100** | 官方是 50；长程方向需要更长预算 |
| **student 模型** | **Qwen3.5-9B** | 细节后定 |
| **evaluator 载体** | **独立包，独立运行**；产出任务 JSON 后再搬进 OSWorld 跑 | 避免像上一批那样把主仓库改脏、与上游持续冲突 |
| **生成用 LLM** | Claude，经 **ppapi.ai** 代理（US 专用 base url） | 已有 token，见 §5.6 |
| **轨迹交付** | **先做成 HTML**，格式对齐 OSWorld 原生输出 | 见 §5.7 |
| **跑批预算** | 3 并发实测可行（峰值 14.7 GiB / 19 GiB，无 OOM）。按 8 分钟/任务估：200 任务 × 3 次 ÷ 3 并发 ≈ **27 小时**，需跨 2 个 Slurm 作业（24h 上限） | 2026-08-08 实测 |

### 1.1 跨应用数量：按配额均衡生成

任务按「需要交互的 GUI 应用数量」分 5 档，**各档任务数近似相等**。

> **当前定位**：这是**生成配额约束**，不是受控实验。
> 均衡配额本身就能看到「应用数越多成功率越低」的**相关性趋势**；
> 想要**因果**结论需要配对设计，已暂缓，见 §1.2。

| 应用数 | 目标占比 | 官方 361 的对照 |
|---:|---:|---|
| 1 | ~20% | 269 个（74.5%） |
| 2 | ~20% | 65 个（18.0%） |
| 3 | ~20% | 23 个（6.4%） |
| 4 | ~20% | 3 个（0.8%） |
| 5 | ~20% | **0 个** |

注意官方在 4 应用上只有 3 个任务、5 应用完全没有，所以 4–5 档没有先例可抄，
必须自己设计并接受更高的失败率。

**「应用」的判定口径（已确认，写死）**：
指 agent 必须**打开并交互**的独立 GUI 应用。
- 计入：chrome / libreoffice_calc / libreoffice_writer / libreoffice_impress / gimp / vlc / thunderbird / vscode / 文件管理器 / 终端
- 不计入：文件格式（pdf、image 这类官方 `related_apps` 里出现过的伪应用）、
  仅作为素材被读取但无需打开的文件

不使用官方的 `related_apps` 字段做统计——它是作者手填的元数据，口径不一致
（混入了 `pdf` / `image` 这类非应用项）。本批次自行维护 `app_count` 字段。

### 1.2 配对组 —— ⏸ 暂缓，当前不做

> **决定（2026-08-08）：本阶段不做配对组，全部 200 个任务自由设计，
> 只保证 §1.1 的应用数配额均衡。**

**它原本是什么**：同一个业务逻辑，做成 1/2/3/4/5 应用五个版本，
控制住原子操作数与信息量，使工作量近似相等——这样成功率的下降
就只能归因于「跨了几个应用」，而不是「任务本来更重」。

**为什么暂缓**：

- 本批次主目标是 **SFT 训练数据**，不是发表因果结论。
  均衡配额已能给出相关性趋势，因果结论属于「知道更好」而非必需。
- 代价明确：75 个任务只覆盖 15 个业务逻辑，多样性偏窄
  （结构上接近 §6 批评过的「family × variant 通胀」）。
- 「工作量等价」这个约束很难在生成阶段真正保证，设计成本高。

**未来若要恢复**：它是一个**独立小实验**，不需要绑进主流程——
跑完主批次若发现应用数与成功率的相关性显著、想确认因果，
再补 15 个逻辑 × 5 档即可。

已用 workflow 起草了 15 个业务逻辑骨架，产出另行成文，不进本文档。
即使不做配对组，那些业务逻辑本身可以拆散并入自由组。

### 1.3 依赖结构：记录，不做平衡设计 ⏸

原计划做「应用数 × 串行/并行」二因子平衡设计，随 §1.2 一并暂缓。

**保留的部分**：每个任务仍要在 spec 里**记录** `dependency` 字段，
取值 `none`（单应用）/ `serial` / `parallel`，作为事后分析的元数据。

- **并行**：多个信息源各自独立，最后汇总。失败是局部的。
- **串行**：A 的输出是 B 的输入。失败会级联，几乎全 0。

对 SFT 两种都要：并行贡献「多源汇总」样本，串行贡献「长链推进」样本
（后者同时满足难度方向③长程多阶段）。生成时大致对半即可，不必严格配额。

---

## 2. 待定

| 议题 | 选项 | 状态 |
|---|---|---|
| 是否恢复拒答类 | | 暂缓 |

---

## 3. 检索任务的信息源 —— **已定：真实网站**

决策人：用户。已知代价见 §3.2，接受并将配置住宅代理。
**代价被接受后，gold 的写法必须相应改变——见 §3.5。**

### 3.1 官方的实际做法（实测数据，非推测）

对 361 个任务按**运行时**真正的网络依赖分类（排除仅出现在 `source` 元数据里的 URL）：

| 类别 | 任务数 | 占比 |
|---|---:|---:|
| 只从素材站（HuggingFace）下载文件 | 244 | 67.6% |
| 完全不联网 | 65 | 18.0% |
| **运行时访问真实站点** | **52** | **14.4%** |
| **在 config 里起本地 HTTP 服务** | **0** | **0%** |

官方**从不使用本地 HTTP 服务**。那 52 个真实站点任务打的是
Amazon / TripAdvisor / Delta / Apple / LinkedIn / Airbnb / Qatar Airways / Ticketek /
FlightAware / Google Scholar / Wikipedia 这类站点。

### 3.2 官方为此付出的代价（实测）

| 指标 | 访问真实站点的 52 个 | 其余 309 个 |
|---|---|---|
| 需要住宅代理（`proxy: true`） | **44 个（85%）** | 5 个 |
| `possibility_of_env_change` = medium/high | **6 个（全部）** | **0 个** |

**环境易变性完全由「是否访问真实站点」决定**——其余 309 个任务的
`possibility_of_env_change` 无一例外全是 `low`。

OSWorld-Verified 那轮 300+ 条社区反馈中，很大一部分正是网站改版、反爬、URL 变更导致的，
官方的修法是：更新解析函数、改模糊匹配、加代理、用等效站点替换被封的站点。

### 3.3 对本批次的硬约束

**四态离线门禁要求 gold 是确定的。** 真实站点的内容会变，gold 就不确定，
门禁 1（§5.1）根本无法执行——这不是偏好问题，是流程上的硬冲突。

其余考量：
- 本批次预计 200 任务 × 3 次 = **600 次运行**，真实站点在这个量级下遭遇改版/限流/封禁的概率很高
- 你们那 49 个 proxy 任务至今未跑（卡在 DataImpulse 凭据），说明真实站点任务
  在当前基础设施上本来就跑不通
- 上一批已有 **82 个任务**使用本地 `http.server`，基础设施现成

### 3.4 代理配置

- 模板：`evaluation_examples/settings/proxy/dataimpulse.json`
- 需填：`username` / `password`（host `gw.dataimpulse.com` 端口 `823` 已预置）
- 机制：`_proxy_setup`（`controllers/setup.py:628`）从全局代理池取一个，做系统级代理；
  Chrome 启动时自动追加 `--proxy-server=http://127.0.0.1:18888`
- 任务侧只需在 JSON 里标 `"proxy": true`

### 3.5 走真实网站后，gold 必须改成「判状态」而非「判数据」

这是硬性推论，不是偏好。真实站点的**内容**会变，但**任务定义决定的状态**不会变。

官方 52 个真实站点任务的实测证据：

| | 真实站点 52 个 | 其余 309 个 |
|---|---|---|
| `expected` 用 `rule` | **52 个（100%）** | 120 个 |
| `expected` 用 `cloud_file` 冻结 | 8 个 | 193 个 |
| `result` 主力 getter | 浏览器状态（`active_tab_html_parse` 12 / `active_url_from_accessTree` 12 / `active_tab_url_parse` 7 / `active_tab_url_and_body_text` 7 / `active_tab_info` 5） | `vm_file` 236 |
| 主力 func | `check_direct_json_object` 21 / `is_expected_url_pattern_match` 11 / `check_url_and_content_include` 7 | `compare_table` 59 / `compare_pptx_files` 49 |

**官方的三板斧（本批次照抄）**：

1. **判到达状态，不判网站数据。** 例：查航班任务的 gold 不是价格或航班号，
   而是「页面上出发=JFK、到达=ORD、日期=明天」——这三个事实由任务定义决定，网站怎么变都不影响。
2. **正则 + 大小写不敏感 + 子串包含，不用精确相等。**
   例：`"expected": ["(?i)ticket-delivery(?:-faqs)?"]` 只匹配 URL slug。
3. **`conj: "or"` 并列多套规则，覆盖不同的合法达成路径。**
   例：Nike 筛选任务给两套规则——一套查 URL 含 women/nike/jerseys，
   一套只查页面正文含这些词——因为站点可能用 URL 筛也可能用 JS 筛。

第四条辅助手段：**`rule_relativeTime`**（官方用了 13 次）处理时间相关任务，
"明天""下周一"在评测时刻才解析成具体日期，gold 永不过期。

### 3.6 对四态门禁的影响

「判状态」型 gold 是确定的，四态门禁仍然可做，只是四态的构造方式变了：

| 状态 | 文件对拍型任务 | 判状态型任务 |
|---|---|---|
| 初始 = 0 | 未动的模板文件 | 初始标签页 / 空浏览器状态 |
| gold = 1 | gold 文件 | 人工到达一次目标状态，抓取其 URL+正文快照 |
| 近似错例 = 0 | 改错一个单元格 | 错的筛选条件 / 缺一个关键词的 URL |
| 独立正确解 = 1 | 语义相同、字节不同的文件 | 另一条合法路径到达的状态（对应 `conj: "or"` 的第二套规则） |

**配对组（75 个做因果统计的）额外要求**：必须能在数月内重复跑出一致结果。
因此配对组只允许「判状态」型 gold，禁止冻结网页内容。

---

## 4. 素材真实感的做法

**分工原则**：

```
Claude  →  场景、人名、公司、字段名、文档措辞、邮件语气、原始数据行
Python  →  从 Claude 给的同一份原始数据，重新算出 gold
```

**绝不让 Claude 给答案。** 它可以给一份 30 行的付款表，但"哪些逾期未付、按金额降序"必须由
Python 从同一份 rows 跑确定性实现算出。gold 就是"正确"的定义，LLM 算错了发现不了。

**噪声只加输入侧**：

| 加在输入（提高任务难度） | 不加在输出（保持 evaluator 好写） |
|---|---|
| 合并单元格标题行、空行分隔、脚注行 | 输出模板保持干净表头 + 数据区 |
| 日期格式不统一（`2026-07-03` / `Jul 3, 2026`） | 输出要求统一格式 |
| 金额带千分位与货币符号 | 输出要求纯数值 |
| 有整列为空、列名带空格或缩写 | 输出列固定 |
| 邮件带转发链、签名档、抄送 | — |
| 目录里混入 README 和无关文件 | — |

---

## 4.5 gold 编写规范（归纳自官方 361 个任务）

官方**没有**明文的 gold 编写规范文档——`evaluation_examples/README.md` 只有 24 行字段说明。
以下全部是从 361 个任务的实际写法里统计归纳的。

### 4.5.1 三种写法

| 写法 | 数量 | 占比 | 适用 |
|---|---:|---:|---|
| ① 冻结金标文件（`cloud_file`） | 171 | 47.4% | 产物是文件，答案唯一 |
| ② 内联规则（`rule` / `rule_relativeTime`） | 144 | 39.9% | 答案是状态、字符串、集合 |
| ③ 无 `expected`（判据写死在 func 里） | 37 | 10.2% | `infeasible` 27 个 + 10 个自包含判据 |
| ④ 其他特殊 getter | 9 | 2.5% | `pdf_from_url`、`info_from_website` 等 |

### 4.5.2 冻结金标文件的约定

- **命名**：`dest` 里带 gold 标记——`Gold` 93 / `gold` 75 / `gt` 27 / 无标记 22
- **托管路径**：`huggingface.co/datasets/xlangai/ubuntu_osworld_file_cache/resolve/main/<domain>/<task_id>/<filename>`
- **⚠️ 硬性要求**：`expected.dest` 必须与 `result.dest` **不同名**。
  两个 getter 都往同一个 `env.cache_dir` 落地，同名会互相覆盖，
  变成 gold 跟自己比，**永远满分**。

### 4.5.3 容差由 `options` 控制，不由 func 名控制 —— 最该学的一条

`options` 是原样透传给 metric 的 kwargs。官方用它把「哪些维度算数」做成开关：

| options 键 | 出现次数 | 作用 |
|---|---:|---|
| `rules` | 60 | 内联规则体 |
| `examine_shape` | 18 | pptx 比对是否检查形状 |
| `ignore_blanks` | 9 | 忽略空白差异 |
| `strip_whitespace` | 4 | 去首尾空格 |
| `examine_run_count` / `examine_alignment` / `examine_font_size` / `examine_bullets` | 各 2–3 | docx/pptx 逐维度开关 |
| `ignore_case` | 2 | 大小写不敏感 |
| `ssim_threshold` | 2 | 图像相似度阈值 |
| `left_tolerance_emu` | 1 | 位置容差 |

**同一个 gold 文件 + 不同 options = 不同难度**。
例：同一份 gold pptx，`examine_shape: false` 就只比文字不比形状。

上一批的 evaluator 全是硬编码严格比对、没有维度开关——这是必须改的。

### 4.5.4 多解的两种表达

1. **别名数组**：`rule` 的 expected 里，每个位置可以是字符串或字符串数组。
   例（`compare_conference_city_in_order`）：
   `["Montreal", "Montréal"]`、`["New York", "New York City", "NYC"]`、`["Lake Tahoe", "Stateline"]`
   实现是归一化后做子串包含匹配。
2. **`conj: "or"` 并列多套 metric**：官方多 metric 任务里 `or`(30) 比 `and`(24) 还多。

上一批 60 个多 metric 任务**全是 `and`、零别名**，会把合法的另一种做法判成 0。必须改。

---

## 5. 流水线

```
1  generate_specs.py    ← Claude API 唯一介入点，tool-use 强 schema，输出结构化 spec
2  build_assets.py      ← 纯代码：落地初始文件 + 算 gold 文件
3  build_tasks.py       ← 纯代码：spec + 资产路径 → OSWorld task JSON
4  validate_static.py   ← 门禁 1（离线四态）
5  smoke_live.py        ← 门禁 2（VM 内注入）
6  calibrate.py         ← 每任务跑 N≥3 次，做难度分层与筛选
```

LLM 只写第 1 步，其余 95% 是确定性代码。

### 5.1 门禁 1：离线四态（每个任务必须四条全过）

| 输入 | 期望分数 | 验证了什么 |
|---|---:|---|
| 初始状态（未动的模板/输入文件） | **0.0** | 什么都不做拿不到分 |
| gold 产物 | **1.0** | 正确做法拿满分 |
| **近似错例**（改对 90%、错一个单元格/字段/像素） | **0.0** | evaluator 不过松 |
| **独立生成的正确解**（语义相同、字节不同） | **1.0** | evaluator 不过严，也不是在比哈希 |

后两条是上一批**缺失**的，必须补。上一批的实测：
- 51.4% 的任务其 evaluator 从未被近似错例测试过
- 17.1% 的任务，把 evaluator 换成「只查文件是否存在」的假货仍能通过自身门禁

### 5.2 门禁 2：VM 内注入

在真实 VM 里 `reset(task)` → 注入 gold 状态 → `evaluate()` 必须 == 1.0；
再注入近似错例 → 必须 == 0.0。

**不能同义反复。** 上一批的做法是「上传 output_gold.xlsx，再拿它和 output_gold.xlsx 比」，
恒等于 1.0，只验证了管道通不通，没验证 evaluator 判别力。

### 5.3 隔离要求

- ID 用 `uuid5` + 本批专属 NAMESPACE，与官方 369 个 UUID 零交集
- 任务定义放独立目录，**不写进 `evaluation_examples/`**
- 结果目录独立，不与官方 `results/` 混
- 每个任务带 `"official_benchmark_task": false` 和 `training-only` 标签
- 指令与官方 369 条的 TF-IDF cosine < 0.7（上一批实测最高 0.596，达标）

### 5.3b spec 与 task JSON 是两层，不要混为一谈

```
Claude ──> spec ──[taskgen/emit/osworld.py]──> OSWorld task JSON ──> OSWorld runner
          中间态                                最终产物，结构 100% 官方
```

**已实测验证**（2026-08-08）：编译出的 task JSON 与官方样例顶层键完全一致，
11 个键一个不多一个不少；spec 独有字段（`near_miss` / `traps` / `gold.rule` /
`assets[].content` / `difficulty_axes` …）**一个都没泄漏**进去。
OSWorld runner 无需任何改动即可消费。

| spec 字段 | 谁消费 | 进 task JSON 吗 |
|---|---|---|
| `assets[].content` | `assets/` 构建素材文件 | ❌ 变成文件 |
| `gold.rule` | `assets/` 算出 gold 文件 | ❌ 变成 gold 文件 |
| `evaluator_hint.near_miss` / `independent_solution` | `gates/` 四态门禁 | ❌ |
| `traps` | 人工评审 | ❌ |
| `instruction` / `apps` / `gold.artifact_path` | — | ✅ |

**为什么不让 Claude 直接产 task JSON**：`config[].type` 的 21 种动作参数名必须精确匹配
`_<type>_setup` 签名；`evaluator.func` 必须是已注册的函数名；`expected.path` 要指向
一个尚不存在的 gold 文件且路径约定必须与构建脚本一致；`postconfig` 的窗口标题必须精确等于
`<文件名> - LibreOffice Calc`（拼错的后果是**做对了也判 0**）。
这些都是有唯一正确答案的机械工作，Python 生成远比 LLM 可靠。

分工：**Claude 出创意（场景、数据、规则），Python 出机械（路径、函数名、窗口标题、setup 序列）。**

### 5.3c evaluator 选择：对齐官方做法，长尾可见但不拦路

`taskgen/evaluators/registry.py` 维护一张「产物类型 → 官方 metric → 它已能判的维度」表。
Claude 只声明「我要判 xlsx 的值和顺序」，不需要知道 `compare_table` 这个名字。

**曾经的做法（已废弃）**：表里没有的组合，编译直接失败，逼人当场归并。
实测编译损耗 45%（11 个 spec 只出 6 个），且拦掉的大多是「现有函数其实能判、只是覆盖集写窄了」。

**现在的做法（对齐官方）**：编译**从不失败**。没有官方 metric 覆盖时，
分配一个 taskgen 专属名字（`tg_<产物>_<维度缩写>`，确定性生成，重编译不漂移），
并登记进 `out/evaluators_needed.json`：

```
evaluators: 11 tasks -> 8 reuse an official metric, 3 need a new one
distinct new functions required: 3
  tg_pptx_contains_order_structure_values     1 task
  tg_docx_contains_order_structure            1 task
  tg_pptx_order_structure_tolerance_values    1 task
```

这与 §1 定的 evaluator 策略一致：**自由出题 → 生成后归并 → 砍长尾**，归并是**事后**动作。

官方的参照：369 个任务用了 118 个 metric，其中 **71 个只用过一次（60%）**，
长尾形如 `check_italic_font_size_14`、`check_green_background`、`check_qt_bgcone`
（字号和颜色写死在函数名里）。官方不设闸门也不做归并；我们保留同样的自由度，
但把长尾**记录下来**——归并不了看不见的东西。

### 5.3d 打分语义：保持二元为主，只在官方也用连续值的地方用连续值

**已核实**：官方的部分分不来自「多阶段各给一部分」，而来自两类**单个** metric 本身返回小数：

| 来源 | 例子 |
|---|---|
| 逐项比例 | `compare_pdfs` = `score/len(pages)`、`compare_docx_paper_records` = `total/len(gold_refs)` |
| 相似度 | `compare_images`（逐图 SSIM 平均）、`fuzzy_match` = `fuzz.ratio/100`、`compare_videos` |

`desktop_env.py:502` 的短路机制决定了：`conj="and"` 下**任一 metric 恰为 0 就直接返回 0**，
所以「多个二元 metric 取平均」并不会产生部分分。全 361 个任务里只有 25 个用 `conj="and"` 且 >1 metric，
它们实际表现仍是二元的。

312 次实跑里的 8 个部分分，全部来自上表两类，无一例外：

```
0.0286  evaluate_presentation_fill_to_rgb_distance   0.6078  compare_docx_files
0.1111  compare_references_gain                      0.7466 / 0.7909 / 0.9030  compare_images
0.2787  compare_images                               0.9977  compare_pdfs ×4 (conj=or 取 max)
```

**本批次的决定**：照抄这个语义。不发明「阶段检查点」式的部分分。
逐项比例和相似度这两类在天然适用时照用（图像、多页 PDF、多条记录），其余保持二元。

理由：对 SFT 而言三种方案没有区别——rejection sampling 只留 `score == 1.0`，
部分分轨迹含错误动作，本来就不能用。而偏离官方语义会让分数无法与官方结果比较。

### 5.3f 实测教训：tool-use 的 enum 不被强制

**曾经的判断（已被推翻）**：schema 作为 `input_schema` 传给 API，模型输出必须符合，
是硬约束而非 prompt 里的建议。

**实测反例**（2026-08-08）：某批次产出 `assets[].kind = "html"`，
而 `html` 当时不在 `ASSET_KINDS` 枚举里。也就是说**嵌套数组项里的 enum 不被强制**。

**修正**：`validate.py` 必须自己校验全部枚举成员资格，不能假设 schema 兜住了。
已补上 apps / dependency / difficulty_axes / asset kind / asset role /
input_noise / gold.kind / gold.artifact_type / judgment_dims 九处检查。

同时补了一条：`gold.kind=derived` 必须有 `gold.impl`。

### 5.3e gold.rule 的执行：Claude 写 Python，AST 白名单 + 沙箱

`gold.rule` 是自然语言，必须变成可执行代码才能算出 gold 文件。两条路：

- 受限 DSL 解释器 —— 安全但表达力不足，覆盖不住检索推理/跨应用这类杂形态
- **让 Claude 写一段 Python 函数** ← 采用

与官方一致：官方每个任务也是写函数。安全措施照抄官方 `check_python_clamp_function`
（`metrics/generated_tasks.py:447`，全套里质量最高的一个 evaluator）的做法：

- **只在本机构建阶段执行**，不进 VM、不联网
- **AST 白名单**：限制可用节点与调用，禁止 `import` 白名单外的库
  （允许 `openpyxl / python-docx / python-pptx / PIL / re / datetime / decimal / csv / json`）
- 执行后用**四态门禁**验证结果（初始=0 / gold=1 / 近似错例=0 / 独立正确解=1）

**沙箱实测**（`taskgen/assets/sandbox.py`）：`import os` / `open()` / dunder 逃逸 /
`eval` / 缺 `compute` / 参数数不对 / 死循环 —— 七种攻击模式全部拦下，正常代码正常执行。

**⚠️ 已知漏洞（重要）**：沙箱只保证代码**能跑**，不保证它实现的是 `gold.rule` 说的那件事。
更糟的是 `compute()` 一个函数同时返回 gold / near_miss / independent，
若它误解了规则，三个产物会**一致地错**，四态门禁照样全绿——
因为门禁验证的是**评测器**，不是**指令↔实现的一致性**。
`independent_solution` 本来该兜这个，但它与 gold 同源，共享同一个 bug。

要堵住需要**独立复算**：第二次 LLM 调用只给 `gold.rule` 和素材，独立实现一遍再对拍。
成本是每任务多一次调用。**尚未决定是否采用。**

### 5.3g 依赖策略：能不依赖就不依赖

WSL 构建机上没有 pip / uv / virtualenv / python3-venv，装包需要 sudo。
因此 PDF 素材改用自带的 `taskgen/assets/minipdf.py`（纯标准库，base-14 Helvetica，
无需嵌入字体），去掉了 reportlab 依赖。已验证 pdfplumber 能正确抽回文本。

当前 taskgen 的运行依赖只剩 `openpyxl / python-docx / python-pptx / Pillow`，
这四个 OSWorld 的 venv 里都有，可直接复用 `/mnt/d/research/OSWorld/.venv/bin/python`。

### 5.4 evaluator 独立包（已定）

不再往 `desktop_env/evaluators/` 里塞文件。改成独立包，自带运行入口：

```
osworld-taskgen/                 ← 独立仓库/包，与 OSWorld 解耦
├── .env / .env.example          凭据（.env 已 gitignore）
├── examples/                    样例 spec + 配对组产出
├── taskgen/
│   ├── specs/   ✅ vocab.py schema.py validate.py   契约与校验
│   ├── llm/     ✅ check.py                          API 连通性
│   ├── emit/    ✅ osworld.py                        spec → 官方格式 task JSON
│   ├── viz/     ✅ traj_html.py                      轨迹 → 单文件 HTML
│   ├── assets/  ⬜                                   素材与 gold 构建
│   └── gates/   ⬜                                   四态离线门禁
└── out/                         生成的 examples/ + manifest.json + 素材
```

代码一律用英文（注释、docstring、输出文案），源文件保持纯 ASCII。

交付方式：把 `out/` 整体搬进 OSWorld，用 `--test_config_base_dir` 指过去跑。

**唯一需要碰 OSWorld 的地方**：新 metric 必须能被 `getattr(metrics, func)` 找到。
两条路，实现时二选一：

1. 在 OSWorld 侧加**一个** shim 模块，动态 import 本包的 evaluators 并注册——只改一次，之后新增 evaluator 不再动 OSWorld
2. 或让本包提供一个安装脚本，把 evaluators 复制进去并追加 `__init__.py` 的 import（等同上一批做法，不推荐）

倾向方案 1。

### 5.4b 生成用 LLM 接入（已打通，2026-08-08 实测）

```
BASE_URL   https://app-us.ppapi.ai      ← US 节点；不要加 /anthropic 前缀
协议       Anthropic Messages，POST {BASE}/v1/messages
认证头     x-api-key: <token>            ← 实测可用（Bearer 未测，x-api-key 第一个就通）
模型       claude-opus-4-6
网关       New API 类型（错误体 "type":"new_api_error"），同 host 也提供
           OpenAI 协议 /v1/chat/completions
```

因为是标准 Anthropic 协议，官方 `anthropic` SDK 直接改 `base_url` 即可，无需手写 HTTP：

```python
from anthropic import Anthropic
client = Anthropic(api_key=os.environ["PPAPI_API_KEY"],
                   base_url=os.environ["PPAPI_BASE_URL"])
```

响应 usage 里带 `cache_creation_input_tokens` / `cache_read_input_tokens`，
说明网关透传了 prompt caching —— 生成器里把长的公共前缀（环境说明、
evaluator 清单、口径定义）放在前面并标记缓存，可显著降本。

**凭据位置**：`osworld-taskgen/.env`（已被 `.gitignore` 排除）。
模板见 `.env.example`。验证：`python3 -m taskgen.llm.check`（只打印掩码，不打印明文）。

### 5.5 轨迹交付：先出 HTML

**OSWorld 原生输出格式**（`lib_run_single.py:45-59`），每个任务一个目录：

```
<result_dir>/<domain>/<task_id>/
├── traj.jsonl          每步一行 JSON
├── step_<N>_<ts>.png   每步截图
├── recording.mp4       全程录屏
├── result.txt          最终分数（单行浮点）
└── runtime.log
```

`traj.jsonl` 每行的字段：

```json
{
  "step_num": 1,
  "action_timestamp": "20260808@002631587992",
  "action": "<pyautogui 代码字符串>",
  "response": "<模型原始回复，含 thinking>",
  "reward": 0,
  "done": false,
  "info": {},
  "screenshot_file": "step_1_20260808@002631587992.png"
}
```

HTML 渲染器要做的：读一个任务目录 → 输出单文件 HTML，逐步展示
**截图 + 模型 thinking/response + 实际执行的 action**，顶部放 instruction 与最终分数。
截图用 data URI 内嵌，保证单文件可分发。

后续 SFT 样本转换在此基础上做（thinking 留不留、截图如何编码、上下文如何截断，
受 §1 里 Qwen3.5-9B 的上下文预算约束）。

---

## 6. 从上一批学到的教训（必须避免重犯）

依据：`OSWorld/synthetic_tasks/` 280 个候选任务的完整审计。

1. **覆盖坍缩**：设计了 30 个 family，只有 15 个产出过轨迹。另 15 个每个只试 1–3 次就被放弃，
   而它们恰好是 Calc / Writer / Thunderbird 密集的族。
   → 新批次：每个 family 必须跑满 N 次才能判定去留，不允许 adaptive 策略静默淘汰。
2. **接受率不是难度指标**：上一批 59.6% 的任务级接受率是贪心利用的产物——
   成功的 family 跑满 8 次，失败的试 1–2 次就停。
3. **evaluator 判别力未验证**：见 §5.1。
4. **variant 通胀**：280 个候选，指令去重（cosine 0.9）后只剩 46 条。
5. **`conj: "or"` 完全没用过**：上一批 60 个多 metric 任务全是 `and`，
   会把合法的另一种做法判成 0。官方多 metric 任务里 `or`(30) 比 `and`(24) 还多。
6. **拒答类的毒化风险**：若生成了「以为不可行、实际可行」的任务，会训练模型拒绝能做的事，
   且事后极难发现。恢复该类别前必须先写「核验不可行理由」的脚本
   （如去 VM 里列出 GIMP 全部可用主题、VS Code 全部 settings key）。

---

## 7. 里程碑

- [x] **M0a** 确定依赖结构 → 二因子设计（§1.3）
- [x] **M0b** 确定检索信息源 → **真实网站**（§3），需配置住宅代理
- [x] **M0d** 打通 ppapi.ai 的 Claude 调用 —— `https://app-us.ppapi.ai` + `x-api-key`，
      模型 `claude-opus-4-6`，实测 200（§5.4b）
- [ ] **M0e** 轨迹 HTML 渲染器：读一个 OSWorld 任务目录 → 单文件 HTML
      （素材现成：上一批 100 条轨迹在 WSL 上）
- [x] **M0e** 轨迹 HTML 渲染器 —— `osworld-taskgen/taskgen/viz/traj_html.py`，已用真实轨迹验证
- [x] **M1a** spec JSON Schema + 受控词表 + 语义校验器（`taskgen/specs/`）
- [x] **M1c** spec → OSWorld task JSON 编译器（`taskgen/emit/osworld.py`），
      已验证输出结构与官方 100% 一致
- [x] **M1b** Claude 生成器（接 ppapi，prompt caching，校验失败自动重试）
      —— 三批实测，最新一批 4 个 spec 零错误
- [ ] **M1d** `assets/` 素材与 gold 构建（**当前唯一阻塞项**）
- [ ] **M1e** `gates/` 四态门禁
- [ ] **M1f** 三个遗留问题：新 evaluator 的实现与注册 shim；
      `gold.kind=state` 的 result getter 选择（现在一刀切 `active_tab_info`，
      官方那 52 个真实站点任务用了 6 种）；素材从 `out/` 搬到 OSWorld 仓库根的步骤
- [ ] ~~**M1b** 配对组 15 个业务逻辑骨架~~ —— ⏸ 暂缓（§1.2），workflow 产出另行成文
- [ ] **M2** 10 个任务垂直切片：跨 1–5 应用各 2 个，走完全链路
- [ ] **M3** 量出三个未知数：单次通过率、每任务 evaluator 代码量、单次运行耗时
- [ ] **M4** 据此定总量，铺开生成
- [ ] **M5** 跑批 + 难度分层 + SFT 轨迹打包（HTML → 训练样本）

### 待决（对账后仍开放）

- 轨迹 → SFT 样本的具体格式（thinking 留不留、截图编码、上下文截断），
  受 Qwen3.5-9B 上下文预算约束
- 是否采纳失败模式分析（105 个「DONE 但判 0」vs 58 个「卡住」）来指导 family 设计

### 已暂缓（不在当前路径上）

- 配对组 / 二因子平衡设计（§1.2、§1.3）
- 拒答（infeasible）类任务（§2）

---

## 8. 相关文件

- 上一批审计对象：`OSWorld/synthetic_tasks/`（280 候选 / 100 条已接受轨迹，未进 git）
- 官方纯净源码：`OSWorld-upstream/`（worktree @ `091f5ef1`，即 campaign 所用 commit）
- 本地改动过的 OSWorld：`OSWorld/`（@ `87df18ff`，落后上游 5 个提交）
- 实验现状：`OSWORLD_EXPERIMENT_STATUS.md`

---

## 9. 决策与反转记录

按时间顺序记录**改过主意的地方**和依据。后续会话读这一节就能知道为什么现在长这样，
不必重走一遍弯路。

| # | 议题 | 最初方案 | 现在 | 反转依据 |
|---|---|---|---|---|
| 1 | 本批用途 | 构造新**测试集** | **SFT 训练数据** | 用户澄清；两者筛选逻辑相反 |
| 2 | 配对组（同逻辑 × 1–5 应用） | 做，75 个任务 | **⏸ 暂缓** | workflow 起草 15 个逻辑后审查发现：「工作量等价」纸面成立实质不成立，高应用档被系统性低估（v5 实际 30+ 步却记 17）。见 PAIRED_GROUP_EXPERIMENT.md |
| 3 | 二因子平衡设计 | 做 | **⏸ 随 #2 暂缓** | `dependency` 保留为记录字段 |
| 4 | 拒答（infeasible）类 | 做，性价比最高 | **⏸ 暂缓** | 用户判断：生成「以为不可行、实际可行」的任务会毒化 SFT 且事后难查 |
| 5 | 检索信息源 | 建议本地 HTTP（可复现） | **真实网站** | 用户决定。代价已知：官方 52 个真实站点任务里 44 个需代理、全部 6 个 medium/high 环境易变都在其中 |
| 6 | 代理 | 需要买住宅代理 | **大概率不需要** | 从 WSL 直连探测 17 个目标站点，14 个 200；49 个 proxy 任务里只有 6 个碰到被挡站点；实跑中 Amazon 任务直连拿到 1.0（curl 探测是假阳性） |
| 7 | evaluator 归并 | 编译期硬闸门，不覆盖就拒绝 | **登记而不拦路** | 实测损耗 45%（11 个 spec 只出 6 个），且拦掉的多是「现有函数能判、覆盖集写窄了」。与 §1 定的「生成后归并」本就一致 |
| 8 | 部分分 | 以为可用多阶段检查点 | **照抄官方二元语义** | 核实：官方部分分只来自逐项比例与相似度两类单 metric；`conj="and"` 短路使「多二元 metric 取平均」不产生部分分 |
| 9 | gold.rule 执行 | 受限 DSL 解释器 | **Claude 写 Python + AST 白名单沙箱** | 用户选择；也与官方一致（官方每任务写函数） |
| 10 | schema 的约束力 | 断言「tool-use 强制，是硬约束」 | **只强制结构，不强制枚举值** | 实测反例：产出了 `kind="html"`，不在 enum 里。validate.py 已补九处枚举校验 |
| 11 | 四态离线门禁 `gates/` | 核心质量保证，必写 | **不写** | 当前设计下四态里三态构造上必然成立：gold 与自身比恒为 1（正是审计上一批时批评的同义反复）；实测 2 个 spec 里 1 个 `independent` 与 gold 字节完全相同。它只在 evaluator 带容差或是手写 `tg_*` 时才有价值 |
| 12 | VM 侧 gold 注入 | 与 #11 一起做 | **保留，且是下一步** | 它不是同义反复——测的是路径解析、窗口标题、getter 接线这些真会坏的东西。上一批的 `smoke_gold_states.py` 是他们唯一有效的门禁 |
| 13 | PDF 素材 | 依赖 reportlab | **自带 minipdf.py** | ~~WSL 构建机没有 pip/uv/virtualenv，装包要 sudo~~ **这个前提是错的，见 §9.13** |
| 14 | 构建期噪声注入 | 14 种噪声类型 | **全部删除，对齐官方** | 见 §9.4 |
| 15 | evaluator 缺失时 | 只登记名字（`tg_*`），不实现 | **官方没有的就单独写**（用户拍板："先这样写，最简单"） | 已实现 2 个：`tg_csv_order_subset_values`、`tg_pptx_contains_order_structure_values`，经 `shim.py` 运行时注册进 OSWorld，零改动官方代码 |
| 16 | `evaluator.options` | emit 不生成（我遗漏了） | **emit 自动生成** | 实测 `compare_table` 不带 `options.rules` 直接 KeyError 崩溃——8 个"复用官方函数"的任务一个都跑不起来。§9.5 |
| 17 | 多样性机制 | 只配额 `app_count` + prompt 软要求 | **配额驱动：主应用轮转 + 单一累积文件** | 实测 15 个 spec：calc 出现率 100%、gimp/vlc 为 0、跨文件 slug 撞名（`warehouse-reorder-alert` ×2）。§9.7 |

### 9.4 为什么删掉全部构建期噪声

**官方的实测证据**（直接下载 HuggingFace 上的官方素材看的）：

```
movies.xlsx（151 行）    合并单元格 0 · 隐藏行 无 · 脚注 无 · 表头干净 · 类型一致
                        唯一的不规范是年份/评分存成字符串，那是导出工具的自然产物
```

另一个 `Student_Level_Fill_Blank.xlsx` 确实是脏的（A 列整列为空、分组下方留空），
**但那个任务的指令就是「把空单元格用上一行的值填满」——脏本身就是题目**，
不是给干净题目额外加的障碍。

结论：**官方素材看起来像真实导出文件，但结构干净；难度来自要做的操作，
不来自数据卫生陷阱。**

**我们这边发现的 bug（删除的直接原因）**：

噪声在**写文件时**注入，而 gold 是从**加噪之前**的原始 content 算的。
语义类噪声因此让两者不一致：

```
agent 看到的文件                gold（从原始 content 算）
  A-1  Open    100                A-1  100
  A-2  Open    200                A-2  200
  A-3  Closed  300                A-4  400
  A-4  Open    400                A-6  600
  A-4 (rev B)  Open  400   <--  这行 gold 里没有
  A-5  Closed  500
  A-6  Open    600
```

认真做对的 agent 会挑出 5 行，gold 只有 4 行 —— **做对了判 0，且是系统性的。**
`empty_column` 同理（文件多一列，gold 没有）。

**论证上的反省**：我此前主张「埋坑能让成功轨迹自然包含验证行为」。
这个论证是弱的 —— 对 rejection sampling 而言，栽了的轨迹本来就被丢弃，
加噪声只是降低成功率，并没有改变**成功轨迹**的行为构成。

**现在的做法**：真实感全部由 Claude 写进 `assets[].content`。
如果一个台账现实中会带货币符号、日期写法不一，就让它自己那样写出来。
构建期不注入任何东西，因此 gold 与 agent 看到的数据永远一致。

净删约 200 行，system prompt 从峰值 3,331 降到 3,099 token。

### 9.5 registry 的映射从未被验证过 —— options 缺失事故

**事故**：`registry.py` 那张「产物类型 → 官方 metric」映射表是我读官方代码后**凭理解手填的**，
从未按 emit 生成的调用方式实测过。结果：生成的 task JSON 语法完全合法，**判分时崩溃**——
`compare_table` 没有 `options.rules` 直接 KeyError。8 个「复用官方函数」的任务全数中招。

**修复**：emit 新增 `metric_options()`，按函数生成必需参数与容差：

```
compare_table        {"rules": [{"type": "sheet_data", "sheet_idx0": "RI0", "sheet_idx1": "EI0"}]}
compare_docx_files   {"ignore_blanks": true}
compare_pptx_files   {"examine_shape": <spec 是否要求判结构>}
tg_*                 {"ignore_case": true, 可选 "fuzzy": 0.9}
```

sheet 索引约定（`metrics/table.py:_parse_sheet_idx`）：
`RI<n>`=result 按位置 / `RN<名>`=result 按名字 / `EI<n>`、`EN<名>` 同理对 expected。

**带 options 后的实测**（`compare_table` + `sheet_data`）：

```
完全一致 1.0 ✓   数字存成文本'5' 1.0 ✓   整数存成5.0 1.0 ✓   sheet名不同 1.0 ✓
表头大小写不同 0.0（可用 instruction 要求"保持表头原样"来管）
值带首尾空格   0.0（同上）
少一行/值改了  0.0 ✓（真错照样抓）
```

`sheet_data` 走 pandas 解析，天然容掉数字文本化——最常见的两类写法差异不会误杀。

**教训**：映射表里的每一行，都必须「按 emit 实际生成的调用方式」跑通一次才算数。
语法合法 ≠ 能运行。

### 9.6 新 evaluator 的落地方式（已验证）

```
taskgen/evaluators/functions.py   官方没有的判分函数（带 options 容差，一函数多任务）
taskgen/evaluators/shim.py        运行时把 EXPORTS 注册进 desktop_env.evaluators.metrics
```

安装：`python -m taskgen.evaluators.shim --install --osworld /mnt/d/research/OSWorld`
——往 venv 的 site-packages 写一个 `taskgen_shim.pth`，之后**任意目录**启动该解释器都自动注册。
`--check <任务目录>` 验证一批 task JSON 引用的函数全部可解析。

对比官方 csv 判分的实测（同判别力，少误杀）：

```
情形               官方 compare_csv    tg_csv_order_subset_values
完全一致                 1.0                1.0
数字写成 240.0           0.0                1.0   ← 官方误杀
表头大小写不同           0.0                1.0   ← 官方误杀
单元格带首尾空格         0.0                1.0   ← 官方误杀
少一行（真错）           0.0                0.0
顺序颠倒（真错）         0.0                0.0
```

OSWorld 侧仅有的痕迹是那一个 `.pth` 文件，官方代码零改动——
这就是 §5.4 说的方案 1，现在验证可用。

### 9.7 多样性：配额驱动，不靠检测兜底（2026-08-08 定稿）

**实测偏科**（前 15 个 spec）：`libreoffice_calc` 出现率 **100%**（15/15），gimp/vlc **0**，
且跨文件 slug 撞名一次。原因不是巧合：表格任务最容易写出确定性 gold，
模型自然往"好判分"的地方滑；prompt 只约束了 `app_count`（数量），没约束用哪些应用。

**官方的多样性怎么来的**：纯手工配额（chrome 46 / gimp 26 / calc 47 / ...），
任务从 77 个真实渠道挖来填坑。没有任何算法检测。

**从 SFT 学生学什么倒推，哪些维度真正要保**：

| 学生学的能力 | 依赖的多样性维度 | 机制 |
|---|---|---|
| 视觉定位（每个应用是独立视觉分布） | **应用覆盖** | 主应用轮转配额（硬） |
| 操作模式（点击/输入/快捷键组合） | **操作类型** | prompt 要求 + quota 报告测量（软） |
| 流程推进（跨应用携带状态） | 跨应用数量、串并行 | `app_count` 配额（硬）+ `dependency` 记录 |
| 终止判断（何时算完/存盘） | **步数分布** | prompt 要求每批含 30+ 步任务 + quota 报告分段测量 |

**表面维度（场景名、公司名、措辞）价值极低**——预训练里见过无数措辞，SFT 不缺这个。
刻意不做的（避免过度保护）：对措辞上强相似度机器、强配额 vlc
（其 gold 是 state 型且未验证，硬塞只会产出坏任务，比缺失更糟；官方也只有 4.7%）、
现在就上 TF-IDF（维持优先级 3，等 variant 机制需要量化"实质差异"时再上）。

**落地的四个机制**（对应四能力表的硬修复）：

1. **主应用轮转** → 视觉定位：约定 `apps[0]` 即主应用（emit 本来就用它推断 snapshot），
   generator 按 `--primary-apps` 轮转，**偏移量按已有 spec 数继续**，跨批不重复偏科。
   默认轮转：chrome, calc, writer, impress, vscode, files, terminal, thunderbird, gimp。
   gimp 可判（png 走官方 `compare_images`/SSIM）；vlc 暂缺（state 型 gold 未验证），诚实记录。
2. **主产物必须是主应用的原生格式** → 操作模式：`vocab.APP_MAIN_ARTIFACTS` 映射
   （files→dir_tree、gimp→png、vscode→json、impress→pptx…），generator 在每个应用的
   原生列表内再轮转。**这一条把"应用轮转"升级成"任务类型轮转"**——否则模型可以让
   gimp 任务最后还是填个表。validator 硬校验 `gold.artifact_type` ∈ 主应用原生表（ERROR）。
3. **步数带轮转** → 终止判断：8-15 / 16-30 / 31-60 三档轮流指定，prompt 要求
   "长带 = 更多来源更多阶段，短带 = 单一目的紧凑任务"。设计期杠杆，真实步长以实跑为准。
4. **单一累积文件** → 去重基础：append 变默认（`--fresh` 才重来），slug/family 跨批排除真正生效。

（第 3 行"流程推进"由既有的 `app_count` 配额 + `dependency` 记录覆盖，无新增。）

quota 报告新增三个视图：主应用分布、estimated_steps 分段、gold 操作类型分布——
可数的配额，不可数的先测量，偏了再修。

**variant 机制（策略 B，已拍板未实现）**：variant 由单独调用生成，
差异维度（数据规模/条件结构/文件格式）作为调用参数指定，不给模型自由发挥空间；
届时 validator 加同族约束（同 family 相似度 >0.85 ERROR、跨 family >0.7 ERROR）并引入 TF-IDF。

### 9.1 已验证 vs 未验证（诚实清单）

**已验证**（有实测数据支撑）：

- Claude 能产出零错误的 spec（第 3、4 批各 4 个，0 errors）
- Claude 能写出通过 AST 沙箱且可执行的 `gold.impl`（4/4）
- 沙箱拦得住七种攻击模式（`import os` / `open` / dunder 逃逸 / `eval` / 缺 `compute` / 参数数错 / 死循环）
- 素材构建产出真文件，噪声正确落地（混日期格式、货币符号、脚注行）
- emit 的 task JSON 与官方结构 100% 一致（顶层 11 键，spec 独有字段零泄漏）
- 轨迹 HTML 渲染器在真实轨迹上可用

**已验证（新增）**：

- `evaluator.options` 由 emit 自动生成，`compare_table` 带 options 实测 8 种情形全部符合预期（§9.5）
- 2 个 `tg_*` 函数已实现并通过 shim 注册，`--check` 确认 4 个任务的函数全部可解析（§9.6）
- 素材已搬进 `/mnt/d/research/OSWorld/taskgen_out/v6/`，task JSON 引用的**每一个路径都存在**
  （9 素材 + 4 gold）——路径约定实测成立

**未验证**（风险全在这）：

- **一个生成任务从未在 VM 里跑完整闭环**（下一步：3 任务并行实跑）
- `gold.kind=state` 的 result getter 一刀切成 `active_tab_info`，官方那 52 个真实站点任务用了 6 种
  （当前 4 个任务全是 derived，未触发）
- `postconfig` 的窗口标题拼接只在纸面推理过，未在真实 VM 验证

### 9.2 已知设计漏洞（尚未解决）

**`gold.impl` 与 `gold.rule` 的一致性无法被管道验证。**

沙箱只保证代码能跑，不保证它实现的是规则说的那件事。而 `compute()` 一个函数同时返回
gold / near_miss / independent，若误解规则，三者会**一致地错**——
`independent_solution` 与 gold 同源，共享同一个 bug，兜不住。

可能的解法：第二次独立 LLM 调用，只给 `gold.rule` 和素材，独立实现一遍再对拍。
成本为每任务多一次调用。**尚未决定是否采用。**

### 9.3 代码精简（ponytail 审查）

用 [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) 的五标签
（`delete:` / `stdlib:` / `native:` / `yagni:` / `shrink:`）过了一遍：

| 标签 | 发现 | 处理 |
|---|---|---|
| `stdlib:` | `load_env` 在 `check.py` 和 `generate.py` 各写一遍 | 提取到 `taskgen/env.py` |
| `delete:` | `validate.py --warn-as-error`、`build.py --only` 从未使用 | 删 |
| `shrink:` | `_kind_for` 是 8 行的恒等映射 | 压成 1 行 |
| `native:` | reportlab 做的事标准库能做 | 已用 minipdf.py 替换（此前完成） |
| 保留 | `sandbox._guarded_import` 是防御纵深（AST 已挡 import，但保留运行时兜底） | 不删，注明理由 |

净减约 14 行——**说明代码本身没有严重过度设计**，因为一路都在边写边砍。
真正的臃肿不在代码里，在**做了但用不上的东西**（`gates/` 是最大的一笔，已决定不写）。

Lint：`ruff` 全绿，配置在 `pyproject.toml`
（`E,F,W,I,UP,B,SIM,RUF,C4,PTH,ARG,TRY`，line-length 100）。

### 9.8 首次全链路闭环（2026-08-08 实测）

3 个生成任务在 WSL 的 Docker VM 里并行跑完，**3/3 出结果，3/3 判 0**。

| 任务 | 步数 | 分 | 实际发生了什么 |
|---|---|---|---|
| `328e41c3` warehouse-reorder-alert | 100 | 0.0 | agent 在 `Reorder` sheet 里写了坏公式，落盘全是 `#VALUE!` / `#NAME?`；gold 是 12 行正确数据。**真实的 agent 失败** |
| `927ddc4d` | 81 | 0.0 | `consolidated_budget.xlsx` 根本没出现在 cache 里 —— agent 从未产出该文件 |
| `daf685e7` | 104 | 0.0 | `final_schedule.csv` 同上；`tg_csv_order_subset_values` 返回 `0.0` 而不是崩溃 |

**这次跑验证了什么**（此前全在"未验证"清单里）：

- `config` 的 `upload_file` 能正确解析 `taskgen_out/<batch>/assets/<slug>/…` 相对路径，素材真的进了 VM
- `launch` / `open` 步在真实 VM 里可用
- evaluator 解析：官方函数（`compare_table`）与自写函数（`tg_csv_order_subset_values`）**都被成功调用**。
  后者返回 `0.0` 而非 `AttributeError`，说明 **`.pth` shim 在真实 runner 进程里生效**
- `postconfig` 的窗口标题拼接没有让 setup 崩掉
- 打分流程走完，`result.txt` 正常写出

**这次跑没有验证什么**：任何一个任务的**正例通路**。三个都是 agent 失败，
所以"gold 正确 → 判 1.0"这条路径**至今没有被证明过**。这是当前最大的未知。
0/3 与 20–25% 的目标通过率并不矛盾（期望值 0.6–0.75 个），但样本量 3 说明不了任何事。

**下一步必须做的验证**：拿 `328e41c3` 的 gold 文件直接当作"agent 产物"塞进 VM 的目标路径，
跑一次 evaluate，确认判 1.0。这是**唯一**能证明判分不是恒 0 的办法，成本极低。

### 9.9 五个缺口的处置（2026-08-08）

用户点名的四个缺口 + 闭环里暴露的第五个：

| # | 缺口 | 处置 | 理由 |
|---|---|---|---|
| ⑤ | click-center 样板 | ✅ **已补，但按域门控** | 见下 |
| — | `compare_table` 按位置选 sheet | ✅ **已改为按名字** | 闭环里实际踩到 |
| ① | 操作型任务 T1（`vm_command_line` + rule） | ⬜ 建议**下一个做** | 所需 getter/metric 官方全有，零新代码 |
| ② | relational gold（第三种 gold 形态） | ⬜ 建议**之后做** | 需要新增词表项与 prompt 分支 |
| ④ | 真实网站任务 | ⬜ 建议**最后做** | 依赖 `state` 型 getter 选择，且需代理 |
| — | T3（vscode 扩展驱动） | ⏸ **继续暂缓** | 需在快照里预装 `vscodeEvalExtension` |

#### ⑤ click-center：原先的判断是错的

原先记的是"官方几乎每个任务 config 里都有的聚焦步骤"。**这是错的**，实测：

```
domain                 有 click-center   该域总数
os                          19            24     79%
vlc                         14            17     82%
multi_apps                   5           101      5%
libreoffice_impress          3            47      6%
chrome / gimp / calc / writer / thunderbird / vs_code   全部 0
```

369 个任务里只有 41 个（11%）。这不是通用样板，是**桌面/播放器专用**的聚焦手段：
`os` 和 `vlc` 域没有文档窗口自然抢焦点，而 Calc 有 —— 往表格中央点一下只会随机选中一个单元格。

所以 emit 里按 `pick_domain(spec) in ("os", "vlc")` 门控。占位符替换发生在
`controllers/setup.py:456-480` 的 `_execute_setup` 内（`_launch_setup` 也有一份），
所以这一步**必须是 `execute` 类型**，写成 `command` 类型不会被替换。

#### 格式上仍与官方不一致的地方

官方 369 个任务的 config 步骤频次（实测）：

```
download 278 · launch 275 · open 155 · execute 154 · activate_window 65
chrome_open_tabs 53 · command 29 · sleep 14 · googledrive 8 · login 8
```

我们目前只生成 `upload_file` / `launch` / `open` / `execute`。最大的缺口是
**`download` 出现 278 次而我们 0 次** —— 官方素材托管在云端 URL，
我们走 `upload_file` 从仓库里传。这是**有意的差异**（素材是我们自己生成的，没有云端 URL），
不是缺陷，但要记在案：如果将来要把任务集发给别人复现，必须换成 `download`。

#### 正例对照（2026-08-08，闭环判 0 之后立刻补做）

首次闭环 3/3 判 0，但**全部是 agent 失败**，所以"gold 正确 → 判 1.0"这条路一次都没走过。
判分函数恒返回 0 会给出完全相同的观测。补做最便宜的一级对照：把 gold 文件同时当作
result 和 expected 喂给该任务实际选中的 metric 与 options。

```
328e41c3  compare_table                             RNReorder/ENReorder    -> 1.0
34536c6d  tg_pptx_contains_order_structure_values   ignore_case            -> 1.0
927ddc4d  compare_table                             RNChen/ENChen          -> 1.0
daf685e7  tg_csv_order_subset_values                ignore_case            -> 1.0
```

**4/4 判 1.0 —— metric + options 这一层不是恒零。** 仍未验证的是 getter 层
（`vm_file` 把 VM 里的文件拉出来、`local_file` 解析仓库相对路径）与 `postconfig` 的时序，
那需要在真实 VM 里把 gold 注入目标路径再 evaluate 一次。

顺带证实了按名字选 sheet 的必要性：`warehouse-reorder-alert` 的 gold 工作簿只有
`['Reorder']` 一个 sheet，而输入素材是 `['Stock']`——agent 的产物会**同时有两个**。
`RI0` 取到的是 `Stock`，永远判 0。

#### 又一条系统性偏差：LibreOffice 任务没有预先 open

实测官方：`libreoffice_calc` **47/47**、`libreoffice_writer` **23/23**、`impress` 45/47
都在 config 里 `open` 文档，且**没有一个用 `launch`**。

我们的 emit 只在 spec 标了 `opened_at_start` 时才 open，而模型这批一个都没标，
结果是 agent 得自己在桌面上找文件、双击、等应用起来——**凭空比官方难一档，
而且难的这一档不是任务想测的东西**。

修法（确定性兜底，不依赖模型记得标）：主应用是 LibreOffice 系时，
若无任何 asset 标了 `opened_at_start`，就打开**主应用原生格式**的那个输入
（gold 目标同名者优先）。只开一个：其余文件由 agent 自己开，这部分是官方多应用任务
本来就保留给 agent 的工作。

修完的实际输出：

```
328e41c3  primary=libreoffice_calc     open=inventory_levels.xlsx
34536c6d  primary=libreoffice_calc     open=pricing_tiers.xlsx
927ddc4d  primary=libreoffice_writer   open=chen_budget_narrative.docx   <- 与指令首句一致
daf685e7  primary=libreoffice_calc     open=speakers.csv
```

#### 未决：指令里存在评测器看不见的约束

`927ddc4d` 的指令要求「Amount 填成**恰好两位小数**的纯数字」，但 gold 里存的是整数
`34200`，而 `compare_table` 经 pandas 读出来是数值，**根本看不到小数位格式**。

对测试集这只是无害的装饰；**对 SFT 训练数据这是有害的**——被判 1.0 的轨迹里
agent 并没有照做，等于在教学生"指令里的约束可以选择性忽略"。

拟加的校验：instruction 里出现的可判定约束，必须能被 `judgment_dims` 里的某一维覆盖；
覆盖不了的约束要么删掉，要么换成评测器看得见的写法。**尚未实现。**

### 9.10 workflow 代码审查（2026-08-08，13 agent / 1.48M token）

六个维度并行审查 + 对抗证伪（默认驳回，除非验证者能自己复现失败路径）+ 汇总。
原始发现 33 条，**存活 29 条**，其中 1 条 critical、7 条 high。

审查方法上值得记下的一点：**要求每个 agent 读官方源码并引 `file:line`**，
证伪阶段推翻了 4 条，还纠正了若干严重度和事实。例如原报告说
"整条 state 路径不可达"，证伪阶段确认 `kind=state` + `files`/`vscode` 是干净通过的，
真实后果只是 registry 里四个官方 state metric 选不中（死词表）。

#### critical：registry 把要 rules 字典的 metric 接到了文件路径上

OSWorld 恒定调用 `metric(result, expected)`（`desktop_env.py:498,520`），
但官方 metric 对第二个参数的期望**不一致**：

| 形状 | 第二个参数是 | 例子 |
|---|---|---|
| file | 路径 | `compare_table`、`compare_docx_files` |
| **rule** | **字典** | `check_json`（`general.py:279`）、`check_list`（`:151`）、`check_include_exclude`（`:28`）、`check_json_settings`（`vscode.py:49`）|

我们的 derived 分支永远发 `expected: local_file`（getter 返回**路径字符串**），
于是 `rules.get("include")` 在 str 上抛 `AttributeError`。
`run.py:215` 按 example 捕获异常，所以**任务不报错，只是没有 `result.txt`，从 campaign 里静默消失**。

实测受影响的是 **9 个 rotation 槽里的 4 个**：chrome / vscode（json）、files / terminal（dir_tree）。
首次闭环全是 LibreOffice 任务，这是它没暴露的唯一原因。

**修法**：给 `registry.OFFICIAL` 加第四列 `expected_shape`，`resolve()` 按形状过滤，
`EXPECTED_SHAPE` 把 gold kind 映射到形状。比"删掉那几行"改动大，但**因为要做 T1，这个改动本来就得做**。

#### high：AST 沙箱可被 `operator.attrgetter` 完整逃逸

`_Auditor` 只看 `ast.Attribute` / `ast.Name` 节点，**从不看字符串字面量**；
而 `operator` 在白名单里，`operator.attrgetter("__class__")` 的 dunder 遍历全在字符串里。

实测：`audit()` 返回 `[]`，`run_compute` **成功执行**并摸到 `object.__subclasses__()` 的 255 个子类。

**修法**三层：`operator` 移出 `ALLOWED_MODULES`（attrgetter/methodcaller/itemgetter
本质就是字符串驱动的 getattr，与白名单模型对冲）；拒绝 AST 中任何匹配 `__\w+__` 的字符串字面量；
拒绝 `.format` / `.format_map`（`"{0.__class__}".format(x)` 是同一个洞的另一条通道）。
实测三条逃逸全堵，正常 gold 代码不受影响。

#### high：`tg_pptx` 默认 `fuzzy=0.9` 让数字全错也判 1.0

`fuzzy` 默认 0.9 且 `metric_options` 永远不会覆盖它（该函数被选中的 dim 集与
`{numeric_tolerance, format_constraint}` 不可能相交），所以散文容差**恒生效**。
实测 gold `["Revenue rose 12% to $4.2M", ...]` vs 三个数字全错的 deck → **1.0**。

**对测试集这是宽松，对 SFT 训练数据这是投毒**——被判 1.0 的轨迹里数字是错的，
等于在教学生"数字不用对"。

**修法**：默认改 `fuzzy=0.0`；且 `_cells_equal` **拒绝对任何含数字的字符串做模糊匹配**
（`"…$4.2M"` 与 `"…$4.3M"` 相似度 0.97，编辑距离在这里毫无意义）。
顺带修 `_num`：拒绝前导零（`"0010"` 是账户码不是 10）、手写指数（`"2e1"`）、非有限值（NaN 自比不该判 0）。

#### high：同名素材互相覆盖 / 目录素材让 setup 崩

- build 和 emit 都只用 `Path(vm_path).name` 做 key，两个不同目录的同名素材在磁盘上只剩一个，
  而 gold 是从 spec 里**各自独立**的 content 算的 → **完美 agent 恒得 0，且 build 报告显示 "ok 2 asset(s)"**。
  修：validator 对 basename 和 vm_path 双重去重。
- `kind=dir` / `code_project` 送进 `upload_file`，而官方 `_upload_file_setup` 是 `open(local_path,"rb")`，
  目录抛 `IsADirectoryError`，且 `setup.py:344` 只捕 `RequestException` → 逃出 `reset()`。
  修：validator 直接 ERROR（按用户决定：先拦，等真需要目录任务时和 dir_tree 的 getter 一起实现）。

#### high：`files` 主应用的 dir_tree 任务无法完成

`files` 唯一的原生产物是 `dir_tree`，而 `vm_file` getter 对目录返回 None，
`check_list` 命中 `if result is None: return 0.` → **无条件 0**。占 rotation 的 1/9。

修：`dir_tree` 归入 `STATE_ARTIFACTS`，validator 禁止它配 `kind=derived`，
强制走 `kind=operation` 的 `vm_command_line` 探针路径 —— 这正是 T1 该干的事。

#### medium：`.pth` 提前 import 污染了 campaign 溯源

旧 `.pth` 在 site 初始化期就 `import desktop_env`，把**默认 `--osworld`（有魔改的那份）**
钉进 `sys.modules`。而纯净 worktree 共用它的 `.venv`（本文 CLAUDE.md §2），
所以**从纯净 worktree 跑"官方" campaign 会静默执行魔改版 `check_json_settings`**。

修：`.pth` 只注入 taskgen 根（**不再注入 OSWorld 根**），装一个
`sys.meta_path` finder 惰性注册——谁先 import 到 metrics 模块就挂给谁。
实测 arm 时零 import，首次 import 时 3 个 `tg_*` 全部挂上，官方函数不被替换。

#### medium：步数带被锁死在主应用上

`(off+i) % 9` 选 app、`(off+i) % 3` 选步数带，而 **3 整除 9**，所以
`((off+i)%9)%3 == (off+i)%3` 恒成立。实测 60 个 spec：chrome 7/7 全在 8-15、
calc 7/7 全在 16-30、writer 7/7 全在 31-60 —— **边际分布完美均匀，联合分布为零**。
9B 学生会学到"chrome 任务短"这个应用身份捷径，而不是"产物写完存盘了就停"。
而终止判断本来就是四大能力里最弱的一项。

修：每绕完一圈让 band 多进一格（`(k + k//laps) % 3`）。`app_count` 同样漏了 `off`，一并修。
实测修后每个应用都覆盖三个 band、五种 app_count、全部原生产物类型。

#### medium：postconfig 挑错了应用

`next((a for a in apps if a in WINDOW_TITLE))` 挑**任意**一个 LibreOffice 应用，
窗口标题却用**主产物**的文件名拼。实测 `apps=['vscode','libreoffice_calc']` +
`settings.json` → `activate_window "settings.json - LibreOffice Calc"`，
这窗口不存在，`setup.py:600` 只记日志，ctrl+s 打在焦点上 —— 这个 block 唯一的目的落空。

修：只看 `apps[0]`。**顺带解释了首次闭环为什么那么难看**：
`grant-budget-consolidation` 当时 `apps[0]` 是 writer，postconfig 拼出
`consolidated_budget.xlsx - LibreOffice Writer`，盲打的 ctrl+s 从未存到目标文件。

#### 其余已修

| 问题 | 修法 |
|---|---|
| 重复 instruction 的 ERROR 挂在 `"<batch>"` 上，slug 正则永远产不出这个值 → 两个重复 spec 全部保留，且此后每批重报、烧掉全部 repair 预算 | 按 slug 归责 |
| `quota_report` 的步数分箱硬编码 `26-40`，横跨真实 band 边界 → **唯一能告诉你 band 轮转是否生效的数字打不出来** | 从 `V.STEP_BANDS` 派生 |
| `--dry-run` 在 `existing` 加载前就 return，off 结构性恒为 0，且 artifact 索引硬编码 `[0]` | 抽出 `rotation()` 供两处共用 |
| `write_csv` 把 gold.impl 的 float 直接写成 `12140.0`，而 Calc 导出 `12140`，`compare_csv` 是逐行文本比较 → 所有 agent 都匹配不上 | builder 层 `_cell()`：整数值 float 写成 int |
| `write_pptx` 同一页既有 bullets 又有 table 时静默丢掉 bullets（layout 5 无 body placeholder），而官方 `compare_pptx_files` 在 shape 数不等时返回 0 | 恒用 layout 1，空 placeholder 显式移除 |
| `minipdf` 用 latin-1 编码却声明 `/WinAnsiEncoding`（cp1252），27 个码位静默变 `?`，`compare_pdfs` 是 fuzz 比例、每个坏字符都扣分 | 改 cp1252 |
| `gold.operations` 是九个 enum 字段里唯一没有成员检查的 | 加检查 |
| `LAUNCH["files"]` 用了 Nautilus 3.6 就移除的 `--browser`，而 server 无条件返回 200、setup 不抛 → 文件管理器没开但 setup "成功" | 去掉该 flag |
| `acceptable_alternatives` 声明映射到 `conj="or"` 但全代码库无实现 | 删掉（违反 README §8"声明了却静默无效比不提供更糟"）；`conj="or"` 需要多 gold 变体，本质是 variant 机制，等那步再做 |
| `state_checks` 可能被写成自然语言，而它是当正则匹配 URL 的 → 正确答案恒判 0 | validator 要求可编译且不像散文 |

#### 审查确认干净的部分（值得记，省得以后重查）

- **官方对齐层整体干净**：11 个顶层 key、config step 类型与参数名逐字匹配
  （dispatch 是 `getattr(self,"_{type}_setup")(**parameters)`，多一个 key 就 TypeError，我们一个不多）、
  四个 getter 都存在且导出、`dest` 两侧都真被读、cache 目录按任务隔离
- **`postconfig` 的 ctrl+s 不是无效动作**：`evaluate()` 在 `desktop_env.py:463` 先跑 postconfig，
  result getter 到 `:487`/`:513` 才调用
- **artifact 轮换算术正确**（逐字求值而非信注释），跨 lap 边界也对；九个应用的全部原生 artifact 都被请求到
- **schema 必填字段与 emit/build 的硬下标完全对齐**，合法 spec 不可能让编译器 KeyError
- **`functions.py` 里五处 `zip(strict=False)` 全部安全**：每处前面都有显式长度相等检查
- **`metric_options` 发出的每个键都真的被目标 metric 读到**；`compare_pdfs` 是唯一没有 `**options` 的，emit 也正确地给它发 `{}`

### 9.11 T1 操作型 + relational 已落地（2026-08-08）

按用户拍板的顺序（**补种类 → variant → 量通过率**）和配比（derived : operation : relational = **6 : 3 : 1**）。

#### 新增两种 gold 形态

```
GOLD_KINDS = derived | operation | state | relational
```

**`operation`**（判系统状态，官方 12 个任务用的形状，**零新增 evaluator 代码**）：

```json
"result":   {"type": "vm_command_line", "command": ["/bin/bash","-c","<探针>"]},
"expected": {"type": "rule", "rules": {"include": [...], "exclude": [...]}},
"func":     "check_include_exclude"
```

spec 侧新增 `gold.probe_command` / `include` / `exclude`，且**禁止 `impl`**。
gold 是字符串不是文件，所以不需要沙箱执行、不存在 asset/gold 往返一致性风险
——而那正好是 derived 通路上最脆的一环。

**探针的防护（用户选了"静态约束 + VM 初始态实跑"）**：

探针是模型写的 shell，跑在 VM 里，写坏了会**静默地永远判 1**——
`echo "done"` 配 `include:["done"]` 就是一个完美 agent 和什么都不做的 agent 同分的任务，
而且 JSON 看起来完全正常。这比 `gold.impl` 算错更糟：那个至少有 `independent` 可能不一致，
探针错了没有任何第二意见。

已实现的静态约束（`validate._check_probe`）：必须有 if/else 双分支；
`include` 和 `exclude` 都非空且不相交；**每个哨兵句必须字面出现在命令里**。
实测 `["/bin/bash","-c","echo 'all three reports were filed'"]` 被两条 ERROR 拦住。

**尚未实现**：VM 初始态实跑（起一个 VM，在**任务开始状态**跑所有探针，必须全部判 0）。
静态约束证明不了"条件写对了"，只有这个能。

**`relational`**（判方向，与**原始输入**比较，无 gold 文件）：

官方用了一个反直觉的手法。三个函数的方向断言**互相不一致**，名字全是误导的（读源码确认，不是读名字）：

| 函数 | 断言 |
|---|---|
| `check_brightness_decrease_and_structure_sim(src,tgt)` | **tgt 比 src 亮**（`gimp.py:301`）|
| `check_contrast_increase_and_structure_sim(src,tgt)` | **src 对比度比 tgt 高**（`gimp.py:508`）|
| `check_saturation_increase_and_structure_sim(src,tgt)` | **src 比 tgt 饱和**（`gimp.py:334`）|

而 OSWorld 恒定调用 `metric(result, expected)`，所以 `src=result`、`tgt=expected`。
**方向由"agent 的产物放在哪一侧"决定**——官方就是这么干的：
`gimp/7a4deb26`（"调暗照片"）把 agent 产物放 `result`，
`multi_apps/4c26e3f3`（"提亮"）把 agent 产物放 `expected`、原图放 `result`。

**后果必须写明：relational 任务的 `result` 字段并不是 agent 的输出。**

`emit.RELATIONS` 表把六个方向映射到 (metric, agent 放哪侧)，**六个全部用真实图片实测**：
正确方向的编辑 → 1.0，反方向的编辑 → 0.0。方向搞反会让所有 gimp 任务整体倒置，
所以这一条不能只靠读源码。

#### 分层教训：修对了地方，但放错了层

"gold sheet 名应该继承模板 sheet 名"这条先放进了 `emit.metric_options`，
结果 `warehouse-reorder-alert` 的正例对照从 1.0 掉到 **0.0** ——
它的指令是**新建**一个叫 `Reorder` 的 sheet，模板里那个叫 `Stock`，
于是发出的 `ENStock` 在 gold 工作簿里根本不存在。

正确的层是 **builder**（`build._named_sheet`）：只在 `gold.impl` **没给** sheet 名
且 gold 产物就是某个输入文件（原地改模板）时，才继承模板的 sheet 名；
任务要求新建 sheet 时，`gold.impl` 选的名字就是指令告诉 agent 的名字，不能动。
emit 则单纯读 gold 文件里的名字——**先把 gold 文件做对，emit 只负责如实转述**。

修后 4/4 正例对照恢复 1.0。

#### 顺带修正了一条约定歧义

`apps[0]` 的语义是**产出主产物的那个应用**（schema 里早就这么写），不是"从哪个应用开始读"。
两个老 spec 违反了它（grant-budget 产 xlsx 却把 writer 排第一、product-launch 产 pptx 却把 calc 排第一），
被新 validator 抓到。修正 app 顺序后 4 specs 0 errors。

### 9.12 这一轮之后还没做的（按优先级）

1. **探针的 VM 初始态实跑** —— 起一个 VM，在任务开始状态跑所有 `operation` 任务的探针，
   必须全部判 0。静态约束（双分支 + 哨兵字面出现）证明不了"条件写对了"，
   只有这个能。用户已选"静态 + 动态都做"，动态这半未实现。
2. **VM 侧注入 gold 验 getter 层** —— 把 gold 塞进 VM 目标路径再 `evaluate()`。
   目前正例对照只验到 metric + options（4/4 判 1.0），
   `vm_file` 拉文件、`local_file` 解析仓库相对路径、`postconfig` 实际时序都还没在真实 VM 里验过。
3. **variant 机制（策略 B）** —— 按拍板顺序排在补种类之后。
   同族相似度 >0.85 ERROR、跨族 >0.7 ERROR，届时引入 TF-IDF。
4. **指令里存在评测器看不见的约束** —— 见 §9.9 末。`927ddc4d` 要求"恰好两位小数"
   而 `compare_table` 经 pandas 看不到小数位格式。对 SFT 有害（教学生忽略约束）。
   拟加：instruction 里的可判定约束必须被某个 `judgment_dim` 覆盖。
5. **目录进出 VM** —— `kind=dir` / `code_project` 目前在 validator 里被 ERROR 拦掉。
   真要做 files 域的目录任务，需要 tar 打包 + `execute` 解压，
   和 `dir_tree` 产物的 getter 一起实现（同一个缺口，分两次改会返工）。
6. **真实网站任务（④）** —— 已决定要做但未做。依赖 `state` 型 getter 选择
   （官方 52 个真实站点任务用了 6 种，我们一刀切 `active_tab_info`）+ 住宅代理。
7. **T3（vscode 扩展驱动）** —— 继续暂缓，需在快照里预装 `vscodeEvalExtension`。
8. **`gold.impl` 与 `gold.rule` 的一致性**（§9.2 的老洞）—— 沙箱只保证能跑，
   不保证实现的是规则说的那件事。可能的解法是第二次独立 LLM 调用对拍，尚未决定是否采用。

### 9.13 一个错误前提，以及它造成的连锁误判（2026-08-08 纠正）

**错误前提**：「WSL 构建机没有 pip / uv / virtualenv，装包要 sudo。」

**事实**：`uv` 就在 `~/.local/bin/uv`（0.11.29），OSWorld 的 `.venv` **本来就是它建的**
（`pyvenv.cfg` 里写着 `uv = 0.11.29`）。venv 里没有 `pip` 只是因为 uv 建的 venv 默认不装 pip，
不代表装不了包。实测：

```
uv pip install --dry-run reportlab        ->  + reportlab==5.0.0        可以装
uv pip install --dry-run imageio-ffmpeg   ->  + imageio-ffmpeg==0.6.0   可以装
```

正确的用法（`VIRTUAL_ENV` 指到 OSWorld 的 venv）：

```bash
export PATH=$HOME/.local/bin:$PATH
export VIRTUAL_ENV=/mnt/d/research/OSWorld/.venv
uv pip install <package>
```

**这个错误前提造成的连锁误判**：

1. **手写了 `minipdf.py`（127 行）替代 reportlab** —— 白写的。而且它是整个 builders 里
   **唯一一条"写和读不同源"的路径**（我们自己写 PDF，官方用 pdfplumber / PyMuPDF 读），
   风险最高的那条，本来可以用现成库消掉。
2. **判定 mp4 / mp3「造不了」** —— 错的。`imageio-ffmpeg` 自带静态 ffmpeg 二进制，
   无需 sudo，装完一条命令就能生成测试视频/音频。这意味着 **VLC 域并非技术上不可做**，
   之前把它排除的理由需要重新评估（它的通过率 41.2%，不算低）。
3. **判定 xcf「造不了」** —— 部分错。`gimpformats` 能读写 xcf，但它要把 numpy
   从 1.26.4 升到 2.5.1，而判分侧的 pandas / opencv / scikit-image 多数钉在 numpy<2，
   **为了造素材去升 numpy 可能把判分搞坏**，不划算。
   **更安全的路是让 VM 自己造**：GIMP 就在镜像里，config 里 `execute` 跑 `gimp -i -b` 批处理。
   这也是做「图层类任务」的唯一办法 —— 官方 6 个 xcf 任务全是图层操作
   （填充背景图层 / 新建名为 Square 的图层 / 调整 dog 图层高度），png 没有图层这个概念。

**教训**：一个没验证的环境前提写进 MD 之后，会被后续所有决策当作既定事实引用，
而且**越往后越不会有人回头质疑它**。环境类结论必须当场用命令验证并把命令记下来，
不能只记结论。

### 9.14 素材类型覆盖率（实测）

官方任务注入 VM 的素材，按出现次数统计（`download` + `upload_file` 的 files 项，共 458 次）：

| 类型 | 次数 | builders 能造？ |
|---|---:|---|
| pdf | 106 | ✅（但走的是自写的 minipdf，应换成 reportlab）|
| xlsx / docx / pptx | 187 | ✅ |
| zip / gz / xz | **51** | ❌ 标准库 `zipfile`/`tarfile` 约 30 行即可，且解锁「解压/归档」整类 operation 任务 |
| png | 24 | ✅ |
| jpg / jpeg / webp / raw | **28** | ❌ Pillow 已在用，`save()` 换扩展名即可 |
| py / sh / md / code-workspace | **24** | ❌ 纯文本，txt writer 加一行扩展名映射即可 |
| mp4 / mp3 | 18 | ❌ 需要 `imageio-ffmpeg`（可装） |
| xcf | 6 | ❌ 需要 VM 内的 GIMP 批处理 |
| ods / odt / xls / ppt | 5 | ❌ 需要 LibreOffice headless 转格式 |

**当前覆盖 325/458 = 70%。** 补上「几乎白送」的三类（图片格式 + 文本扩展名 + 压缩包，
约 50 行）后到 **99%**。

另有一条已验证的好消息：**我们写文件用的库与官方判分读文件用的库是同一套**
（xlsx→openpyxl、docx→python-docx、pptx→python-pptx、png→Pillow），
所以不存在格式往返不一致的风险。**唯一例外就是 PDF**（我们写 minipdf、官方读 pdfplumber），
这也是第 1 条该修的理由。
