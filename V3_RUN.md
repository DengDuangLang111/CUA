# ostg v3 —— 生成运行记录

> 2026-08-08。记录 v3 这一轮改了什么、量到了什么、还有什么没验。
> 设计理由在 [`SAMPLING.md`](SAMPLING.md)，代码说明在 [`README.md`](README.md)。
> 本文只记**这一轮**的事实与数字。

---

## 1. 一句话

v3 用「先定义轴、再枚举笛卡尔积」替换 v2 的「从 OSWorld 361 条标注里抽坐标」，
并把 CUA-Gym 的 10,909 条已有指令喂回生成端当避让清单。
**目标是降低与已有 benchmark 的重复率**——v2 实测 7/29 (24%) 是确认重复。

---

## 2. 流水线现在走到哪

```
① gen      生成 spec              ← 进行中,14/40 批
② emit     编译 + 两个构建期对照    ← 已在 46 条样本上试跑
③ check    OSWorld 合法性校验      ← 已在 46 条样本上试跑
④ contam   查重                   ← 已在 24 条样本上试跑
⑤ 搬进 OSWorld + manifest         ← 未开始
⑥ run      起 VM,Qwen 真做         ← 未开始,6-16 小时
⑦ filter   留 score==1.0 出 SFT   ← 未开始
```

**答题模型链路已验通**：隧道监听 18001、ControlMaster 活着、`/v1/models` 返回 200、可用内存 18G。

---

## 3. v3 相对 v2 改了什么

### 构造上保证的（代码算出来，模型没有余地）

| | v2 | v3 |
|---|---|---|
| intent | 无此轴 | 每个 intent 恰好 40 条 |
| 业务领域 | **无此轴** | 13 个行业强制铺开 |
| 显式要求数 | 模型自由发挥 | 指定：`1条=46, 2条=56, 3条=55, 4条+=43` |
| 坐标唯一性 | 批内不重复 (artifact, source) | 200 个 (intent, domain, constraints) 三元组全不同 |
| 产物 | —— | 12 种，9 个应用，23 种 (产物 × 应用) 组合 |

**77% 的任务被要求至少两条要求**，43 条要求四条以上并带排序或平局规则。
这是针对 v2 的具体病因：v2 那 7 条重复里 5 条是「改一个属性」，
而单属性任务的空间本身就小，谁生成都会撞。

### 只是施加了压力的（模型可以不听）

- **prompt 里带真实的已有任务**，按 app 采样 12 条，明写
  *"A task that differs from one of these only in a constant … counts as the same task and is worthless."*
  天花板要说清楚：libreoffice_calc 有 2,576 条，只给看 12 条（**0.5%**）。
  它是给手感，不是穷举排除。
- **模型换了**：Opus 4.6 无 thinking → **Opus 5 带 thinking**，每条多花约 4,950 输出 token。

---

## 4. 量到的数字

### 查重（24 条样本 vs 11,259 条参考语料）

```
              median   p75    p90    max     ≥0.35
v3 (24 条)     0.14    0.22   0.26   0.31    0/24   (0%)
v2 (29 条)     0.24    0.37   0.54   0.55    9/29   (31%)
```

**整条曲线下移**，不是最大值走运——v3 的最大值 0.31 比 v2 的 p75 (0.37) 还低。
人眼复核环节第一次为空（v2 那次有 9 对要读）。

### 编译与校验（46 条样本）

```
emit  编译       46/46 成功
      负例对照   0 失败      ← 没有"白送分"任务
      正例对照   2 失败      ← 见下,任务没坏
check 合法性     46/46 通过
```

**负例 0 失败比正例通过率更重要**：它证明没有任何任务在初始状态就能判过。
白送分的任务会静默抬高成功率。

---

## 5. 这一轮找到的 bug

四个，全是我引入或判断失误的。**共同点：没有一个是被检查抓到的，都是靠读实际输出发现的。**

### ① 分片步长与 constraints 轴对齐

`space[i::4]` 的步长 4 正好等于 `CONSTRAINTS` 的取值个数，而它是笛卡尔积里变化最快的维度。

```
修复前   shard 0: {1: 65}   shard 1: {2: 65}   shard 2: {3: 65}   shard 3: {4: 65}
```

shard 0 的 50 条会全是「只有一条要求」的任务。
**教训**：任何算术分片都会和乘积的某个轴对齐——块切对齐最外层，步长切对齐最内层。
正解是先用固定种子打乱再切（固定是必须的，四个进程必须推出同一个排列）。

