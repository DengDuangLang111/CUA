# CHECKPOINTS — 模型/数据集/轨迹存放台账

> 谁存在哪、哪个臂对应哪份数据、哪些能删。命令在 `RUNBOOK.md`,
> 配方在 `sft/TRAINING.md`,分数在 `EXPERIMENTS.md`。
> **口径:目录名以 `pgrep -af run_multienv_qwen` / sbatch 里的 `DS=` 为准**,
> 不以记忆为准(数结果数错目录的教训,`CLAUDE.root.md` 铁律 2)。

## 1 四个存放地

| 存什么 | 在哪 | 备注 |
|---|---|---|
| **训练 checkpoint** | Tillicum `/gpfs/scrubbed/jy050706/sft/out/<臂>/<版本>/checkpoint-N` | **scrubbed 文件系统:长期不访问会被自动清理,重要 checkpoint 要么用要么迁走** |
| **SFT 数据集** | Tillicum `/gpfs/scrubbed/jy050706/sft/data/<语料名>/` | samples.jsonl + images/;由 WSL 侧 build 产出后 ship |
| **语料构建产物** | WSL `/mnt/d/research/ostg-v11.1/out/sft-<语料>-<池>/` | 含 report.json(每条过滤的账)、think_quarantine.jsonl |
| **rollout 轨迹(原料)** | WSL `/mnt/d/research/OSWorld/results_generated/<模型>/<批次>/` | 教师轨迹 + eval 结果都在这里,按 model 目录分 |
| **审计 sidecar** | WSL `/mnt/d/research/ostg-v11.1/out/*.jsonl` | trajaudit/stepaudit/arb/curate 产物,只读元数据 |
| **eval 结果** | WSL `.../results_generated/qwen35-4b-sft/eval50-<臂>-<日期>/` | 每个目录带 MODEL_BOUNDARY.json 说明该臂配置 |

版本目录 `v<N>-<YYYYMMDD-HHMMSS>` 由 swift 自动生成;同名臂多次尝试会累积
多个 v 目录,**只有含 checkpoint 的那个是真跑起来的**(见下表 ckpt=0 的行)。

## 2 现役 checkpoint(2026-08-17 07:00 盘点,总占用 4.1 TB)

| 臂 | 目录 | ckpt | 末步 | 体积 | 语料 | eval |
|---|---|---|---|---|---|---|
| **gb64o** | `q38e3B-gb64o/v0-20260817-013858` | 9 | 267 | 592G | B(v11-100+500 pass) | **在跑(3VM)** |
| **Bs-gb64** | `q38Bs-gb64/v0-20260817-032220` | 9 | 264 | 592G | q38e3B-tc2048-*(cap 2048) | 排队 |
| **Bs-LoRA** | `q38Bs-lora/v0-20260817-043913` | 7 | 210 | 14G | 同上 | 排队 |
| gb128 ep2 | `q38e3B-gb128/v7-20260816-224140` | 2 | 90 | 132G | B | ✅ **21.9/50 = 43.8%** |
| B-1ep | `q38e1B/v0-20260816-183257` | 1 | 708 | 66G | B | ✅ 15/50 = 30% |
| B-3ep | `q38e3B/v1-20260816-183257` | 1 | 708 | 66G | B | 待(下午落地) |
| rich | `q38e3-rich/v0-20260815-012706` | 3 | 450 | 198G | arm A rich | ✅ 14/50 = 28%(stock 15/50) |
| lean | `q38e3-lean/v0-20260815-012706` | 3 | 450 | 198G | arm A lean | ✅ 11/50 = 22% |

LoRA 的 14G vs 全量 592G = adapter 存储优势的实测量级(**42 倍**)。

> ⚠ **上表所有用 B / Bs 语料的臂都含 slug 冲突缺陷**(~29/5,586 样本截图错配,
> 0.5%,详 `SFT_DATA.md` 事故章)。量级远小于臂间差异,不重训;引用这些分数
> 时带上此脚注。**Bhqs 起已修复**(build/verify/census 三层防线)。

## 2.1 在训/待训模型登记(2026-08-19,按用户优先级排序)

用户裁定的下一批 eval 顺序(已排进 `tools/tillicum_chain.sh`,全部 no-split 口径):

