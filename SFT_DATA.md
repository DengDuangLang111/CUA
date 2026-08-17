# Building SFT data from rollout trajectories

Every rule here was verified against the v11 run (100 trajectories) or the
runner source on 2026-08-13 — the "receipt" column says how. Encode them in
`sft_check.py`; do not rebuild them from memory.

The unit of data: one sample = (rendered context, step-k response). The
response is trained verbatim — thinking, tool_call syntax, coordinates as the
model wrote them.

**The on-disk format is deliberately left as the runner writes it** — one
line per pyautogui action, so a multi-action step spans several lines with
the same `step_num` and a byte-identical `response`. This is lossless
(aggregation reconstructs steps exactly; verified 200/200 groups identical),
and changing the writer mid-campaign would break the trajectory viewer, the
dashboard daemon, and comparability with v11 data. All correction happens in
the builder, governed by the rules below.

## 1 Reconstructing steps from traj.jsonl

| rule | receipt |
|---|---|
| **One line ≠ one step.** The runner writes one line per pyautogui action; a multi-action response repeats the same `step_num` with an identical `response`. Aggregate by `step_num`: one sample per step. | v11: 3770 lines / 3470 steps (8.6% inflation); all 200 multi-action groups byte-identical in `response`, 0 diverged |
| **The observation for step k is step k−1's LAST screenshot.** `screenshot_file` on a row is taken AFTER that action executes. With multi-action steps, take the final row's screenshot of the previous step — `setdefault`/first-row pairing is systematically wrong. | runner source: `obs` overwritten per action inside the step loop |
| **The initial observation is history for EVERY sample, not just step 1's input.** Step k's context contains screenshot 1 = `initial_state.png`; without it the whole trajectory is unbuildable. New runs save it (patched 2026-08-13). For older runs `--initial-fallback mp4` takes recording frame 0 — between `_get_obs()` and `start_recording()` nothing touches the VM, so the gap is ambient-only; the approximation is flagged in `meta.initial_from`. Needs ffmpeg; degrades to dropping the trajectory when absent. | builder test on v11: 0 samples buildable without it (75/75 steps dropped) |
| **Take only the last episode in a file.** `traj.jsonl` opens in append mode: a healed/re-run task stacks episodes. Boundary = step_num decrease OR same step_num with a changed `response` (multi-action lines are byte-identical, so a changed response at the same number is a restart). | mode `"a"` in source; the second signal exists because the smoke test caught a single-step re-run being merged into its successor |

## 2 Filtering steps and trajectories

| rule | receipt |
|---|---|
| **Keep only `score == 1.0` exactly.** `conj:"and"` can emit partial scores. | v11 held only 0.0/1.0 — defensive, zero cost |
| **Drop hallucination steps everywhere, not just trailing.** A step whose `response` calls an undeclared action (`answer`, `screenshot`) trains the model to hallucinate — the executed WAIT is not what the label says. They are NOT all trailing: 7 v11 tasks had real actions after one, including 2 PASSED trajectories (writer/16118294, vs_code/14d0a2c2). Detect with `<parameter=action>\nanswer` (newline inside the tag — adjacency-assuming grep finds nothing). Since 2026-08-13 `actions.py` logs `unhandled action` warnings, so runtime.log lists them. | byte-level scan 2026-08-13 |
| **Truncate degenerate tails.** Passing trajectories can end in a loop the evaluator never sees (43× Ctrl+S, 43× WAIT hit the v11 cap and still scored 1.0). The WAIT breaker (≥10) bounds WAIT tails in new runs; click/key tails still need the truncation pass. | v11: 4 cap-hitting passes, tails confirmed junk |
| **Cap-hitting passes need review even after truncation** — mid-episode flailing (opened wrong menus, recovered) is a judgment call: robustness data vs noise. Current default: keep recovery sequences, cut pure oscillation. | v11 inspection |

## 3 Rendering the training context

The full context anatomy — message layout, folding, wrapper strings,
knob values — lives in [sft/CONTEXT.md](sft/CONTEXT.md); it is the
builder's specification. The rules below are the summary.

| rule | receipt |
|---|---|
| **Labels come from `response`, never from `action`.** The model emits relative 0–999 coordinates; `action` holds pyautogui code already scaled to 1920×1080 (`[180,257]` → `doubleClick(345,277)`). Training on `action` shifts the coordinate distribution ~2×. | cross-checked v11 rows |
| **History must be rendered by the model's own chat template with the same kwargs the campaign sent.** The client does NOT strip thinking (`ensure_empty_think_prefix` only prepends an empty block when missing) and under `nopreserve` it sends `chat_template_kwargs={"enable_thinking": true}` — no `preserve_thinking` key at all. The template (chat_template.jinja, 7764 B) then strips `<think>` from every assistant turn at or before the last user query: `{%- if (preserve_thinking is defined and preserve_thinking is true) or (loop.index0 > ns.last_query_index) %}` keeps thinking, else drops it. So: render history through `apply_chat_template` with the campaign's kwargs — hand-stripping in the builder duplicates template logic and WILL drift. | template read from Tillicum model dir 2026-08-13; client code `mm_agents/qwen/main.py:278-284`, `history.py:90-94` |
| The current step's target keeps its full `<think>` block — that is what the model emitted under `enable_thinking` and what generation-time distribution looks like. | — |

