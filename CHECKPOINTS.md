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

## 2.1 在训/待训模型登记(2026-08-19 深夜更新;eval 顺序=用户令)

当前链(`tools/tillicum_chain.sh`,全 no-split,08-19 17:00 版):**kG(跑动中)
→ vl20 → vl3b → vl20g → kEh1 → baseh1 → vlbaseh1(尾)**,之后 eval100 决赛。
baseh1/vlbaseh1 = 两个未训基座 @ `--image_max 1 --fold_size 1`(08-19 用户令,
1pic-vs-3pic 决策的下限参照;serve 复用 eval4bbo/eval4bvlb,无训练闸)。
kF 不排。VL 三尾臂均带完训闸;vl20g 即第五臂(用户排上=保留)。
插曲三:248869/248870 首交 8 秒死于 MASTER_PORT=29500 写死(1 卡/节点作业与
248868 共享节点抢端口),改为 `20000+JOBID%9000` 后重交为 248882/248883;
四个 VL 训练脚本的端口全部改成 job 派生,此坑永闭。

| 臂 | 模型/权重 | 状态 | 说明 |
|---|---|---|---|
| nocap | `out/q38Bhqs2t-lr3e6-nocap`(kE 配置去 think-cap) | **已训完** | 回锅后再调序:排 vlsft 后;链有完训闸 |
| vlsft | `out/q3vl-r5vl-lr3e6`(Qwen3-VL-4B-Thinking × r5vl,lr3e-6 3ep) | 在训 | 排 kG 后,完训闸;对照 = vlbase |
| img3 | `out/q38Bhqs2t-img3`(**kE 字节级同配方**,仅训练截图窗 20→3) | 在训 | 排 vlsft 后,完训闸;**按用户令用标准 20 图协议评**(2×2 的故意 skew 格) |
| img3h3 | 同 img3 权重 | — | eval 侧 `--image_max 3 --fold_size 1`(3训/3评格),复用 img3 serve |
| kEh3 | 同 kE 权重 | 在盘 | eval 侧 `--image_max 3 --fold_size 1`(20训/3评格) |
| kF | loralean-merged-300 | 在盘 | **不排**(用户令 08-19 撤销);权重与 serve 脚本齐备,要跑随时可挂 |

> ⚠ **scrubbed 吃文件是实证过的**(08-19 凌晨吃掉 uv Python 标准库,验尸在
> OPS.md)。checkpoint 同住 scrubbed:新写的暂安全,**长期保留的(冠军 kE 的
> checkpoint-300 等)应尽快异地备份**——krishna 盘 99% 满、home 仅 10G,
> 现实去处是 Klone `/gscratch/cse/jy050706/`。

### VL 训练三炉的真实配置(2026-08-19,以此表为准,**248868 的 wandb 注记是旧的别信**)

| job | 数据 | 真实拓扑 | lr | save |
|---|---|---|---|---|
| 248868 vl3pic-gb128 | vl3pic(3 图窗) | 8 节点×1 卡×bs1×accum16 = gb128 | 1e-5 | 10/16 |
| 248869 vl20pic-gb128 | **r5vl(20 图)** | 同上 | 1e-5 | 10/16 |
| 248870 vl3pic-base | vl3pic | 8 节点×1 卡×bs1×**accum8** = gb64 | **3e-6** | 25/16 |

OOM 验尸(248818/248809,均第 8/16 步死):峰值 ∝ bs × 批内最长样本(语料 max
39,552 token);bs2 两条长样本同批 → 136G+34G 索求 > 139.79G。**治好它的是
bs2→1,不是节点拓扑**(1 rank/节点多的是 CPU 内存,显存还是那一张卡);accum16
的 ~4G 增长仍在,bs1 基线低才装得下——**谁再开 bs2 照爆**。248869 系设计外第五臂
(与在跑的 248781 仅差 gb 64/128),去留待用户裁。三个脚本的 WANDB 注记已修正,
248868 在跑改不了注记,以本表为准。

### 08-19 傍晚新增训练(两炉)

| job | 臂 | 数据 | 配置 | 状态 |
|---|---|---|---|---|
| **249492**(原 249458 撤) | **img1** | q38-Bhqs2t-img1-*(6385 条,窗 1,fold 1,cap 同 img3;自助构建,code e6b6e034,双端 md5 + 6385/6385 图片 resolve) | kE 配方同(lr3e-6/3ep/seed 同默认),仅窗口变量;**08-19 重拓扑 2×8→8×1,accum 4→8,gb64 梯度数学不变**(整节点申请卡到次日 01:15;1 卡/节点避 zero2_offload 的 PCIe 争用,实测 2.3× 每 rank;原 sbatch 存 .bak-2x8) | **跑动中**(17:20 排上 8 节点 g001/002/006/010/011/017/019/020;preflight 6385/6385 过,accum=8 生效;用户曾令改 4×2 应对排不上,排上后经确认保持 8×1) |
| **249496**(249457→249486→249496) | **vl20nocap** | q38-Bhqs2t-r5vlnocap-*(6474 条,另一会话建+过闸) | **8 节点×1 卡×bs1×accum8 = gb64**(与 16卡×accum4 梯度等价),**max_length 81920**(smoke 实测 99% 峰值可容;65536-delete 会恰好丢掉 3 条轨迹的 terminate 目标行——19a5b6dd/acd3db2e/128c9ca6 终止行各 18 图),lr1e-5/3ep | **跑动中**(另一会话管理;249486 健康跑 8/306 步后被其主动撤——墙钟 6h 装不下实测 ETA 8.1h(20 图样本 95 s/it),重交 249496 墙钟 10h,vl20g 撞墙教训的前置应用) |

> 扫描 swift 多轮语料的教训:一行 = 截到第 k 步的整段对话,终止调用只在任务
> **最后一行的最后一个 assistant 轮**;读第一个 assistant 轮会得出"全语料无
> terminate"的假象(两个会话同踩)。判据应锚定 tool_call 块内 action 字段。

历史窗 2×2 全景:kE@20 = 57.81%(已有)| img3@20 | kE@3 | img3@3 —— 四格齐后
"训练窗×评测窗"的交互一图定案(img3 训练把视觉 token 砍到 29%,若 img3@3
不掉分,token 经济学成立)。

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
