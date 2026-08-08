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

## 8. 跑完之后要做的

1. `emit` 全量 → 看对照通过率是否维持在 95%
2. `check` 全量 → 必须 100%，任何一条不过都会在 VM 里炸
3. `report` 全量 → 对比 v2 基线，**并人眼读 cosine 最高的 10 对**
   （哪怕全在 0.35 以下也要读——这是唯一能验证阈值本身是否合适的办法）
4. 重复的扔掉**再**搬进 OSWorld —— 每条重复任务要烧 5-15 分钟 VM 时间
5. 第 ⑥ 步开跑前确认隧道还活着（ControlPersist 48h）

**第 ⑥ 步一旦开始就是 6-16 小时的机器占用**（195 任务 ÷ 3 并发，3 是 18G 内存的硬上限），
开跑时机由人决定。