## 4 The builder (test version, 2026-08-13)

`ostg/sft/traj.py` (rules 1–2) + `ostg/sft/build.py` (rule 3):

```
PYTHONPATH=.:/mnt/d/research/OSWorld python -m ostg.sft.build RESULT_DIR \
    --tasks TASKS_DIR --out OUT [--limit N] [--tail-run 5] [--initial-fallback mp4]
```

Emits `samples.jsonl` (messages ending at step k's user turn; `response` =
verbatim target; `meta` = provenance), `images/` (screenshots re-encoded with
the agent's own `process_image`, so disk pixels = seen pixels), and
`report.json` (kept/dropped counts per rule — the audit trail).

Design points worth keeping when this graduates from test version:

- **The message structure is assembled by the agent's own code** —
  `build_messages`, the tools def, the system prompt, `update_folding_state`
  imported from `mm_agents.qwen` — so it cannot drift from the rollout.
  Verified against live `message_cache` payloads: system text, tool_response
  wrappers, and turn shape identical.
- **Hallucinated steps are dropped as TARGETS but kept in HISTORY**: the
  model really saw them in its context, so removing them from history would
  itself be a train/inference mismatch.
- Collapsed screenshots are never copied (lazy image writing).

First real output: 3 passed ms100 tasks → 43 samples, 14 MB images.

**Dialect (decided 2026-08-14): ms-swift, student Qwen3.5-4B** (natively
multimodal; inference stays on our harness, so relative-0–999 coordinates
carry over). `ostg/sft/export.py` reshapes samples.jsonl into swift's
messages+images JSONL next to the images dir; 43/43 converted, one `<image>`
marker per path, order-aligned. Qwen3.5-4B's chat template was fetched and
checked: it strips history `<think>` by the same last-query rule as the
teacher's serving template and has no preserve_thinking kwarg — the student's
default rendering equals the teacher's rollout distribution. Train with loss
on the final round only; verify the exact ms-swift flag at install time.

## 5 Final verification before training

No replay needed — the client already dumps every step's payload (text
verbatim, image base64 truncated) to
`OSWorld/draft/message_cache/qwen_messages_step_{i}.json` (see
[sft/CONTEXT.md](sft/CONTEXT.md) §5). Byte-diff the builder's rendered text
against a handful of those dumps and rule 3.2 is measured, not derived. The
dir is shared across envs and keyed by step index only, so treat it as a
rolling sample, not an archive.

## 6 Provenance to record per sample

run id (`v11-500-ms100-think-nopreserve-20260813`), task slug + id, step_num,
screen size (1920×1080), coordinate convention (`relative 0–999`), template
kwargs used for rendering, and whether the trajectory was truncated/filtered
and why. A sample that cannot answer "which run, which step, what did the
model actually see" is not auditable.

## B 语料 target-token 分布 vs OpenWebRL(2026-08-17,tokenizer 对齐实测)

同一把 Qwen3.5 tokenizer 重算双方(他们的 1.71GB 原始 jsonl 拉到 Tillicum
重数;卡片 max 1,324 vs 我们数出 1,325,口径可比成立)。

| | B 语料 | OpenWebRL 0.4K |
|---|---:|---:|
| N / 总 target | 5,659 / 1,809,926 | 3,085 / 1,030,942 |
| p50 / p90 / p99 / max | 146 / 675 / 2,770 / **9,712** | 314 / 469 / 773 / **1,325** |
| top-1% / 5% token 份额 | **13.4% / 33.5%** | 2.7% / 10.4% |
| >2048 样本/token | 1.7% / **18.3%** | 0 / 0 |
| >4096 | 28 个 / 8.2% | 0 |
| think 占比 | 68.7% | **0%(无 think 标签,推理裸文本 85.7%)** |
| action 占比(≤512 → >4096) | 29.8% → **2.3%** | 11.4%(无长桶) |

判决:双峰分布——典型步比他们短一半,尾巴重一个量级;action 随长度
崩塌 = 超长样本几乎纯教推理不教动手。**待办**:① 审计 28 个 >4k 样本
(固化为 census 长度分层报告);② 核实 swift loss 分母(token 级 vs
样本级,决定尾巴权重 60× 还是 1×);③ 清尾消融四臂(token 配平)见
IDEAS.md。在飞三臂不动。原始文件:Tillicum tmp_owrl/(审计后可删)。

### 组成解剖补遗(2026-08-17)

| 段 | B 语料 | OpenWebRL |
|---|---:|---:|
| think 通道 | 68.7% | **0(通道不存在)** |
| 可见叙述 | 12.6%(人均 ~40 tok) | **84.4%(人均 ~282)** |
| tool_call | 17.4% | 14.3% |
| 结构 | 100% think;96% tool;4% 裸文本终止(DONE/FAIL) | 0 think;100% tool;**终止也走工具调用** |