| 序 | 臂 | 模型/训练 | 状态 | eval 安排 |
|---|---|---|---|---|
| 0 | **vlbase** | `models/Qwen3-VL-4B-Thinking`(基座,零训练依赖) | 在盘 | **t38 后立即跑**(VL 系的参照,插队令 2026-08-19) |
| 1 | **nocap** | `out/q38Bhqs2t-lr3e6-nocap`(= kE 配置去 think-cap;作业 247800 在训) | 在训 | vlbase 后跑;链上有**完训闸**(作业退队 + endpoint epoch≥2.99),半熟权重进不了 serve |
| 2 | **img3** | (尚无训练、无目录;历史图从全量降为 3 张的 token 经济学臂,OpenWebRL 先例) | **不存在** | **只登记,不排跑**(用户令) |
| 3 | **VL-SFT** | `out/q3vl-r5vl-lr3e6`(Qwen3-VL-4B-Thinking × r5vl 语料;作业 248101 在训) | 在训 | **只登记,不排跑**(用户令;评它之前先要 vlbase 参照 + serve 兼容冒烟) |
| 4 | loranp = kG | `out/q38Bhqs2t-loranp-merged-300` | 在盘 | 已在链上(nocap 后) |
| — | loralean = kF | `out/q38Bhqs2t-loralean-merged-300` | 在盘 | 链尾(此前用户令) |

> nocap 与 VL 的训练由另一会话发起;此表只管 eval 排期与登记。

## 3 数据集(Tillicum `sft/data/`)

| 名 | 内容 | 用于 |
|---|---|---|
| `q38e3B-v11100` / `-v11500` | B 原始(checker 判过的全部 pass) | B 各臂、gb64o |
| `q38e3B-tc2048-v11100` / `-v11500` | Bs = B + think-cap 2048 | Bs-gb64、Bs-LoRA |
| `q38-Bhqs-v11100` / `-v11500` | **Bhqs = 双判官+仲裁筛选 + cap 2048** | Bhqs 臂(新) |
| `q38-Bhqs2t-v11100` / `-v11500` | **Bhqs-2-terminal**。集群上目前是**有缺陷的旧版**(6,297 行),待换成 r5 | 239100 LoRA、239101 全量 lr 3e-6 |
| `q38e3B-v11100`(旧)/ `v11-legacy` / `v11-500-partial` 等 | 早期实验 | 已退役 |

### 3.1 Bhqs-2-terminal 语料的版本(WSL `ostg-v11.1/out/`)

| 目录 | 轨迹 / 样本 | 说明 |
|---|---|---|
| `sft-Bhqs2tr5-v11100` / `-v11500` | **362 / 6,385** | **现役**。三路修复(48 原样 / 259 补指令 / 69 重写),末步 100% terminate,meta 带 `terminal_mode` + `rescued` |
| `sft-Bhqs2tr4-*` | 362 / 6,385 | 同上但 meta 无溯源字段,已被 r5 取代 |
| `sft-Bhqs2t-*` | 362 / 6,297 | **有缺陷**:截尾砍掉真动作、图片继承污染。**这一版已 ship 到集群,尚未替换** |

末步修复的中间产物是 `out/terminal_v11{100,500}.jsonl`(每轨迹一行,含
`mode` / `keep_to` / `tail_gate` / `teacher`),历史版本留在 `.v1` / `.v2` / `.v3`。

## 4 可清理(省 ~1.6 TB,做之前逐个确认无引用)

8-13 的探索期臂,均已被后续实验取代且无 eval 记录:
`ep5np`、`ep5pt`、`fast`(各 329G)、`more3`、`more3np`、`pilotS`、`pilotS3`
(各 198G)、`more`(132G)、`e3`(198G)、`e1`/`pilotS3x3`(各 66G)。
另有 12 个 ckpt=0 的空目录(失败的启动尝试,每个 130K,不占空间但碍眼):
`q38e3B-gb128/v0..v6`、`q38e3B-gb128o/v0`、`probe-z3a16`、`smoke*`、`pilot1`。

**清理前必查**:该臂是否出现在 `EXPERIMENTS.md` 的分数表里、是否有 serve
sbatch 指向它(`grep -r <臂名> sft/sbatch/`)。

## 5 命名约定(新臂照此起名)

```
<教师代号><epoch><语料>[-<优化域>][-<方法>]
q38  e3      B      -gb64o          全量,3ep,B 语料,全局 batch 64 + 对齐优化器
q38  Bs      -lora                  LoRA,Bs 语料
```
serve sbatch 与 eval 驱动用同一个臂名做 TAG(`eval50-<臂>keep-<日期>`),
这样 checkpoint→serve→eval 结果三处可以互相对照。
