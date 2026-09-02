# PLAN-20260901 严格语料:两道闸 + mixA 组成

> 用户令 2026-09-01。**跑完当前判官全量、检查过再执行**,本文件只是计划。
> 上游发现见 `sft/FAILURE_ANATOMY.md §0`;判官体系见 `JUDGING.md`。

## 0 为什么做这件事

eval 侧实测(mixb4b 全 100 题,冻结 50 + 样本外 50):

| 结局 | 题数 |
|---|---|
| 成功 | 51 |
| 撞 50 步上限 | 25 |
| **假 DONE(宣告完成、判据不通过)** | **20** |
| 主动 FAIL | 4 |

假 DONE 的机制是**核对代理指标而非验收条件** —— 三例实读:确认"文件存在"
(而非内容正确)、"zip 存在"(而非装对了文件)、"查到了教程"(而非改了
`~/.vimrc`)。三例的 think 推理都正确、证据都充分,**不是能力不足,是宣告
完成的门槛太低**。

语料侧对得上:旧判官准入的轨迹里,**18.4% 的要求是 `evidence: inferred`**
(推断满足,没有任何一帧看到结果)。

### 已经排除的一个假说(2026-09-01 实测)

"判官 prompt 太松"**不成立**。把自撰 prompt(2650 字符)换成 OpenWebRL 官方
轨迹判官原文(`JUDGE_SYSTEM_PROMPT_ACTION_HISTORY`,1764 字符,仅 6 处
web->desktop 名词替换)、判决契约从 requirement 逐条核对简化成二元
SUCCESS/NOT SUCCESS,**同一模型(claude-opus-5)、同样 flags,716 条全量只翻转
4.1%**(29 条),反向翻转 0 条。

| 域 | 准入 | 翻转 | 翻转率 |
|---|---|---|---|
| multi_apps | 399 | 20 | 5.0% |
| thunderbird | 10 | 1 | 10.0% |
| vs_code | 32 | 2 | 6.2% |
| vlc | 17 | 1 | 5.9% |
| libreoffice_impress | 40 | 2 | 5.0% |
| libreoffice_calc | 70 | 2 | 2.9% |
| libreoffice_writer | 35 | 1 | 2.9% |
| chrome / gimp / os | 112 | 0 | 0.0% |

**29 条翻转都是实质性的**,抓的是官方 prompt 那条 any-part-fails 规则:
任务有多个部分、其中一部分没做到而旧判官给了 success。实读几例:
五张幻灯片只有第 5 张的备注真正落进占位符;题面要求"两样都还原"实际只还原
一样;题面明写 `wc -l` 结果必须是 14 而终端显示 17;要求新增一张幻灯片实际是
往已有幻灯片上打字。**旧判官的 j_note 里有几条自己就写着 "only inferred"、
"typed id..." —— 它看见了同样的缺口,但仍判成功。**

结论:**"判官太松"方向对,量级不对 —— 只松 4.1%。** 语料里的假 DONE 不是
判官放水放进来的,是**教师轨迹本身就"做完但不验证"**,判官看到的证据也确实
支持"做完了"。真正的筛选压力必须落在 WebSTAR 步级那一闸。

## 1 两道闸

```
旧语料 v16 准入 716 条(去重后)
   │
   ├─ 闸一  严格判官:verdict == SUCCESS
   │        OpenWebRL 官方 prompt(逐字 + 6 处名词替换),二元契约
   │
   └─ 闸二  WebSTAR 步级过滤:逐 step 决定该 target 留不留
            score > 5 保留;<= 5 丢掉该 target,但**仍留在后续步的 history 里**
```

闸一在轨迹级,闸二在步级 —— 一条通过闸一的轨迹,里面仍可能有该丢的步。

### 取消了证据闸(用户令 2026-09-01 上午)—— ⚠ 当日下午已推翻,见 §8


原计划在两闸之间加一道 `evidence == seen`。**取消,理由是那个信号本身没有
外部验证** —— `evidence` 是判官自己填的字段,没有 checker 或人工复核支撑,
拿它去砍语料等于用一个未经检验的判断替换另一个。

代价也算过:按旧数据,`seen` 闸会把 716 条砍到 **222 条**,而其中 241 条是
**因为用的是旧 schema、根本没有这个字段**而被误杀,不是真的推断不足。
用一个自身可能错、且覆盖不全的信号砍掉六成语料,风险大于收益。

## 2 判官契约(已落地)

`VERDICT_TOOL` 只有两个字段,与官方 prompt 的结尾句逐字对应:

```python
"reasoning": {"type": "string"},                       # 先解释
"verdict":   {"enum": ["SUCCESS", "NOT SUCCESS"]},     # 再判决
```

落盘时归一化成既有的 `success`/`failure`,原判词另存 `j_verdict_raw`。
`strongjudge.py` 里 SYSTEM 的溯源注释记着官方 sha256
`2d9a77fb…`(1764 字符)与本份 `f817fe52…`(1781 字符)。

**连带影响**:`curate16.admitted()` 仍要求"必须有 requirement 列表且每条都
完成",新格式的行会被它全拒。用新判官筛语料前必须把它改成只看
`j_verdict == "success"`。

## 3 语料组成:这次用 mixA

**mixA = 旧 v11(已训过、效果已知的那 360 条) + 新 v16(过三道闸之后)**

选 mixA 不选 mixB 的理由:旧 v11 那 360 条是**已经跑过、分数已知**的基线,
把它固定住,新 v16 那部分的过滤效果才读得出来。

⚠ 已知混淆:旧 v11 那半是带 terminal-rewrite 建的(5.6% 的样本以
`terminate` 结尾,其余语料是 0.3%),还过了 whole-traj-filter。这是既有事实,
不是本次引入的,但报结果时要披露。

