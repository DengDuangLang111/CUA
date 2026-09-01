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

### 取消了证据闸(用户令 2026-09-01)

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