判决:**重尾 100% 住在 think 通道**(去掉 think 我们人均 ~100 tok 比他们
还匀);他们均匀的四机制 = 无 think 通道(可见叙述有文体自限)+
keep-shortest-of-4 策展 + 主场短任务 + (我们侧)600s 放行政策。
Reasoning-cap 消融臂的施工图:think 重写为 ≤300 tok 可见叙述 = 复刻
他们的组成结构。终止格式差异(裸文本 vs 工具调用)入跨代/格式档案。

### 长考带指纹体检(2026-08-17 凌晨)

| 带 | n | 压缩比 | shingle逐字重复 | 轨迹位置 |
|---|---:|---:|---:|---:|
| A≤512 | 5,096 | .764 | 0% | 53% |
| C 1k-2k | 159 | .384 | 0.1% | 54% |
| D>2k | 73 | .338 | 0.2% | 46% |

**全语料无逐字循环**;C 带抽样原文 = 多条目规划/多约束分解/终止前校验
(深思带标签内容级坐实,cap2048 保 C 正确)。**D 带罪名改写**:非复读迷路,
是"非重复超长铺陈"——伤害机制归能力错配+action稀释,非垃圾进;Phase 2
审计预设从"删多少"转向"改写多少"(Phase 3 rewrite 桶预期 >> drop 桶)。
边界:shingle 不抓换措辞循环;终审仍是 28 个 >4k 人工过目。

### 定窗压缩体检 + cap-512 否决(2026-08-17)

全文压缩比随长度下降是 DEFLATE 的长度伪影;**定窗(前 1,024 字符)拉平后
各带 0.507→0.485 几乎水平**——各长度带信息密度同质,"长=冗余"不成立。
cap 模拟:512 剔 45.7% target token、波及 188/312 轨迹(60%)→ 否决;
1024 剔 29.6%/33%;**2048 剔 15.6%/14% = 维持为第一刀**。长考真问题 =
能力错配 + action 稀释(Phase-3 rewrite 的辖区),非内容冗余。

## 盲审判官考试与 checker 仲裁(2026-08-17)

### 轨迹级 v1 考试:同卷对决(v11-100,全 rollout 成败混审)

| | Qwen3.8-27B think-low | Opus5 no-think |
|---|---|---|
| AUC | 0.774 | 0.763 |
| pass 均/中位 | 8.94 / 9 | 8.24 / 9 |
| fail 均/中位 | 6.47 / **8** | 5.37 / 5 |
| 最佳阈值 | ≥9(acc .820) | ≥7(acc .833) |
| 被骗败例(≥8) | 17/30 | 10/27 |

两判官逐条 r=0.810。**排序能力打平(弱模型开 think ≈ 强模型不开)**,但
刻度不同:Qwen 挤天花板(55/70 pass 打 9),Opus 刻度舒展更好用。
**败例分布双峰**(低段一坨、高段一坨、中段真空)→ 高分败例不是判官噪声,
是"可见证据全说完成了"的子群体:**9 条双判官共享假阳性**(chrome/04624efc、
chrome/dd2afa67、calc/2fb67412、calc/acd3db2e、impress/40e63aa0、
impress/af2758ee、os/aaf68a9c、vs_code/cd179ea7、vs_code/e2b7cf45)。
判官 note 显示采信了 agent 的自我验证表演(EXIT=0、pdftotext……)。
域热点:vs_code 败例均分 8.7 ≥ 其 pass 均分——终端文本型验证域判官失明。
Opus 10 条 error 行(API),resume 会跳过 error 行,补跑前需先剥除。

### 步级审计(Qwen,395 步;终端 319 轨迹 / 隔离 42 轨迹 8 域)

| 层 | n | grounded | outcome | necessary | 弱步(任一≤1) |
|---|---:|---:|---:|---:|---|
| 终端步(pass 收尾) | 319 | 1.98 | 1.96 | 1.99 | 9(2.8%) |
| 隔离步(>2k think) | 73 | 1.84 | **1.52** | **1.56** | **30(41%,散布 21 轨迹)** |

think 带交叉:0-256=3.3% 弱、256-1k=1.6%、**1k-2k=0%(n=11,小样本)**、
>2k=41% → **判官盲画的质量断崖正落在 2048,cap-512/1024 第三次被否**。
>2k 弱步主模式:**"想完不做"**(命令打对不按回车 ~20/30;步1烧3-6k think
后 WAIT 空转 3 条)= action 稀释的行为学证据。39 条弱步里 30 条已被 Bs
的 cap 屏蔽(修复率 77%)。lucky 标志 395 步零触发;恢复步仅逮到 2。

### checker 双向嫌疑与仲裁(arb.py,Opus5+thinking,亮 evaluator 配置)