## 4 各闸之后的预期规模(待实测填)

| 阶段 | 轨迹 | 样本 | 备注 |
|---|---|---|---|
| v16 判官准入(旧) | 716 | — | 去重后 |
| curate16 之后(现状) | 554 | 13,372 | 当前 mixC 的语料 |
| 闸一 严格判官 SUCCESS | **686** | — | 716 条翻转 29 条(4.1%),实测 |
| 闸二 WebSTAR 步级 | 同上 | **待测** | 307 行 pilot 保留 254/307 = 82.7%,已被标注作废,不可外推 |
| + 旧 v11 360 条 | +360 | +6,474 | 固定不动 |

## 5 执行顺序

1. **等当前全量判官跑完**(717 条,新 prompt + 二元 + opus-5),核对翻转率与
   逐域分布 —— 已在跑。
2. 改 `curate16`:准入只看 `j_verdict == "success"`,不再要求 requirement 列表。
3. 闸一出通过清单与规模。
4. **WebSTAR 步级过滤按它自己的规矩走**:README 写死
   `Status: IMPLEMENTED / CALIBRATION PENDING`,
   "**The next allowed operation is the 200-step calibration. Full grading
   remains blocked**",且那次 307 行的保留率被标注为已作废
   ("must not be reported as the current retention estimate")。
   **先做 200 步标定,不直接全量。**
5. 建 mixA 语料,ship,起训练臂。

## 6 未决

- **闸一几乎不筛**:全量实测翻转 4.1%,716 -> 686,只掉 29 条。换句话说
  这一轮的严格判官**基本是换了个 prompt 的同一批准入**,真正的筛选压力
  全落在 WebSTAR 步级那一闸上。这不是坏事(步级本来就是更细的刀),但
  要清楚:**"严格版判官"这个名字名不副实,它只是口径更规范,不更严**。
- WebSTAR 打分用 `gpt-5.6-luna`(ppapi),轨迹级判官用 `claude-opus-5` ——
  两个不同模型分管两级,是否要统一,待定。

## 7 WebSTAR prompt 版本(2026-09-01 已复现验证)

**主策略是 `policy_official_revised.json`,不是 `prompt.py` 里那份。**

| policy | 版本 | 状态 |
|---|---|---|
| `policy_v1.json` + `prompt.py` | webstar-filter-v1 / paper-four-stage v2 | **historical**,已被取代 |
| **`policy_official_revised.json`** | webstar-official-revised-desktop-v1 | **PRIMARY**,calibration-pending |
| `policy_official_equal_budget.json` | …-equal-budget-… | experimental,自述 "not an exact WebSTAR reproduction" |

溯源链已端到端验证:

```
github.com/yifei-he/WebSTAR @ d5c2a34cb7ff193a85c144fdd91f48a0e716da86
  clone 到 /Users/knight/uw/computeragent/WebSTAR (与 OpenWebRL 并列,不在任何仓库内)
  step_eval/gpt_prompts.py:105-192 :: GPT_STEP_JUDGE_REVISED
      官方 sha256 240c77aca3c08b4f862c48d91f35a8a3a22303554eb5f3d584a2df39cb2f7906  ✅
  ↓ 5 处断言替换(allow ordered desktop action bundle / replace browser action
    space / remove WebVoyager-only restrictions / adapt final answer to explicit
    DONE / rename web element to UI element)
  适配后 sha256 3cd1d4350f1f6b59f69f0b9fc44ad220b8b72beb34ec711eae5293d40768ee69  ✅
      6303 字符(**去掉尾部换行之后**;grade_steps.py:292 读取时 .strip())
```

产物:`/private/tmp/webstar-prompt-20260901/{official_revised_desktop.txt,
provenance.json,official_to_desktop.diff}`。

⚠ **跑 grade_steps 必须显式传 `--prompt-file`**,否则按其 CLI 默认
("omitted uses paper-four-stage v2")会**静默退回已被取代的旧版**。

## 8 证据闸恢复:strict-340(用户令 2026-09-01 下午)

§1 "取消证据闸"当天下午被推翻。用户原话:"我要求的是 340 准入,用 strict 规则,
我现在在筛数据质量。"

**口径**(`curate16 --strict`,ostg@5c8594f2):默认准入规则之上,再要求每条
requirement 都有截图为证 —— `j_inferred == 0`、`j_cannot_tell == 0`、
`j_crit_fail` 假、`j_evidence_violations == 0`、`j_derived >= 10`。

| 口径 | 准入 | 占 1374 |
|---|---|---|
| curate16 默认(只看 verdict + 每条 requirement done) | 645 | 46.9% |
| **curate16 --strict** | **340** | **24.7%** |
| §4 计划里的"闸一" | 686 | — |

按难度:d1 168/468 = 36%,d2 137/465 = 29%,**d3 只有 35/441 = 8%**。

§1 反对证据闸的两条理由仍然成立(evidence 是判官自填、无外部验证;旧 schema
的行会被误杀),但用户判定筛质量优先。**报结果时要把这一点当已知偏置披露**:
strict 语料对推断型证据的任务系统性欠采样,尤其是 d3。

### 语料组成(mixA,实测)

| 来源 | 轨迹 | 步数 | result_dir |
|---|---|---|---|
| v11-100-t1-20260814 | 75 | 1363 | qwen38-27b-local/v11-100-t1-20260814 |
| v11-500-t1ms50-20260814 | 287 | 5145 | qwen38-27b-local/v11-500-t1ms50-20260814 |
| v16-main-1 (strict) | 300 | 6386 | qwen38-27b-local/v16-main-1 |
| v16-pilot-200 (strict) | 40 | 984 | qwen38-27b-local/v16-pilot-200 |
| **合计** | **702** | **13878** | 重叠 0 |

