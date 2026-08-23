# 实验臂命名标准

> 2026-08-23 立。起因:`kE` / `a1h10` / `img3h3` / `nocap` 这类名字只有当事人
> 看得懂,外人拿到表格无法判断哪两行可以对着比。名字的职责是**让人一眼看出
> 这个臂和基准差在哪**。

## 格式

```
<骨干>-<训练法>-<语料>[-<偏离项>...][@<推理窗口>]
```

**只写与标准配方不同的部分。** 完全按标准配方训练的臂,名字里就没有偏离项 ——
名字越长,说明这个臂动的东西越多、越不适合做单变量对比。

### 标准配方(省略即代表用的是它)

Qwen3.5 全参微调 · lr 3e-6 · 3 epoch · global batch 64 · warmup 0.1 ·
weight decay 0 · β₂ 0.999 · 余弦退火到 0 · max_length 65536 · 梯度重计算开

### 标准推理配置(省略即代表用的是它)

`image_max 20 / fold_size 10` · temperature 1.0 · top_p 0.95 ·
max_steps 50 · max_tokens 81920

## 各段的取值

| 段 | 取值 | 说明 |
|---|---|---|
| **骨干** | `4b` `9b` `27b` | Qwen3.5-4B / 9B / 教师 Qwen3.8-27B |
| **训练法** | `full` `lora` `base` | 全参 / LoRA / 未训练 |
| **语料** | 见下 | |
| **偏离项** | `lr2e6` `ep5` `gb128` `hermes` `t0` … | 与标准配方不同的地方,可多个 |
| **推理窗口** | `@3` `@1` `@10` | 仅当不是默认 20/10 时才写;`@N` 表示 `image_max N / fold_size 1` |

## 语料命名

```
img<窗口>[cap][np][v]
```

| 记号 | 含义 |
|---|---|
| `img20` `img10` `img3` `img1` | 训练时每步最多保留几张截图 |
| `cap` | teacher 的 think 被截断过(不带则是完整 think) |
| `np` | 去掉了 teacher 散文(no prose) |
| `v` | 切了 5% 验证集(训练样本相应减少) |

例:`img10v` = 10 图窗口 + 完整 think + 带散文 + 切了验证集。

## 已有臂的对照表

历史结果目录名不改(它们是存档),但**报表、文档、对外材料一律用新名**。

| 新名 | 旧名 | 一句话 |
|---|---|---|
| `4b-full-img20` | nocap | 4B 冠军基准 |
| `4b-full-img20cap` | kE | 同上,但 teacher think 被截断过 |
| `4b-full-img20cap@3` | kEh3 | 同一份权重,推理只给 3 张图 |
| `4b-full-img20cap@1` | kEh1 | 同一份权重,推理只给 1 张图 |
| `4b-full-img10` | a1 | 训练窗口砍到 10 |
| `4b-full-img10@10` | a1h10 | 同一份权重,推理也给 10 张 |
| `4b-full-img10-hermes` | a3 | 同语料同窗口,动作 token 的 loss 权重 ×2 |
| `4b-full-img3` | img3 | 训练窗口 3,推理仍是默认 20 |
| `4b-full-img3@3` | img3h3 | 同一份权重,推理给 3 张 |
| `4b-full-img1@1` | img1 | 训练和推理都只给 1 张 |
| `4b-full-img20np` | nocapnp | 去散文 |
| `4b-full-img20-lr1e6` | np1e6 | 学习率降到 1e-6 |
| `4b-full-img20-t0` | nocapt0 | 推理改贪心解码 |
| `4b-full-img20@100steps` | nocapms100 | 推理步数上限翻倍到 100 |
| `4b-lora-img20` | r5lora | LoRA |
| `4b-lora-img20np` | kG | LoRA + 去散文 |
| `4b-base` | base / basekeep | 未训练的 4B |
| **`9b-full-img10`** | **a2** | **9B,当前最好的学生** |
| `9b-full-img10v-gb128-hermes` | a7 | 9B,多个改动同时动(不是单变量对比) |
| `4b-full-img10v-lr2e6-ep2` | a6v | 学习率和 epoch 都降了 |
| `9b-base` | base9b | 未训练的 9B |
| `27b-teacher` | t38 | 教师,未微调 |

## 怎么用

**看到两个名字,把不同的段圈出来 —— 那就是这次比较的变量。**

```
4b-full-img20   vs   4b-full-img10        只差训练窗口 ✓ 干净
4b-full-img10   vs   4b-full-img10@10     只差推理窗口 ✓ 干净(同一份权重)
9b-full-img10   vs   4b-full-img10        只差骨干     ✓ 干净
9b-full-img10   vs   9b-full-img10v-gb128-hermes   差三项 ✗ 不能归因到任何单项
```

最后那行正是这个命名法的价值:**名字自己就在警告你别做那个比较。**

## 规矩

1. **新臂一律用新名**,包括 sbatch 的 `--output_dir`、serve 的
   `--served-model-name`、驱动里的臂键。
2. **偏离项要写全** —— 少写一个,就等于对读者隐瞒了一个变量。
3. **同一份权重的不同推理配置,共享前缀、只差 `@` 后缀** ——
   这样一眼能看出它们是同一个模型。
4. 语料建出来时就按标准命名,不要事后翻译。