弱终端步 9 条 + 轨迹级假阴性 3 条 = **12 条 checker 宽松嫌疑**(均在 B 语料)。
仲裁首两单(23 分歧待裁):chrome/13594739 = checker 对、判官排序算错
(宽松嫌疑 -1);**chrome/04624efc = checker_bug_strict 坐实**(任务规则
"同年按字母"应到 /374,checker 硬编码 Durham /370 违反自家规则)——
**被误标失败的成功轨迹**,九共享假阳性之一昭雪。含义:checker-过严 =
pass 率被低估 + 好轨迹被挡在 B 外;checker-过松 = 假 pass 混进 B。
全部裁决 + v2/v2req 复考结果待补(runbook: 质量审计三命令 §v2)。

### 仲裁终审 + 问卷拆账 + 500 池首报(2026-08-17 晨)

**仲裁 23/23(零报错零含糊):10 checker 冤案(全过严向)/ 13 判官失手 /
0 过松**。抽查 3/3 代码坐实:`round()` 银行家舍入 vs 任务"取整"(4162≠4163)、
Impress 单位枚举写 3(米)实为 6(Point)= 物理不可过、硬编码 totals.txt
(任务未命名文件)。**v11-100 真实 pass 率 ≈80% 非 70%**;10 条好轨迹被
挡在 B 外 = 白捡数据;9 共享 FP 里 6 条昭雪(判官对 checker 错)。
判官假阴性侧全军覆没:3 条"checker 过松嫌疑"全是判官算错/误读,
**盲审低分不足以定罪 pass 轨迹**——筛选权限:判官提名、仲裁定罪。

**问卷拆账(Qwen,同卷三跑)**:v1+low AUC .774 / v2+low .759 / v2+medium
.698 → medium 是主犯(想多=自我说服),问卷措辞对弱判官无效;n=100
噪声带 ±.03-.05,方向可信幅度勿信。**Qwen 生产配置 = low 档**;
v2(无清单)退役(Opus A/B 收尾后),**v2req 为生产问卷**(推导分为成功
轨迹分层——分层力待 500 池分布验证;v1 冻结为校准基线)。

**v11-500 Opus v1 报告(n=399,44 error 行待补)**:AUC .771(跨池稳定);
pass 220/fail 179;**81 条败例 ≥8 分 = 500 池冤案候选区**;盲区轮到
os(fail 均 8.0)/vs_code(7.1)——"终端输出好看"域即吵架域。

**筛选流水线(用户令 08-17)**:Qwen v2req 批两池(在跑)→ 分歧/嫌疑集 →
Opus5+thinking 仲裁定罪(500 池 ~110 条)→ 三张名单:keep 高质(pass ∧
清单证据佳)/ 赎回(fail ∧ 判 checker_bug_strict)/ 剔除(pass ∧ 仲裁
坐实假 pass)→ **B-rescue 语料候选**。原始数据只读;名单过目后才建语料
(stage+swap+snapshot)。步审 9 条弱终端步(过松嫌疑)需 arb --targets
扩展单独喂(待实现,diff 先行)。

### 筛选流水线首跑(v11-500 部分数据,2026-08-17 06:0x)

curate 首报(判官 246/444 + 仲裁 23 条时的快照):**rescue 19 / drop 0 /
tier1 199 / tier2 38**。标记清单:weak_terminal 18、req_weak_evidence 19、
judge_low 4、req_not_satisfied 4、req_partial 3、req_unverifiable 1。
赎回分域:chrome 9 / calc 8 / gimp 2 —— **chrome 冤案新病种 = 联网 checker
硬编码易变外部引用**(e-Laws 锚点实为顺序书签、CELEX 需合并版编号 0…、
WHO ICD-11 换路径、期望域名拼写错)。两个方向极不对称:
**fail 侧分歧 123 条(冤案率 ~64%),pass 侧只有 4 条判官低分且 6/6 全判
"判官错"** → **B 语料主要病是"漏掉好数据",不是"混进坏数据"**;
真正的放水嫌疑全部来自步级终端步(18 条 weak_terminal),需 ④ 定罪。

### 分域病理与打分分布(v11-500,Qwen v2req 批到 337/444 的中途观察)

**分数分布(自由分)**:pass 181 条里 137 条打 9(通胀依旧,自由分不能分层);
**fail 156 条呈双峰:低段 0-2 共 28 条(明摆着的失败)、高段 8-10 共 99 条
(63%)**,中段近乎真空 —— 高峰即冤案富矿(已裁 35 条,57% 判 checker 有 bug)。
**推导分才有分层力**:128 条 pass 满分 10(清单全绿=一等品),53 条落 10 以下
(有具体瑕疵→tier2)。**结论:自由分做筛选无效,清单推导分+状态标记才是筛子。**

**分域可疑率**(败例中判官给 ≥8 的比例,即 checker/判官打架率):
impress 49%(n=35)、thunderbird 48%(21)、chrome 74%(19)、calc 34%(34) …
gimp 25%(12)、vlc 17%(6) 最低 —— **gimp/vlc 的失败是"一眼可见做不成"
(判官与 checker 高度一致);impress/thunderbird/chrome 则是脆 checker 或
隐蔽失败的重灾区**。writer(11)、os(16)样本太小暂不下结论。