v11 那 362 条沿用既有语料(带 terminal-rewrite,§3 已披露的混淆),v16 那 340 条
用 `ostg/sft/tools/build-v16-strict.sh` 中性重建(`--image-max 10 --fold-size 1 --think-cap 2048
--whole-traj-filter`)。

### 标定被跳过(用户令 2026-09-01 下午)

WebSTAR README 写死 `The next allowed operation is the 200-step calibration.
Full grading remains blocked`。用户令直接对这 702 条全量打分,跳过 200 步标定
与双 pass。**这是明知的偏离**:没有判官一致性、假保留率、终止步行为、逐域保留率
的事前检查,阈值 `score > 5` 未经本语料标定。报结果时必须披露。

### 闸二执行口径:luna 单 pass(用户令 2026-09-01 下午)

| | 判官 | 规模 | 保留率 |
|---|---|---|---|
| **p1 决策用** | `gpt-5.6-luna` | 13203 条 target,全部完成 | **55.0%** |
| p2 仅作证据 | `claude-opus-5` | 4190 条(31%,事故中断) | 74.9% |

**双 pass 被否**:两个判官在同一批 3311 条上判定一致率仅 70.8%,
`decide_steps --require-passes 2` 会把分歧的 22.6% 全标 `review`,
而 `filter_copy.py:50` 拒绝任何未解决的 review —— 换算约 2900 条要逐条人裁,
不现实。**opus 那遍只作为判官一致性证据写进文档,不参与删留决策。**

判官分歧的方向是单边的:luna 丢 / opus 留 占 22.6%,反方向仅 5.0%,
分差均值 +0.83、中位 0 —— **opus 系统性比 luna 松 19pp**,差异集中在
骑在阈值线上的 5/6 分那批。这说明 `score > 5` 这个阈值对判官选择极其敏感,
是跳过 200 步标定的直接代价,报结果必须披露。

v11 与 v16 两半都过滤(用户令):13203 → 约 7260 条 target。

### 出数据的前置(WebSTAR README 的硬约束)

1. `filter_copy` **不复制也不重编码图片**,只把路径重映射到 `--image-root NAME=PATH`
   给的**已存在的** GPFS 根目录。所以顺序是**先传图片上 Tillicum,再跑 filter_copy**。
2. `decide_steps` 会把三类标 `review`,必须清零 filter_copy 才肯出数据:
   两 pass 分歧(单 pass 不触发)、终止步没有显式 DONE/terminate、终止步 score<=5。
   后两条单 pass 也会产生,702 个终止步里落进 review 的要逐条裁。
3. `--expected-rows` 默认 18576 是 MixB 的数,本语料要传 13203。

## 9 执行记录(2026-09-01 傍晚)

### 漏做终止规范化,已补

首次 build v16 时漏传 `--terminal-rewrite`,`verify` 又没带 `--require-terminate`
(不带就不检查,却照样打印 `0 endings not terminate(success)` —— 这句被我当成
证据引用过)。后果不是 review 多几条,是整个 v16 半区没有终止示范。

**重建前后(325 条进语料的轨迹末步)**:

| 末步动作 | 重建前 | 重建后 |
|---|---|---|
| NO_ACTION_TAG(纯散文) | 299 | 0 |
| call_user | 14 | 0 |
| **terminate** | **12 = 3.7%** | **325 = 100%** |

项目记录的全局基线是 13-15% 带显式 terminate,这批 3.7% 更低。

**为什么会这样(机制,与 computeragent-17 逐行核过)**:模型末步根本不调工具,
只输出散文;`mm_agents/qwen/actions.py:416` 的 `if not pyautogui_code:` 让
harness 追加 `"DONE"`。**轨迹里的 DONE 是 harness 贴的标签,不是模型输出的动作**,
所以转成语料时没有 tool_call 可写 —— 忠实转换,不是 bug。另两条同源:
`:159 answer → DONE`、`:379 call_user → FAIL/DONE`。

**代价已在 eval 侧量出**(末步 response 是否含显式 terminate):

| 臂 | 任务 | 显式 terminate |
|---|---|---|
| base9b 未微调 | 259 | **69%** |
| base4b 未微调 | 247 | **75%** |
| mixa9b | 100 | 19% |
| mixb9bw20 | 49 | 4% |
| mixb9b | 100 | 2% |
| mixb4b | 50 | **0%** |

模型本来会说 done,是语料把它教没的。mixa9b 的 19% 明显高于 mixb 系,因为它
约 1/3 语料来自 r5 系(过了 terminalfix,末步 100% terminate)。

**mixA 的 v11 半区不用重做**:`sft-Bhqs2tr5nocapimg10-v11{100,500}` 实测
75/75、287/287 全部显式 terminate。散文结尾的是 mixB 用的 v11new 那一代,
不是 r5 系。

### 判官的分对末步不构成风险(实测)

担心"打分把末步判低分删掉"——**相反,末步是全语料分最高的一批**:

| | n | 均值 | 中位 | 保留(>5) |
|---|---|---|---|---|
| 末步 | 687 | **9.00** | 10 | **92.9%** |
| 非末步 | 12516 | 5.37 | 6 | 52.9% |

原因是适配 prompt 的五处断言替换里有一条 "adapt final answer to explicit DONE",
判官被告知末步就该是收尾。`decide_steps` 另有一层保护:终止步 score<=5 不 drop,
标 `review` 待裁。

### 决策定稿

| | 条数 |
|---|---|
| keep | **7311**(含 49 条按策略保留的末步) |
| drop | 5888 |
| review | 0 |
| 打分后被 terminalfix 截尾、已不在语料 | 4 |

**末步 687/687 全部 keep,且 687 条全部带 terminate。**

过滤前后动作分布(动作次数,15267 → 8621,整体留存 56%):