### ② 产物轴是个常数

`rotation` 是函数局部变量，每批归零；而每批恰好抽每个 intent 一次，
所以它永远停在 0，永远取字母序第一个。

```
修复前   整个 200 条只有 4 种产物
         info_seeking 40/40 全是 browser_tab
         spreadsheet / text_document / slide_deck / source_code / raster_image 一条都不会有
修复后   12 种产物
```

不是「多样性不够」，是**那个轴根本没在转**。

### ③ browser_tab 任务判分器是坏的

`taxonomy.py` 把 `gold_kind` 硬编码成 `"file"`，gen.py 又用 cell 的值
**覆盖掉模型正确吐出的 `browser_state`**。后果是 emit 把空 probe 接到读文件的判分器上
——**永远 0 分**，而且两个构建期对照报 n/a 不报错，能一路溜到 VM 里。
前 21 条里已有 5 条中招。

已加闸：`gold_kind=file` 但 `probe_py` 为空的 spec 直接丢弃并打印原因。
**它之所以能静默出厂，就是因为没有任何地方断言这一对。**

### ④ HTTP 504 不该被当成永久失败

原先写的是「HTTP 错误直接上抛，重试只会在同一个失败上烧 token」。
**这对 400 成立，对 504 不成立**——网关超时是瞬时故障。
一次 504 让 shard 1 丢了整批 5 条。已改成 429/5xx 重试、其余 4xx 上抛。

> 该修复**没有应用到正在跑的这一轮**：进程已加载旧模块，
> 重启一次损失 30 条 + 25 分钟，为救 5 条不划算。
> **所以本轮预期产出 195 条而非 200 条**，最终报告按实际条数算比例。

---

## 6. 已知没解决的

| | 说明 |
|---|---|
| **跨 shard 无 slug 避让** | 四个进程互相看不见对方写了什么。格子不重叠挡住结构性重复，挡不住两个进程都写「医疗行业的发票整理」。只能靠满 200 条后的 `vs_siblings` 测 |
| **`sig.py` 跨语料失效** | 实测：已知真重复对得分 0.097、排名 1254/10899。CUA-Gym 用 python-docx 读 `paragraph_format.line_spacing`，ostg 解压读 `w:spacing`，标识符交集为零。**参数级重复仍可能藏着** |
| **主机对照够不到 5% 的任务** | 2/43 正例失败是因为模型没一致地用 `P()`（一条写死 `/home/user`，一条用 `expanduser('~')`）。任务在 VM 里能跑对，但对照失去了覆盖。RULES 第 11 条没禁止这两种写法——下一轮补 |
| **live_web 任务没验过网络** | 8 条 browser_state 打 arXiv / Wikipedia / law.cornell.edu。官方 44 个 `proxy: true` 是因为 Amazon/Delta 拦数据中心 IP，这几个站点大概率不拦，**但没测过** |
| **`configure` 那 40 条风险没消失** | 只是被限量了。可设的属性就那么多 |

---

## 7. 提交记录（分支 `check`，基于 `v3-taxonomy`）

```
ae76850  gen: retry 429 and 5xx; a gateway timeout is not a bad request
2ad37ea  taxonomy: the artifact axis was constant, and browser_tab was ungradeable
97c0ade  report: run-level duplication report against a baseline
443a75b  taxonomy: shard stride aligned with the constraints axis
7bf277c  taxonomy: --shard I/N so generation can run in parallel
9ef47ff  gen: --thinking, which means tool_choice auto and a retry
3098c9d  sig: docstring said Jaccard over whole identifiers; it is over word pieces
d8bfb4c  check: TF-IDF cosine, grader signatures, external avoid list
359bea6  SAMPLING: CUA-Gym is the binding contamination constraint, not OSWorld
92ea75c  contam: compare against N benchmarks, not just OSWorld
54739d6  v3: axis-first taxonomy — intent x domain x constraints
```

---

## 7.5 rollout 实测（跑到 8/185 时的观察）

### 步数是双峰的，而且做对的那一峰更短

```
1.0  spring-tour-csv-archive     27 步   5.0 分钟
0.0  donation-fy-totals-repair   23 步   4.6 分钟
─────────────────────────────────────────────────
0.0  fernwood-shelf-price-repair  88 步  23.5 分钟
0.0  q3-channel-cpa-workbook      90 步   8.9 分钟
0.0  open-matters-fee-ranking    104 步  26.3 分钟
```