**判官挑出的毛病类型分域不同**(requirement 非满足状态计数):
impress 36 / thunderbird 36 / gimp 19 / chrome 15 条 **not_satisfied**
= "要求根本没做";**calc 特色是 weak_evidence 23 条** = 算完没保存/
保存无可见确认(其 pass 率仅 51.4%,全域最低之一);os/writer/vs_code
几乎零标记 = 任务直白、做没做一目了然。**taskgen 含义:calc 类任务需要
在指令里明确"保存并可见确认",impress/thunderbird 类需降低隐式要求密度。**

**难度信号**:pass 中位 17 步 vs fail 中位 19 步 —— 失败**不是**步数爆炸型,
是"走完了但没走对"型,与步级"想完不做"发现同源。

## 事故:slug 冲突导致图片张冠李戴(2026-08-17 发现,追溯到 08-15)

**症状**:Bhqs 构建时 `--image-cache` 的硬链接抛 `SameFileError` —— 目标文件
已是源文件的硬链接。追下去发现是**图片目录被两条不同轨迹共用**。

**根因(双层,两层都漏)**:
1. **合并层**:`ostg` 的 slug 在**每个分片内唯一,合并成 `*-final` 池后不唯一**。
   全量排查 40 个任务池:分片池(v11-500-s0..s3、v11q2-500-s*、v9/v8big 各片)
   **全部 0 冲突**;只有合并池出问题——**v11-500-final 3 组、v11-500-recheck 4、
   recheck2 3、v500-all 4**。08-15 的 accept 门(`slug collisions across shards`)
   发现过 v11q2 的 5 组并做了 cull,**但 v11-500 是在那之前合并的,从未回补**。
2. **构建层**:`build.py` 用 slug 当图片目录名(假定唯一),第二条轨迹**静默覆盖**
   第一条的截图;而 `verify.py` 只验"图片存在且非空"——**被覆盖的图片依然存在**,
   所以这道门永远查不出来。

**实际损坏(B 与 Bs 两个语料,已训练)**:
| 冲突组 | 后果 |
|---|---|
| `campaign-brief-broken-links` | chrome/16d30a31(23 步)先写 → os/b132cf79(24 步)全覆盖:**chrome 那条 23 个样本全部配错图** |
| `retainer-trust-balance-sheet` | calc/15bcfb49(11 步)→ calc/318c3734(6 步)覆盖前 6:**15bcfb49 前 6 个样本配错图** |
| `retainer-deck-notes-to-handout` | 只 1 条过 checker,**无损坏** |

合计 **~29 / 5,586 样本(0.5%)** 的截图与文本不匹配。**已训练的 B、Bs、gb64o、
Bs-LoRA 各臂都含此缺陷**;量级远小于臂间差异(±1 任务 = 噪声),**不重训**,
但所有基于这些臂的结论都带这一句脚注。**Bhqs 起已修复**。

**三层防线(已固化,ostg@1df5c975)**:
1. `build.py`:冲突 slug 的图片目录加 task_id 后缀(`<slug>-<tid8>`),非冲突项
   保持裸 slug 以维持 `--image-cache` 命中;`report.json` 记 `slug_collisions`。
2. `verify.py`:**任一图片目录被两个 task_id 引用即硬失败**(exit 1,
   `pipeline.sh` 的 `set -e` 直接中止)。对旧语料实测精确报出 2 处。
3. `census.py --tasks`:构建前打印池级 slug 唯一性(`SLUG-COLLISION` 行),
   `pipeline.sh` 自动传 `--tasks`。

**教训**:存在性检查 ≠ 正确性检查。凡是"用业务字段当文件路径"的地方都要在
写入层假定冲突会发生(唯一化 + 事后交叉引用检查),不能依赖上游保证唯一。

**全量语料体检(2026-08-17,新 verify 扫全部 7 个已建语料)**:
| 语料 | 样本 | 共享图片目录 |
|---|---|---|
| sft-B-v11100 | 1,181 | 0 ✓ |
| **sft-B-v11500** | 4,478 | **2 ⚠** |
| sft-Btc2048-v11100 | 1,167 | 0 ✓ |
| **sft-Btc2048-v11500** | 4,419 | **2 ⚠** |
| sft-q38-v11100 | 1,196 | 0 ✓ |
| **sft-Bhqs-v11100 / -v11500**(修复后) | 1,114 / 4,253 | **0 / 0 ✓** |

损伤范围**就是** v11-500 那两组冲突(各 ~29 样本 / 0.5%),arm A 用的 v11-100
系池全部干净,**无更大隐藏问题**。体检命令固化为
`for d in out/sft-*/; do $P -m ostg.sft.verify $d; done`(RUNBOOK §四道门)。