| 动作 | 前 | 占比 | 后 | 占比 | 留存 |
|---|---|---|---|---|---|
| left_click | 4901 | 32.1% | 2609 | 30.3% | 53% |
| key | 3930 | 25.7% | 2867 | 33.3% | **73%** |
| type | 3375 | 22.1% | 1257 | 14.6% | **37%** |
| **terminate** | 687 | 4.5% | 687 | **8.0%** | **100%** |
| wait | 547 | 3.6% | 237 | 2.7% | 43% |
| screenshot | 425 | 2.8% | 132 | 1.5% | **31%** |
| double_click | 393 | 2.6% | 313 | 3.6% | 80% |

terminate 占比翻倍是因为它是唯一 100% 留存的动作。判官最不待见 `screenshot`
(31%)与 `type`(37%),最认 `key`(73%)。

### 两个已知代价,报结果必须披露

1. **687 个末步未经任何判官检验**。打分在 terminalfix 之前做,重写后的
   terminate 从未被打过分。走这条路是用户令(2026-09-01):"直接 keep 就好了,
   只改了末步"。格式经 `verify --require-terminate` 全绿,内容质量无判官背书。
2. **`decide_steps` 的打分后 sha256 校验已删除**(用户令,不留开关)。理由:
   terminalfix 重写末步是流水线的正常一步,校验与既定流程冲突。代价是此后
   "打分后语料被改"不再有任何自动拦截。

### 判官口径

p1 `gpt-5.6-luna` 13203 条全量;p2 `claude-opus-5` 只跑到 4190 条(31%)即因
ppapi key 失效中断,**不参与决策**,仅作一致性证据:同一批 3311 条上判定一致
70.8%,opus 保留 74.9% vs luna 56.0% —— **opus 系统性松 19pp**,分歧单边
(luna 丢/opus 留 22.6%,反向 5.0%)。这是跳过 200 步标定的直接代价。

## 10 语料出厂与训练臂(2026-09-01 夜)

### 产物

`/gpfs/scrubbed/jy050706/sft/data/mixa-webstar-v16strict/`

| 文件 | 内容 |
|---|---|
| `train_swift.jsonl` | **7311 行**(v11100 747 + v11500 2851 + v16main 3249 + v16pilot 464) |
| `step_decisions.final.jsonl` | 每个 source row 一条决策,含 reason 与 source(judge / manual_override / no_score) |
| `DATA_VERSION.json` · `FILTER_POLICY.json` · `SOURCE_FILES.sha256` · `retention_report.json` | filter_copy 自带的溯源 |
| `v16main/images` · `v16pilot/images` | v16 那半的图(5921 + 865 个文件);v11 那半复用既有的 `q38-Bhqs2t-r5nocapimg10-v11{100,500}/images`,一字节没传 |

**图片路径实测**:sbatch preflight 全量 stat,**58003 个引用 0 个未解析**。
(第一次 `filter_copy` 的 `--image-root` 误传成 `.../images`,而 samples 的相对
路径本就以 `images/` 开头,拼出 `images/images/...`。行数与内容全对、只有路径错 ——
正是"row counts lie"那类静默失效,靠远端 stat 才抓到。`--image-root` 传父目录。)

### 训练臂 mixaw9b(Slurm 271875)

| 项 | 值 |
|---|---|
| 模型 | `Qwen3.5-9B` |
| 数据 | mixa-webstar-v16strict,7311 样本 |
| lr / epochs | **3e-6** / **3** |
| 全局批 | **64** = 8卡 × per_device 1 × accum 8 |
| save_steps | **115**,limit 4 |
| 资源 | 4 节点 × 2 H200,400G,12h,排除 g018,估价 $86.40 |
| 其余 | zero2_offload / sdpa / bf16 / max_len 65536 / warmup 0.1 / wd 0.0 / `IMAGE_MAX_TOKEN_NUM=2048` / channel_loss on / preserve_thinking on —— 与 `img10-9b.sbatch` 逐字相同 |

**checkpoint 落点**:7311 / gb64 = 每 epoch 115 步(奇数),3 epoch 345 步。
115 的因数只有 1/5/23/115,**无法同时满足"硬整除"与"每 epoch 两个点位"**
(后者要 57.5)。用户 2026-09-01 裁定取 `save_steps=115`:整除 345,三个点位
正好压在 ep1/ep2/ep3 终点。既有规矩在 spe 为奇数时以硬整除优先,此例入册。

### 训练侧的连带变化(样本数少 44.6% 的后果)

被过滤的步不算 loss,但**仍留在后续步的上下文里**(label 置 -100,不是删数据)。
轨迹数不变,变的是每条轨迹的训练目标数:

| | 前 | 后 |
|---|---|---|
| 训练样本(目标步) | 13199 | **7311** |
| 每条轨迹目标步 均值/中位 | 19.2 / 17 | **10.6 / 9** |
| 一个目标步都不剩的轨迹 | — | **0** |
| 只剩末步的轨迹 | — | 3 |

**每 epoch 步数因此几乎减半**,`save_steps` / 调度总步数都要按新数重算 ——
沿用旧臂的 save_steps 会让 checkpoint 全部落错位置。

### 与 r5 基线的关系(报结果时的读法)

| | 样本前 | 样本后 | 留存 | 轨迹 |
|---|---|---|---|---|
| v11(r5,旧) | 6473 | 3598 | 55.6% | 362 |
| v16(新) | 6726 | 3713 | 55.2% | 325 |
| **mixA 合计** | 13199 | **7311** | 55.4% | 687 |
| 对照:r5 原样(a2 训过) | 6473 | — | 100% | 362 |

轨迹 +90%,样本只 +13% —— **新增的量基本被步级过滤吃掉**。所以这个臂测的
不是"数据更多",而是"同样多的数据、每一步都被判官筛过"。