每步中位 **15.6 秒**（p90 22.5s），大头是模型推理——每步要重送最多 20 张
1920×1080 截图。所以**做不对的任务比做对的贵 4 倍**。

### 把上限从 50 提到 100 是净亏损

两条有 50 步基线的任务，放宽后重跑：

```
                            50 步        100 步
open-matters-fee-ranking    0.0 (触顶)   0.0 (用了 104 步)
q3-channel-cpa-workbook     0.0 (触顶)   0.0 (用了 90 步)
```

**多给的 50 步一条都没救回来**，只让每条多烧 13 分钟。吞吐直接减半，
换来的是零。当时的判断"100 步能分清 0 分是任务太难还是步数不够"是错的——
对死循环型失败，两者都不是。

下一轮：上限回 50，并加一个**无进展提前终止**判据（连续 N 步屏幕哈希不变，
或同一动作重复 M 次）。OSWorld 的 runner 没有这个，要自己加。

### 主导的失败模式：`\t` 被当成字面字符

模型在 `<parameter=text>` 里写 `Channel\tSpend\tClicks`，而这个接口**原样输入**。
整行挤进 A 列，B/C/D 全空。正确做法是发 `key: tab`。

完整的失败链在 `ebd63064` 里可以看到：

```
x36  pyautogui.press("enter")               ← 40% 的动作是按回车
x5   typewrite("Affiliate\\t2800\\t...")     ← 同一行打了 5 遍
x4   typewrite("Email\\t1200\\t...")
```

打一行 → 挤进一格 → 看到不对 → 重打 → 还是不对 → 90 步烧完。

这**不是我们的 bug 也不是 OSWorld 的 bug**，是模型不知道自己工具的契约。
修它要改 OSWorld 的 agent 提示词，那会让结果和官方数字不可比。保留。

但它有个后果值得记：**自对弈教不会模型它从没做对过的事**。`filter.py` 只留
score==1.0，这个技能一条样本都产不出来。要真提升得靠重复采样（提高偶然做对的
概率）或者外部示范，不是靠多生成同类任务。

### 另一种失败：agent 自己放弃

`ba692629` 一步就结束——点了一下工作表标签，说"打开 Findings 表准备录数据"，
然后直接发 `DONE`。把"我准备好了"当成"我做完了"。

---

## 7.6 v4 改了什么（分支 `check`，commit 07a8b34）

v3 唯一没改善的是自相似度（median 0.14 → 0.19，最差一对 0.44）。两处修复：

| # | 改动 | 状态 |
|---|---|---|
| ① | 避让清单**每批重读**，四个分片能互相看见 | 待验（要 100+ 条才测得出） |
| ② | 增加**按应用分组**的避让，发全文不发 slug | 待验 |
| ③ | RULE 11b：所有路径必须过 `P()` | ✓ **44/44 合规**（v3 是 170/185） |
| ④ | 429/5xx 重试 | ✓ **8 次重试 0 丢批**（v3 是 3 次丢 15 条） |

①②针对的是同一件事的两个层面：v3 最像的两对都是**跨分片**的，而且按
`(artifact, source)` 分组太细——那两个 VLC 任务在不同格子里，per-cell 清单
永远看不见它们。**按应用分组才是"操作空间小"真正咬人的粒度。**

③ 的效果立竿见影，而且改变了模型的取舍：同一个格子
`configure/human_resources/c=3`，旧的是"改 VLC 快照目录"（写死 `/home/user`），
新的换成了"配置字幕"——按应用避让让它主动换了方向。

---

## 8. 跑完之后要做的

1. `emit` 全量 → 看对照通过率是否维持在 95%
2. `check` 全量 → 必须 100%，任何一条不过都会在 VM 里炸
3. `report` 全量 → 对比 v2 基线，**并人眼读 cosine 最高的 10 对**
   （哪怕全在 0.35 以下也要读——这是唯一能验证阈值本身是否合适的办法）
4. 重复的扔掉**再**搬进 OSWorld —— 每条重复任务要烧 5-15 分钟 VM 时间
5. 第 ⑥ 步开跑前确认隧道还活着（ControlPersist 48h）

**第 ⑥ 步一旦开始就是 6-16 小时的机器占用**（195 任务 ÷ 3 并发，3 是 18G 内存的硬上限），
开跑时机由人决定。