**另一处顺带补的固化缺口**:`train_swift.jsonl` 的格式转换此前是手工一行命令
(违反"数据生成代码先入 git"),已固化为 `ostg.sft.to_swift` 并串入 pipeline;
**用旧产物做逐字节回归,4,419 行完全一致**,确认规则复刻无偏差。

### Bhqs 语料定稿与赎回口径(2026-08-17)

**赎回是三阶段口径,引用时必须说清是哪一阶段**:
**83 条原始赎回**(仲裁定 checker_bug_strict,conf≥1)→ **56 条过质量门**
(Qwen v2req ≥9 / Opus ≥8 / 无硬缺陷 / 无终端弱步;刷掉的 27 条里 15 条卡在
"Qwen 给 8 分"、9 条卡在"Opus 给 7 分",都是差一档,非硬缺陷)→
**54 条最终进语料**(build 的 whole-traj-filter 又刷掉 2 条 cap-hit/无 DONE)。

**Bhqs = 304 轨迹 / 5,367 样本**(cap 2048)。与 Bs(312 / 5,586)的关系:
**共有 250、剔除 62、赎回 54 = 换血 32%**,规模只小 3.9%。

分域换血率极不均匀,**净数字会骗人**:
| 域 | B→Bhqs | 净变 | 保留 | 剔除 | 赎回 | 换血率 |
|---|---|---|---|---|---|---|
| libreoffice_calc | 44→40 | −4 | 25 | 19 | 15 | **58%** |
| libreoffice_impress | 21→19 | −2 | 12 | 9 | 7 | **57%** |
| thunderbird | 9→9 | **±0** | 7 | 2 | 2 | **36%** |
| os | 56→59 | +3 | 52 | 4 | 7 | 17% |
| vlc | 4→4 | ±0 | 4 | 0 | 0 | **0%** |

thunderbird 净变 0 却换掉了 4 条 —— **只看总数会以为没动过**。calc/impress
是手术台:checker 最易写错(舍入/行偏移/枚举)与判官标记最多("算完没保存")
两股力量同时作用,一进一出几乎抵消。vlc/os/vs_code 换血最少:任务"做没做成
一眼可见",两个裁判都不容易错。

**质量方向**:Bhqs 难度均值 3.04 vs Bs 2.95、难≥4 占比 35% vs 33% —— **筛完
更难,不是更简单**;中途循环样本 15→7 减半,恢复型样本 198→213,超长风险
13→7 减半。

**仲裁协议差异**:Bhqs 建立在 **v1 仲裁**名单上。全量 v2 重裁后名单差异为
**1 条该撤 + 6 条该加 = 7 条 / 304 = 2.3%**,远小于臂间差异,**不重建**;
v2 版名单存于 `out/v2only_*`,下一轮语料直接用。

## 终止信号:SFT 训掉了显式 terminate(2026-08-17)

**DONE 的三条来路**(读 `mm_agents/qwen/actions.py:363-377`,用仓库自己的
`iter_tool_call_params` 重放判定,不靠正则):
```
for params in iter_tool_call_params(response): process(params)
if not pyautogui_code:                      # 没产生任何动作码
    append("FAIL" if infeasible_response else "DONE")
```
1. `terminate` 工具调用(status≠fail)→ DONE
2. `call_user`(向用户求助)→ **也判 DONE**,episode 结束并按当前状态打分
3. **无动作码 → 兜底判 DONE**:模型只写散文、或调用格式坏掉、或动作名未处理

**跨模型/跨任务集实测(同一 harness)**:
| 模型 | 任务集 | 通过 | terminate | 散文兜底 | call_user | ≥50 步 |
|---|---|---|---|---|---|---|
| Qwen3.6-27B | 真实 Verified 361 | 45% | **82%** | 4% | 9% | 18% |
| Qwen3.6-27B | **生成任务 v11-100** | 39% | **96%** | 0% | 4% | 48% |
| Qwen3.8-27B | **同一批 v11-100** | 70% | **13%** | **72%** | 15% | 8% |
| Qwen3.8-27B | 生成任务 v11-500 | 56% | 13% | 68% | 18% | 9% |
| 4B base | eval-50 | 38% | **100%** | 0% | 0% | 28% |
| 4B SFT(gb64o) | eval-50 | 43% | **0%** | **81%** | 16% | 34% |

**结论(注意变量归属)**:
- **不是任务集的问题**:3.6 和 3.8 跑同一批 v11-100,terminate 率 96% vs 13%
  —— **是教师模型版本**;3.8 自己就改用散文让 harness 兜底。
  (限定:3.6 那两批是 think-nopreserve,3.8 是 preserve,serving 也差一项。)
- **最干净的一对无混杂**:4B base 与 SFT 后的 4B 跑同一批 eval-50、同一 serving,
  **terminate 100% → 0%**,散文 0% → 81%,撞上限 28% → 34%。
  **学生忠实继承了教师的散文终止风格,把自己原有的显式终止能力训没了。**
- **`call_user` 占 14-18% 且通过率最低**(48.3% vs terminate 69.1% / 散文 65.9%):
  语料在教"卡住时喊人,而且这算正常结束"。