⚠ **与 a2 不可直接归因**:r5 半区自己也被砍掉 44%,差异里同时含"加了 v16"与
"r5 变少了"两个变量。要拆开须再跑一个"只过滤 r5、不加 v16"的臂
(语料现成,按 `step_decisions.final.jsonl` 的 source_build 一筛即可)。

两半留存率几乎相同(55.6% vs 55.2%),说明**新语料的步级质量与旧的没有系统性差别**;
strict 卡的是轨迹级(1374 → 340),WebSTAR 卡的是步级,两道闸筛的是不同的东西。

### 过滤对动作分布的影响

动作次数 15267 → 8621(留存 56%):

| 动作 | 前 | 占比 | 后 | 占比 | 留存 |
|---|---|---|---|---|---|
| left_click | 4901 | 32.1% | 2609 | 30.3% | 53% |
| key | 3930 | 25.7% | 2867 | 33.3% | **73%** |
| type | 3375 | 22.1% | 1257 | 14.6% | **37%** |
| **terminate** | 687 | 4.5% | 687 | **8.0%** | **100%** |
| wait | 547 | 3.6% | 237 | 2.7% | 43% |
| screenshot | 425 | 2.8% | 132 | 1.5% | **31%** |
| double_click | 393 | 2.6% | 313 | 3.6% | 80% |

**终止示范的密度翻倍**(4.5% → 8.0%),因为 terminate 是唯一 100% 留存的动作。
若 mixa9b 那 19% 显式终止率确实来自 r5 的贡献,这是本臂最可预期的效果。
判官最不认 `screenshot`(31%)与 `type`(37%),最认 `key`(73%)。

### 271875 死因:`gen_meta` 让 Arrow 推出冲突 schema(已修,271889 重投)

第一次投的 271875 在 `datasets` 加载时死于

```
TypeError: Couldn't cast array of type string to null
datasets.exceptions.DatasetGenerationError
```

**不是 OOM,不是路径**(preflight 58003 张图零未解析)。是 `train_swift.jsonl`
里 v11 与 v16 两半的 `gen_meta.related_apps` 一边全空 `[]`、一边 `['chrome']`,
Arrow 按前一块推成 `list<null>`,读到后一块 cast 失败;`gen_meta.ostg` 同理
(v11 半区完全没这些键)。

**为什么 mixA-9b(08-30)混同样两代语料没炸**:那四份 `train_swift_abs.jsonl`
(v16-main / v16-pilot / r5nocapimg10-v11100 / -v11500)都是各自年代的 `to_swift`
转的,都只有 `[channel, images, messages]`,**根本没有 `gen_meta`**。
`gen_meta` 是 ostg@`5c6aea84`("v14 item 0: 生成坐标活到训练样本")加进
`to_swift.py` 的。这次 `filter_copy` import 的是 ostg-v16 的新 `to_swift`,
**第一次让 v11 那份旧 samples.jsonl 过新转换器** —— 旧 samples 没有
`meta.ostg`/`meta.related_apps`,写出来就是空壳,与 v16 的实值撞型。

`to_swift.py:63-70` 的注释 "VERIFIED 2026-08-26 … accepts the extra column
without error and then DROPS it" **只验了单一语料**。丢列发生在 schema 推断
之后;"null-valued fields rather than no key" 只管 dict 键缺失,不管
空 list 对字符串 list。**这条要进 DATA_PIPELINE 静默失效清单**:一路绿灯
(filter_copy 原子改名成功、preflight 全过),到 `datasets` 读文件才炸。

**本次修法**:合并时 `pop('gen_meta')`,7311 行只留 `[channel, images, messages]`,
远端校验 schema 一种。溯源信息在 `step_decisions.final.jsonl` 完整保留,
swift 训练只读 `messages`/`images`/`channel`,无损。

**未做的根治**(要改 `to_swift.py`,先给 diff):混合语料下 `gen_meta` 必须
类型稳定 —— 要么 `related_apps` 永远非空 list 或永远 null(不能一半空 list),
要么 `filter_copy` 路径不写 `gen_meta`。任何再走 `filter_copy` 的混合语料
在根治前都会踩同一坑。

### 为什么 mixaw9b 起步 loss 更低、token acc 更高(2026-09-01 夜,用户问)

同配方对照 img10-9b(r5 未过滤语料,同 9B/lr/gb):

| epoch≈ | mixaw9b loss/acc | img10-9b loss/acc |
|---|---|---|
| 0.01 | **0.53 / 0.85** | 0.78 / 0.78 |
| 0.19 | 0.55 / 0.83 | 0.56 / 0.83 |
| 0.26–0.30 | **0.46 / 0.86** | 0.60 / 0.81 |

**不是模型学得快,是目标变了。** 被删的步和留下的步**动作正文一样长(93 tok)**,
差的全在 `<think>`(token = 字符/3.5):

| | n | 目标总 tok | think | 正文 |
|---|---|---|---|---|
| 过滤前 | 13204 | 287 | 189 | 93 |
| keep | 7311 | **226** | **129** | 93 |
| drop | 5893 | 362 | 265 | 93 |

每一种动作内部都如此(left_click keep 137 / drop 273;key 87 / 204;screenshot 132 / 258)。
**判官系统性地给长思考打低分**,非末步 12517 条按 think 长度五等分,删除率单调上升:
Q1(5–28 tok)30% → Q5(232+)67%,判官均分 6.31 → 4.25。叠加两个效应:末步(程式化
教师结尾 + 固定 terminate 调用)占比 4.5% → 8%;短目标的 `key` 留 76%,长目标的
`type`/`screenshot` 只留 32% / 15%。

