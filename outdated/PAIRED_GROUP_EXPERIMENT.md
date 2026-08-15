> **暂缓中(2026-08-15 收编)**:不在当前数据生成路径上;主线见 `EXPERIMENTS.md`。

# 配对组实验 —— 起草成果与审查结论（⏸ 已暂缓）

> 创建：2026-08-08
> 状态：**暂缓，不在当前数据生成路径上**。主线见 [TASK_GENERATION_PLAN.md](TASK_GENERATION_PLAN.md) §1.2。
> 原始产出：`osworld-taskgen/examples/paired_group_logics.json`（407 KB，15 个逻辑 × 5 档 + 38 条审查意见）

---

## 1. 这个实验原本要做什么

回答一个因果问题：**跨应用本身是否降低成功率？**

做法是把同一个业务逻辑做成 1/2/3/4/5 应用五个版本，**控制住原子操作数与信息量**，
使工作量近似相等。这样成功率的下降就只能归因于「跨了几个应用」，
而不是「高应用数的任务本来就更重」。

15 个逻辑 × 5 档 = 75 个任务。

---

## 2. 起草结果

用 workflow 生成（10 agents / 582k tokens / 32 分钟）：
3 个视角各提 7 个候选 → 21 个 → 去重选 15 → 5 个 agent 展开成五档 → 2 个 critic 审查。

| # | slug | 各档 atomic_actions |
|---:|---|---|
| 1 | `three-way-match-po-grn-invoice` | 16, 16, 17, 17, 17 |
| 2 | `paper-shortlist-dedup` | 15, 16, 16, 17, 17 |
| 3 | `shift-rest-gap-audit` | 15, 16, 16, 17, 17 |
| 4 | `ar-aging-late-fee` | 15, 16, 17, 17, 18 |
| 5 | `bib-citation-audit` | 14, 15, 16, 17, 17 |
| 6 | `ticket-triage-sla` | 15, 16, 17, 17, 18 |
| 7 | `expense-policy-adjudication` | 16, 16, 17, 17, 17 |
| 8 | `ablation-result-rollup` | 15, 15, 16, 16, 17 |
| 9 | `inventory-count-variance` | 14, 14, 15, 15, 16 |
| 10 | `bank-reconciliation-unmatched` | 15, 16, 17, 18, 18 |
| 11 | `dataset-license-inventory` | 15, 16, 17, 17, 18 |
| 12 | `contact-dedupe-merge` | 15, 16, 17, 17, 18 |
| 13 | `budget-overrun-attribution` | 16, 17, 18, 17, 18 |
| 14 | `reviewer-assignment-coi` | 15, 16, 17, 17, 18 |
| 15 | `performance-band-quota` | 16, 17, 17, 18, 18 |

纸面上全部落在 14–18 区间，看起来配平得很好。

---

## 3. 审查结论：配平是假的

38 条意见，其中 **blocker 6 / major 22 / minor 10**。核心问题有两条系统性的、两条局部的。

### 3.1 ⛔ 系统性：原子动作的计量单位在档与档之间不统一

低应用档把一次列级清洗（拆合并单元格并向下填充 45 行、72 行日期归一、删一行脚注）
**各记 1 分**；高应用档把「打开 Thunderbird → 在 14 封邮件里按发送时间比较 3 个同名附件
→ 保存 → 在 Calc 打开」**整体记 3 分**。

按统一尺度重算，`three-way-match` 的 5 应用档实际 GUI 层面 **30 步以上，却记 17**。
也就是说 **12–18 这个约束只在纸面成立**，4/5 应用档普遍越过上限。
而 `bib`(14→17)、`ticket`(15→18)、`ar-aging`(15→18) 声称的档间差已经是 3 ——这还是低估后的数字。

审查给出的修法是先固定一张显式成本表再重新配平：

```
进入一个新应用并定位到目标内容        4 分
在诱饵集合里做一次「取最新/取现行」判定  2 分
一次列级转换（>=30 行）              2 分
新建文件 + 另存为对话框               2 分
写一个单元格 / 字段                  0.1 分
删一行 / 跳过表头                    0.2 分
```

并且**只允许同类交换补差**（信息从 sheet 搬到网页、字段从产物 A 搬到产物 B），
禁止用 0.2 分的「删脚注」去抵 4 分的「多开一个应用」。

### 3.2 ⛔ 系统性：可编程应用让高档位可以整体旁路

高档位引入 VS Code 集成终端 / GNOME Terminal 后，纯文本源数据可以被一段脚本整体绕过。

最尖锐的是 `ticket-triage-sla`：v1 只有 Calc，55 行的跨格式时间差 / 分档 / 排序全靠 GUI 公式；
v4/v5 却给了 VS Code + 纯文本 `tickets.csv` + 可 curl 的 localhost 映射表，
**整题一段脚本做完，应用越多反而越省力，难度梯度被反转。**