- **未爆的雷**:`looks_infeasible_response` 是对整段 response 的子串匹配
  ("infeasible/not possible/impossible/cannot be completed"…),**think 里随口
  一句就能把兜底从 DONE 翻成 FAIL**。实测目前 1/465(0.3%)命中。

**因此 cap 豁免终止步**(build,2026-08-17):终止监督只占 13-15% 的显式信号,
是最不能再损失的部分;verify 增加 `TERMINAL-STEP-MISSING` 硬检查(末步目标
被 cap 摘掉即 exit 1),实测抓出 1 条(vs_code/7de2a092,26 步里第 12 和 26 步
都被摘)。**Phase-3 重写的首要目标随之改为:把末步改写成"简短确认 +
显式 terminate",不动其余轨迹** —— 比删数据划算,且直击 eval 的早停/晚停失败。

### 缺陷:auto 截尾把"真动作步"当成空转砍掉(2026-08-17 出包后审查发现)

Bhqs-2-terminal 出包后按"**终止画面是否等于 checker 验收的画面**"逐条复核 33 条
被截尾的轨迹(`--tail-policy auto --stall-min 2`),结果:

| 判定 | 条数 | 含义 |
|---|---|---|
| 终止画面 == 原末步画面 | 8 | 砍掉的都是视觉惰性步,**安全** |
| 画面不同、但砍掉的全是 WAIT/screenshot | 12 | 画面差异来自光标/时钟/渲染,**基本无害** |
| **画面不同 且 砍掉了真动作** | **13** | **在教模型提前停手,正是要消灭的病** |

13 条 = 语料的 3.6%,共砍掉 **109 个真动作**。最重的:
`chrome/1abda5b3` 留 19/31 砍 30 个动作、`chrome/6116349d` 留 5/12 砍 22 个、
`chrome/a2d92df4` 留 2/11 砍 16 个、`thunderbird/c9be16a6` 留 21/29 砍 13 个。

**根因在 `terminalfix.stalled_tail()` 的两个判据**:
1. `waited = any(a.strip() == "WAIT" for a in s.actions)` —— **"含有 WAIT"被当成
   "什么都没干"**。agent 的习惯是「点一下 + 等一下」,于是"点击后等待"的生产性步
   被判死,倒着走的循环一路吃穿整条轨迹(`a2d92df4` 因此只剩 2 步)。
   应为 `all(is_noop(a) for a in s.actions)`。
2. `same` 用 `screenshot[i] == screenshot[i-1]` 判停滞。**这条是对的**:`traj.py:44`
   注明截图拍摄于该步**最后一个动作之后**,所以等式指控的正是该步自己,不存在
   差一位(初版本条曾写成"差一位",错误,已更正)。它唯一的残余风险是
   "画面没变"≠"没干活"(写文件、后台保存不改画面),由下面的硬门兜住。

**归因实测(`corpusaudit` 记录每个被判死的步是哪条判据触发)**:
`all_noop 56 / same_screen 10 / **waited_only 41**` —— **41 个既非空动作、
画面也确实变了的生产性步,只因为"动作列表里含一个 WAIT"被判死**。
缺陷完全落在判据 1,判据 2 无责。

**更根本的问题是没有事后硬门**:整个流程没有任何一步验证"我们让模型停下的那个
画面,就是 checker 打过分的那个画面"。启发式可以错,硬门不该缺 —— 与 slug 冲突
事故同一教训:**存在性检查 ≠ 正确性检查**。

**审查方法本身也踩了一次坑(记录以免重犯)**:第一版审查脚本按 task_id 在
`results_generated/` 下扫目录、`setdefault` 取第一个命中,而**同一 task_id 在多个
model/run 下都有轨迹**(`results_generated/<model>/<run>/<domain>/<task_id>`),
于是拿 `qwen36-27b-bf16-local` 的轨迹去比 `qwen38-27b-local` 的语料,报出"28 条
异常、1257 个动作被删"的假结论。改为按 `meta['run']` 定位 + 用 `orig_steps` 校验
步数后才得到上表。**任何按 task_id 找轨迹的脚本都必须同时锁定 model 和 run。**

### 修复(2026-08-17 当日):判据改对 + 加硬门

**代码改动(ostg@4ca4cae2 / 后续)**:

| 位置 | 改动 | 理由 |
|---|---|---|
| `stalled_tail()` | `any(a=="WAIT")` → `all(is_noop(a))` | "含一个 WAIT"≠"什么都没干";agent 的固有习惯就是「点一下+等一下」 |
| `decide_keep_to()`(新) | 切点定了之后**强制比对终止步截图与原末步截图的 md5**,不一致整条退回 last-only,记 `tail_gate="reverted"` | checker 打分打的是原末步状态;只有画面逐字节相同,截尾才是可证安全的 |
| `--recompute-tails`(新) | 只重算 keep_to:位置没动的行保留教师原文,动了的才回炉 | 全量重写会把 300+ 条本来没问题的目标静默改掉,而且浪费 |
| `ask_anthropic/ask_qwen` | 返回 `(reason, error)`,错误写进 `teacher_error` 并计数 | 见下 |