loss 是逐 token 均值:目标短 21%、think 短 32%,而长段推理正是未训练模型最难预测的
部分,所以**第一步就更低**。头 20 步差距收敛是 img10-9b 学会格式后追上;之后再拉开
(0.46 vs 0.60)是剩下的差异 —— 长推理 —— 一方有一方没有。

**两条读法,报结果时都要说**:
1. **各臂 loss 曲线从此不可横比**。mixaw9b 的低 loss 是选择效应,不是学得更好;
   只有 eval 能裁。
2. 这个过滤器实际是"短思考选择器"。它删掉的 Q5 那 67% 是教师在难屏幕上的长时间
   斟酌 —— 可能是绕路(README 想删的),也可能正是模型该学的恢复/推理示范。
   哪种为主,要看 eval 上撞上限与假 DONE 的变化,以及 K1 对照臂(IDEAS)。

### mixaw9b 的 eval 口径(2026-09-01 夜定):必须与 a2 同窗口 20/10

用户反问"之前两份数据混着训的结果也不好"。数字(RESULTS §5.30,eval-100):

| 臂 | 语料 | 评测窗口 | 通过 | 去 infeasible |
|---|---|---|---|---|
| a2 | r5 单独 | **20/10** | 61.0% | **65.5%** |
| mixb9b | v16 + v11new | 10/1 | 60.0% | 58.6% |
| mixa9b | v16 + q38 v11 rollout | 10/1 | 57.0% | 58.6% |
| base9b | — | 20/10 | 36.4% | 39.1% |

结论成立:两个 mix 顶多打平 a2(99 题配对 a2 只领先 mixb9b +2.0pp,且窗口不同)。
它们有一个**已量化的共同缺陷**(FAILURE_ANATOMY §11):两半语料的末步都是散文
(v16-main 88%、v11new-500 88%、v11new-all 100%),学生末步 72–97% 靠 harness 回退,
a2 是 100% 显式 terminate。mixaw9b 相对它们改了四处:v11 半区换成 r5(100% terminate)、
v16 半区补做 terminalfix(3.7% → 100%)、准入 strict 340 而非 554/716、加步级过滤。
前三处是修已测出的缺陷,第四处是新变量(且带"短思考选择器"副作用)。**"多一份数据
到底有没有用"至今没有一个干净的实验回答过** —— 之前的 mix 都被末步缺陷污染。

**eval 口径(2026-09-01 夜修订,依据 RESULTS §5.31 mixb9bw20)**:mixB-9b 同一份权重从
10/1 换到 20/10,分数 60 → 52(−8.0pp,去 infeasible −5.7pp);a2 在同窗口仍领先 +9.0pp
(去 infeasible +12.6pp,≈2.4σ)。两条结论:①a2 对 mixB 的领先**是真的,不是窗口**;
②**偏离训练窗口本身要付 6–8pp**(a1→a1h10 −6.1、mixb9b→w20 −8.0,两次同型)。
mixaw9b / mixbtf9b 训练窗口都是 10/1,所以**两个窗口各跑一次 eval100**(同权重同 serve,
链表两行 XWIN 不同):10/1 对 mixb9b 公平,20/10 对 a2 公平。窗口不改变 think 长度与结束
方式(295 vs 304 tok、DONE 回退 72 vs 73),两次之差只反映窗口。只跑 20/10 会先付错配
再比 a2,低估;只跑 10/1 与 a2 不可比。排不排、排在哪仍由用户令。要拆"加数据"与"步级过滤",
再跑 IDEAS K1(只过滤 r5)。

## 11 对照臂 mixbtf9b:mixB 同一份语料,只补终止规范化(用户令 2026-09-01 夜)

用户问:"把 mixb9b 的数据不带 step filter、只加 terminalfix,训一个新的 9B 看效果。"
这是拆变量的干净对照:与 mixb9b 同语料同配方,唯一变量 = 末步。

**语料重建(与 08-30 的 `out/sft/mix-*` 构建逐项对齐:img10 / fold 1 / `--include`
准入名单 / 无 think-cap,只加 `--terminal-rewrite`)**:

| 份 | 轨迹 | 行(前 → 后) | terminalfix(append / already / rewrite) | 末步 terminate(前 → 后) |
|---|---|---|---|---|
| v16-main | 485 | 11678 → 11670 | 423 / 22 / 40 | 24 → **485** |
| v16-pilot | 69 | 1694 → 1694 | 63 / 2 / 4 | 2 → **69** |
| v11new-500 | 246 | 4265 → 4259 | 216 / 13 / 17 | 15 → **246** |
| v11new-all | 66 | 939 → 937 | 65 / 0 / 1 | 0 → **66** |
| **合计** | **866** | **18576 → 18560** | 767 / 37 / 62,**0 失败** | **41 → 866** |

−16 行是 `keep_to` 截掉的停滞尾巴。`verify --require-terminate` 四份全绿。图片一张没传:
重建只换末步文本,图片与原构建逐字节相同,jsonl 里的路径指回 `data/{v16-main,…}/images`,
出包脚本逐条对预取的 GPFS 清单核过(`sft/tools/ship-mixbtf.sh`,ostg@221b8a9f)。
驱动:`sft/tools/run-terminalfix-mixbtf.sh` / `build-mixbtf.sh`(ostg@30bca0be)。