`bib-citation-audit` 更彻底：源数据是 `.tex`/`.bib` 纯文本，
集成终端一条 python 就能出结果，v1 标称的「14 个原子动作」完全不成立。

### 3.3 ⛔ `ar-aging-late-fee`：方向反了

v1–v3 需要对约 50 行做分档日费率 + 90 天以上一次性 5% 违约金 + 逐行 half-up，
是本逻辑最重的计算块。**v4/v5 把它整块删掉**，换成 3 个占位符替换 / 3 次建目录复制。

结果是：Writer 里的费率对 gold 没有任何因果影响，agent 完全可以不打开 Writer 就拿满分
（按「必须打开并交互」的口径，v4/v5 实际是 3/4 应用）；
而且**工作量随应用数单调下降**，与被测变量的方向正好相反。

### 3.4 ⛔ `shift-rest-gap-audit`：输出侧成本差一个量级

v2–v5 的交付物是「向一个只有表头、没有 body 行的 docx 表格插入约 11 行 × 5 列中文」，
agent 必须自己插行再逐格填 55 个单元格；而 v1 只需在 Calc 里写一个 11×5 的块。
这两者不是同一量级，却被记为 +3/−2。

（同组的 `paper-shortlist` 预置了 5 个空 body 行，说明设计者知道这个成本，
但这里因为违规行数本身就是答案而无法预置。）

---

## 4. 为什么这验证了「暂缓」是对的

配对组的**全部价值**建立在「五档工作量等价」这一个前提上。前提不成立，统计结论就不成立。

而审查显示：**这个前提在生成阶段极难保证**，
即使明确要求、即使给了 12–18 的量化区间、即使让模型自报 `atomic_actions`，
产出的东西纸面达标而实质不达标——而且偏差方向不随机（高应用档系统性被低估）。

要救活它，至少要做三件事：

1. 固定一张显式成本表，按它重算五档，超上限就整组缩小数据规模而非删噪声找平
2. 统一「是否允许脚本化」：五档要么都不给可编程环境，要么都给且 GUI 取数项数量相同
3. 保证每一档新增的应用都是 **load-bearing** 的——它提供的信息必须对 gold 有因果影响，
   否则 agent 可以跳过，应用计数就是虚的

这三件事本身是一个独立的小项目，不适合绑在主线数据生成上。

---

## 5. 可回收的部分

**那 15 个业务逻辑本身是有价值的**，问题只出在「五档配平」上。

它们全部满足：gold 可由 Python 从同一份源数据确定性重算、
不依赖实时价格/排名、业务规则里没有主观词、噪声只加在输入侧。
审查的第二位 critic 明确说这批在可判分性上「基本达标」。

所以可以**拆散并入自由组**：每个逻辑只取其中一到两档，作为独立任务使用，
不承担配对统计的职责。这样既用上了这次的产出，又不受等价性约束。

具体候选（审查未标 blocker、且可判分性无重大意见的）：

```
three-way-match-po-grn-invoice    paper-shortlist-dedup
ticket-triage-sla                 expense-policy-adjudication
ablation-result-rollup            inventory-count-variance
bank-reconciliation-unmatched     dataset-license-inventory
contact-dedupe-merge              budget-overrun-attribution
reviewer-assignment-coi           performance-band-quota
```

---

## 6. 另外两条值得带进主线的通用教训

这两条不限于配对组，对自由组同样适用：

1. **可编程应用是难度的漏洞。** 只要任务的源数据是纯文本、且环境里有终端或 VS Code 集成终端，
   agent 就可能用一段脚本绕过全部 GUI 操作。设计任务时要么明确接受脚本化路径，
   要么把关键信息放进非文本载体（截图里的数值、需要 GUI 交互才能展开的内容）。
2. **每个应用必须是 load-bearing 的。** 如果某个应用提供的信息对最终产物没有因果影响，
   agent 会跳过它，`app_count` 就是虚标——这会污染任何按应用数做的分析，
   即使只是相关性分析。**建议把这条写进 spec 校验**：
   `gold.rule` 必须引用到每一个列在 `apps` 里的应用所承载的信息。

---

## 7. 原始数据

```
osworld-taskgen/examples/paired_group_logics.json
  ├── logic_count: 15
  ├── logics[]:  slug / title / business_rule / gold_computation / variants[5]
  │              每个 variant: app_count / apps / dependency / instruction /
  │                            artifacts / evaluator_sketch / atomic_actions / workload_note
  └── review:    overall[2] + findings[38] + blocker_slugs[4]
```