**顺带挖出的第二个静默失败**:`ask_anthropic` 原本把异常吞掉返回空串,而
`canonical_response("")` 会替换成兜底句。于是**漏传 `--model`(anthropic_cfg
原样透传模型名)会让整批理由变成同一句话,而日志里一切正常**。首次重跑就踩中:
7 条理由全空。现在错误会 surface,且**空理由本身被判为 stale,下次重跑自动回炉**。

**两个 pipeline 陷阱(写进 RUNBOOK)**:
- `--tasks` 传 **run 目录**,不是 `examples/`——`load_instruction` 自己拼 `examples/`。
- `--backend anthropic` **必须**显式给 `--model claude-opus-5`。

**审计脚本自己的两个 bug(都会造成假警报,记下来免得重犯)**:
1. 图片路径是**相对于各自 build 目录**的(ship 时才转绝对),按进程 cwd 解析
   → 报"60,903 张全部缺失"。
2. 图片目录归属键用了**相对路径** → 两个 pool 各自 build 目录下的同名相对路径
   被判成冲突,给 Bs 报出 281 处不存在的"共享目录"。**必须用绝对路径做键。**

### 多智能体独立审计又挖出两个更严重的问题(2026-08-17 晚)

六个审计员各自从原始数据重新推导,**独立复现了截尾诊断**(多人各自定位到
`terminalfix.py` 同一行),同时报出两个我没测到的缺陷。两个我都亲自复核过。

#### 缺陷 A:教师看的是模型看不到的那一帧

`build.py:271` 定义观察映射:`obs_files = [init] + [s.screenshot for s in steps[:-1]]`,
即**第 k 步的输入观察 = 第 k−1 步动作之后的截图**。而 `terminalfix` 交给教师的是
`steps[keep_to-1].screenshot` —— **该步自己动作之后的那一帧,超前了一帧**。

后果:**教师引用的证据,模型在必须决定"要不要停"的那一刻根本看不见**,而语料
把这句话当成目标去训——等于在教它凭空断言。截尾的轨迹上两帧是完全不同的画面。
审计员抽查 22 条末步理由,**5 条被画面直接证伪**;另有一类反复出现的
"the file is saved",而 `ctrl+s` 要么在被砍掉的尾巴里、要么在超前的那一帧里。

**修复**:新增 `observation_at(td, steps, k)`,严格复刻 build 的映射
(k=1 用 `initial_state.png`,否则 `steps[k-2].screenshot`)。

#### 缺陷 B:被污染的像素靠 `--image-cache` 传播

slug 冲突事故的修复是给图片目录加 `<slug>-<tid8>` 消歧,**但那只对新建的目录生效**。
Bhqs2t 是带 `--image-cache` 从旧 build 目录拷图建起来的,于是**旧目录里已经被
覆盖过的错图被原样搬进了新语料** —— 目录名唯一、`verify` 全绿,像素却是别的任务的。

审计员用 `mm_agents.qwen.images.process_image` 从原始轨迹重新编码逐字节比对,报
Bs / Bhqs-1 / Bhqs-2t **三个语料各有同一组 29 张错图**。我只抽查了每条轨迹第一步的
样本(297 张)就复现了 2 张(`chrome/16d30a31`、`libreoffice_calc/15bcfb49`),
**指控成立**;完整数量以 `--verify-pixels` 全量跑的结果为准。

**教训升级**:`存在性检查 ≠ 正确性检查 ≠ 归属检查`。目录归属唯一也不能证明像素对,
因为污染可以从上一代语料继承。**新增 `corpusaudit --verify-pixels`**:每张图从原始
轨迹重新编码比对字节,这是唯一能抓住这类问题的检查。重建 Bhqs2t 时**不再使用
`--image-cache`**,直接切断传播链。

#### 顺带修正的设计:三条修复路径,而不是一刀切重写

原做法把全部 376 条末步一律替换成合成结尾,其中**54 条本来就是正确的
terminate(success)** —— 那是倒退。改成按最小干预分流:

| 原始结尾 | 处理 | 条数 |
|---|---|---|
| 已是 terminate(success) 且未截尾 | **完全不动**(行里 `response: null`,build 跳过) | 54 |
| 完整的散文结尾 | **保留教师原文,只补上缺的 tool call** | 246 |
| `call_user` / 截尾 / 末步是真动作 / 踩 infeasible 触发词 | 教师重写 | ~60 |

**教师调用从 362 次降到约 60 次**,318 条保留自己真实的结尾文字。

另外:自然产生的 68 条 terminate 结尾**100% 在 `</think>` 与 `<tool_call>` 之间有一句
可见结论**,语料里其他目标也有 75.3% 有;而初版注入的结尾**一句都没有**,使末步成为
全语料唯一的形状。教师现在产出 `thinking` + `statement` 两段,拼成自然形状。