**训练配方 = mixB-9b 逐字,只改拓扑**(节点上限 2):9B / lr 3e-6 / 3ep / gb64 =
2 节点 × 2 卡 × bs1 × accum 16 / max_length 81920 / `IMAGE_MAX_TOKEN_NUM=2048`。
步数:18560 / 64 = 290 步/epoch,`save_steps` 145(sbatch 运行时算,290 % 3 ≠ 0 取 2),
6 个 checkpoint,总 870 步。sbatch `sft/sbatch/mixbtf9b.sbatch`,**用户令 22:0x 投,Slurm 272351**,g[006-007] 直接起跑。
**拓扑修正(用户令,09-01 深夜)**:272351 是 2 节点×2 卡×accum 16,实测 **130–133 s/it**
(mixB-9b 4×2 是 70–72),870 步要 ~32h > 24h 上限,会在 ~650 步(ep 2.2)被砍。用户问
"为啥不 2 节点每个 4 卡"——对:2×4×accum 8 每卡负载与 4×2 相同(~70 s/it),又不违反
节点上限 2。此刻只有 g021 一台有 4 张空卡、队列 45 个作业,按"先排队再放卡":
**272551 `mixbtf9b-2x4`** 09-02 00:xx 排上 g[005,021] 开跑,**70.3 s/it,ETA ~16.5h**,preflight
与步数算术与 272351 逐字同;272351 随即撤(CANCELLED @2h07,未到 checkpoint)。
**正式臂 = 272551**,OUT `out/mixbtf9b-2x4`。

**读法**:mixb9b → mixbtf9b = 修末步的净效应(同窗 10/1);mixbtf9b → a2 = 换语料
(r5 vs mixB)的部分(同窗 20/10)。两窗各评一次(§10 末)。

**eval 对接(用户令,经 computeragent-00 转达,2026-09-01 深夜;随后改令)**:原定 mixbtf9b
首个 checkpoint(145 步)在 AWS 上评,**已撤**——权重仍暂存到 Klone `$KB/sft/models/mixbtf9b-ckpt145`
(不写 READY),要评时直接用。改为 **mixaw9b 的 ep1/ep2 也在 AWS 上评**:00 在 g3104:8056 另起
一份 serve 读同一份 `mixaw9b-ckpt115`(只读,与 g3082:8045 那份并存,vLLM 加载后不再碰文件,
无 IO 冲突);ckpt-230 推完后我额外写 `READY_aws_mixaw9b230`(与链用的 `READY_mixaw9b230`
同内容不同名),00 读它在 g3109:8057 起 serve、AWS 6 VM 评,先 10/1。17 的链里 mixaw9b
两行是否拿掉由用户/17 定。以下为原记录:分工:我(73)在 145 落地后按 115 那套
tar → klone.sock 直推 → md5 → 解包到 `$KB/sft/models/mixbtf9b-ckpt145`,Klone 侧核到
config + 4 分片后写 `READY_aws_mixbtf9b`(**不用** `READY_mixbtf9b`,留给链);00 读它后在
第 6 个空闲 l40s 占位(备选 38976065 g3104 / 39189091 g3109)起 serve,端口 8056、隧道
18056,AWS 6 VM 评,先 10/1(对 mixb9b),20/10 待第一轮出来再定。与 8041–8045 /
g3082–g3087 / WSL 3 VM 互不相碰。

**忠实重建的校验(272351 起跑后 8 步,对 mixb9b 269047 同位置)**:

| 步 | mixbtf9b | mixb9b | 差 |
|---|---|---|---|
| 1 | 0.700 | 0.766 | −0.066 |
| 3 | 0.826 | 0.713 | +0.114 |
| 5 | 0.676 | 0.796 | −0.120 |
| 8 | 0.659 | 0.680 | −0.021 |
| **前 8 步均值** | **0.744** | **0.757** | **−0.013** |

逐步差正负交替、均值差 0.013,在 batch 噪声内 —— 与 mixaw9b 那种从第一步起低 0.25 的
选择效应截然不同。说明除末步外语料确实一字未动(末步只占 4.7% 行,且新结尾更短更程式化,
方向上应略低,量级正如所见)。**这个臂的 loss 曲线可以直接与 mixb9b 横比**,
mixaw9b 的不行。preflight 147,336 张图 0 未解析;运行时步数算术 18560 / 290 / 145 / 870
与预算逐字一致。

### mixaw9b 评测排程(用户令 2026-09-01 21:13 / 21:17,经 computeragent-17 转达)

**最终分工(用户令 23:21)**:10/1 两行(115、230)**从 17 的 WSL 链拿掉,改由 computeragent-00
在 AWS 跑**(g3104:8056 / g3109:8057,读同一份权重);17 的链改为 `chain_eval_w20f.sh`
(PID 61475):mixc9b 补趟 → **mixaw9b230w20(20/10,g3083:8042)→ mixaw9bw20(115,20/10,
g3082:8045)** → mixa4b。230 那套紧跟 mixc9b(约 2–3h 后):mixc9b 评完 17 scancel 它的
serve step 并发我消息,我的自守门任务随即起 serve、写 `READY_mixaw9b230`。
(此前顺序 w20e:mixc9b → 115@10/1 → 230@10/1 → 230@20/10 → 115@20/10 → mixa4b,已废。)后果:230 那套在 mixc9b 完成后约 5h 就轮到(g3083 要等 mixc9b 的 serve
step 39187994.95 结束才空);115 的 serve 要活到 ~20h 后。占位预算:g3082=39306244 剩 3d16h,
g3083=39187994 剩 2d08h,都够。230 的对接做成自守门的后台任务:权重到 + 8042 空 +
mixc9b step 结束 → `srun --overlap` 起 serve → root 校验 → 写 READY;不自动杀任何 step。

| 点位 | 权重(Klone) | serve | READY |
|---|---|---|---|
| checkpoint-115(ep1) | `$KB/sft/models/mixaw9b-ckpt115` | 占位 dxg_w37=39306244,g3082:8045,`mixaw9b-stock` | `READY_mixaw9b` |
| checkpoint-230(ep2) | `$KB/sft/models/mixaw9b-ckpt230` | g3083:8042(mixc9b 用完后),`mixaw9b230-stock` | `READY_mixaw9b230` |

