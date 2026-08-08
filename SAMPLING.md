# 抽样与污染边界

> 361 个官方任务**既是评测集，也是"任务长什么样"的参考库**。
> 这两个身份互相冲突，这份文档记的就是那条边界划在哪、为什么划在那里。

---

## 1. 冲突是什么

想要覆盖面，最直接的办法是拿官方任务的**内容**去生成变体。但如果之后还要在这
361 个任务上报分，那就是拿评测集的内容做训练数据——分数不可信。

所以边界是：

| | |
|---|---|
| **可以借** | 分类坐标：`artifact`、`source`、`operation`、`app_count`、`domain`/`primary`、`modality`、`mechanism` |
| **不能借** | instruction 原文、具体文件名、业务规则、任何数字 |

坐标是"这类任务长什么样"的压缩表示，不含任何可以被背下来的东西。
`drawn_from` 记的官方任务 id 只用来抽坐标，它的内容一个字都不进 prompt。

---

## 2. 现在的坐标空间

`gen.cells()` 从 `data/osworld361_labels.json` 里 260 个 `generatable` 的官方任务
中抽。可达格子数：

| 组合 | 格子 |
|---|---|
| `artifact × source` | 37 |
| **`artifact × source × operation`（当前）** | **80** |
| `+ app_count` | 88 |
| `+ domain` | 107 |

**当前实现到 80。** `app_count` 和 `primary` 也在 brief 里，但它们是**派生的**，
不是独立抽的：

- `app_count` 跟着抽中的那个官方任务走
- `primary` 在"实际承载该 artifact 的应用"里按确定顺序轮转

`domain` 不做独立轴是有意的：`primary` 已经是它的代理，而独立轮转应用会产出
`raster_image + libreoffice_calc` 这种无意义组合。为了从 88 走到 107 而重新打开
那个口子，不划算。

### 格子密度极不均匀

37 个 `artifact × source` 格子里，最大的两个各自代表 48 和 40 个官方任务：

```
(preference_store, prompt_literal)   48
(spreadsheet,      self)             40
(slide_deck,       prompt_literal)   25
(slide_deck,       self)             15
...
```

**48 个官方任务塌缩成同一句 brief。** 这是加 `operation` 和加避让清单要解决的问题。

---

## 3. 为什么加了 `operation`（推翻 README §4 的一半）

README §4 依据 40 个样本的盲标重标不一致率否掉了 `operation`：

```
artifact    10.0%
app_count   12.5%
source      13.9%
modality    15.0%
operation   27.5%   ← 被否掉
```

**这个否决对"度量"成立，对"转向"不成立。**

27.5% 说的是：两个标注员对一个**已完成的任务该叫什么**会吵起来。这确实让
`operation` 不能用来当多样性的**度量**——你不能拿它做覆盖率报告。

但它说不了：告诉模型 `operation=remove_element` 和 `operation=set_value`，
产出的任务会不会不一样。**会。** 度量需要可靠性，转向不需要。

所以现在的分工是：

```python
AXES  = ("artifact", "source")               # 报覆盖率用，只用信得过的
STEER = ("artifact", "source", "operation")  # 喂给模型用，能分开就行
```

`modality`（15.0%，README 说"过关但冗余"）同理——作为度量冗余，作为转向照样能用。
暂时没加，因为它跟 `artifact` 的相关性太高，边际收益小。

### 批内去重仍然停在 `(artifact, source)`

加 `operation` **没有**放宽批内去重。理由是 README 记的那次教训：第一个真实批次
在 8 个里抽到 3 次 `spreadsheet/self`，三个都回来是"加一列算出来的值然后保存"。
把去重键放宽到含 `operation` 会让这个洞重新打开一条缝，而扩出来的覆盖面本来就
会在多个批次之间自然累积。**收益照拿，风险不担。**

---

## 4. 避让清单（纯自对弈）

同一个格子、同样四个坐标，抽多少次都是同一句 brief。所以 `gen` 现在把该格子里
**已经生成过的 slug** 一起发过去，要求避开：

```
Already generated in these cells. Do NOT repeat their business scenario or
their rule; go somewhere clearly different:
  spreadsheet / self: grade-weighted-average-calc, inventory-reorder-flag,
                      sales-commission-tiers
```

三个性质：

1. **零泄漏。** 清单来自我们自己生成的 spec，跟官方套件无关。
2. **只发 slug。** slug 本来就是业务场景的压缩表示（`inventory-reorder-flag`），
   token 便宜，而且不含任务细节。
3. **运行内累积。** `--batches 3` 时第二批已经知道第一批刚写了什么。

清单按 `(artifact, source)` 索引，不按 `(artifact, source, operation)`——粒度更粗
即避让更宽，而且老的 spec 没有 `operation` 字段也照样能匹配上。

到 2000 个任务的量级，107 格平均每格 19 个，这一步是必需的，不是锦上添花。

---

## 5. 还没做：事后测污染

现在的安全性靠"只借坐标"这条纪律保证，**没有任何东西在事后验证它**。

该补的是：生成完之后，把每条 instruction 跟**全部 361 条**官方 instruction 算相似度，
超阈值的直接扔。这把"我们希望没污染"变成一个数字。361 × N 条短文本，秒级。

依据是 `taskgen/specs/vocab.py` 里记的那次教训：上一代生成到过 0.987 的指令相似度
才被发现模式塌缩。同一把尺子，换个用途。

这一步跟 ostg「质量控制在事后、不在生成端」的主张是一路的——所以它属于 `filter`
那一层，不属于 `gen`。

---

## 6. 结构性覆盖不到的

`generatable=False` 的 **101 个**（不是 README 写的 88），按 blocker：

| blocker | 数量 |
|---|---|
| `needs_live_web` | 56 |
| `refusal_not_observable` | 27 |
| `needs_network_install` | 9 |
| `needs_gui_only_state` | 8 |
| `subjective_judgement` | 1 |

`refusal_not_observable` 那 27 个最彻底做不了：判分信号是
`desktop_env.py:469` 读的 `action_history[-1] == 'FAIL'`，在 **agent 的输出通道**里，
VM 内任何程序都看不见。probe 结构上够不着。

但它并非无解——`func: "infeasible"` 在 `evaluate()` 里是**在取 result getter 之前**
短路的，所以这类任务的 evaluator 只需要 `{"func": "infeasible"}`，一个 getter 都不用。
成本在 emit/check：这类任务没有 solved 状态，两个构建期对照对它没意义，得特判跳过。
7.5% 的任务类型空白，换一处特判，看起来划算，但还没做。