流程照 `prep_evals.sh`,跳过"等 COMPLETED / epoch≥2.99"两道门(评的是中途点位)。
g3082 上 mixa9b 的 vLLM 在 eval 结束后仍在跑(step 39306244.0),按 OPS 规矩只 scancel
该 step,.batch/.extern 未动。ckpt-345(ep3)是否评,待用户令。

## 12 strict 闸在刷什么:七成是判官视野与"保存"口径,不是轨迹(2026-09-01 深夜)

用 v3 同一个判官(claude-opus-5,`--think 0 --answer 1 --last 8`,走 Anthropic 直连)重判 r5
采纳的 v11 362 条(75 + 287;**终值,362/362 判完,0 错误**),并用同一分类器回看 v16 的 strict 拒绝:

| | v11(r5 采纳,362) | v16(全部有效判定,1374) |
|---|---|---|
| 判官 success | 97.0%(351) | 52.8% |
| 默认准入 | 93.6%(339) | 47.1% |
| **strict** | **67.7%(245)** | **24.4%** |
| strict / 默认 | 72% | 52% |

**strict 拒绝的构成**(inferred 条目按 requirement 文本与 `evidence_steps` 分类):

| 类 | v11(94 条) | v16(312 条) | 含义 |
|---|---|---|---|
| **A** 只有"以原格式保存"被判 inferred | 41(44%) | 94(30%) | 其余全 seen;判官看到 Ctrl+S + Keep Format 对话框消失,但"没有画面证明已存"。r5 那批确定性 evaluator 已在磁盘验过文件 |
| **B** 证据在被裁掉的早期帧 / 读文件类 | 24(26%) | 109(35%) | 任务要先读 note/policy/brief,读的画面在前几步;判官只拿到初始帧 + 末 8 帧(`--last 8`) |
| A+B 混合 | 3(3%) | 50(16%) | |
| **C** 其他 inferred(真·证据缺口) | 21(22%) | 49(16%) | 备注面板没截到、导出文件没看到落地、靠文档推断 |
| 非 inferred(cannot_tell/evidence 违规/derived<10) | 5(5%) | 10(3%) | |

**A+B(+混合)在 v11 占 72%,在 v16 占 81%。** 换算:

| 口径 | v11 | v16 |
|---|---|---|
| 现行 strict | 67.7%(245) | 24.4%(335) |
| 保存类免检(A) | 79.0%(286) | 31.2%(429) |
| 再给判官全帧(A+B) | **86.5%(313)** | **42.8%(588)** |

v16 的 strict-340 若按修正口径重筛,语料可到 ~588 条——**接近翻倍,而且多出来的不是低质量,
是被判官视野误杀的**。§8 记的"d3 只留 8%"很可能主要是 B 类:难任务步数多、读文件更早,
末 8 帧更装不下。

**建议(两条,都不需要重判)**:
1. `curate16 --strict` 里,requirement 文本命中"保存/原格式"的 inferred 不计入 `j_inferred`
   (r5 系有 evaluator 兜底;v16 系至少不该比"做成了"的 verdict 更苛)。
2. 有"读文件/先看"类 requirement 的任务,判官改用全帧(`--last 0`)或把 `evidence_steps`
   指向的帧补进去再判 —— 只需重判 B 类那 ~160 条(v16)。
C 类 49 条才是 strict 真正该保留的判断,单独人工抽 10 条看判官是否可信。

**独立复算(隔壁会话,gateaudit 优先合并,默认 645 / strict 拒绝 305)**:只按 `evidence_steps`
判据(不加文本条件):A 96(31%)/ B 全部 inferred 在窗外 119(39%)/ B' 至少一条在窗外 51(17%)
/ C 38(12%)/ 非 inferred 1 → **A+B+B' = 87%**,与本节 81% 同向同量级。结论成立。
**成本提醒**:B 类全帧重判(`--last 0`)v16 约 170 条、平均 20+ 步、每条 20 帧,是 v3 每条 9 帧的
2 倍多,opus 直连要先算钱。

判官输出:`ostg-v16/judge-v3-v11-100.jsonl`、`judge-v3-v11-500.jsonl`;targets
`targets-v11-r5-*.jsonl`;分类脚本逻辑见本节(正则:保存类 `save|xlsx|docx|odt|ods|pptx|
original format|in place|keep format`,读文件类 `read|locate|open|inspect|…` + `note|file|brief|
policy|folder|…`;B 判据 = 该条 `evidence_steps` 全部 < n_steps−8)。

### 独立复算(computeragent-73,2026-09-01 深夜)

用 gateaudit 优先合并 main/pilot(默认准入 645,strict 拒绝 305),按本节写的 B 判据
(该条 `evidence_steps` 全部 < n_steps−8,**不加**"读文件"文本条件)重算:

| 类 | 条 | 占拒绝 |
|---|---|---|
| A 只有保存类 inferred | 96 | 31% |
| B 全部 inferred 证据在末 8 帧之外 | 119 | 39% |
| B' 至少一条 inferred 在窗外(≈上表 A+B 混合) | 51 | 17% |
| C 证据步在窗内仍判 inferred | 38 | 12% |

A+B+B' = 87%,与上表 81% 同向同量级(分母口径略异)。**结论成立。** 注意 B 的判据必须
是"证据步在窗外",不能再叠"requirement 文本命中读文件"—— 叠了会把 B 压到 41 条、
C 涨到 167,结论反转;分类正则只是标签,不是判据。

代价提醒:B 类重判要 `--last 0` 全帧,v16 那 ~170 条平均 20+ 步 = 每条 20 帧,
是 v3 那轮 9 帧的两倍多,opus 直连按帧计费。是否改口径由用户定;两个在训的臂
(mixaw9b 用 strict-340,mixbtf9b 不用 strict)不受影响。
