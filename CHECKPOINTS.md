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

## 2 全臂总表(2026-08-19)

**口径与来源**:超参逐臂取自各 checkpoint 自带的 `args.json`(ms-swift 写的,
不是 sbatch 意图);分数为 `result_dir/**/result.txt` **逐文件**求和 ÷ 50
(缺题记 0;禁 `cat` 拼接,见 `sft/RESULTS.md` §5.12);臂名↔权重映射取自
各 eval 目录的 `MODEL_BOUNDARY.json`。**分数是权重的属性,不是 sbatch 的属性** ——
下表"服务的存档"列凡标注的,都是没跑到终点的权重。

### Qwen3.5-4B 学生线(已 eval)

| 臂 | 权重目录 | 语料 | lr | gb | ep | 微调 | **eval50** | 注 |
|---|---|---|---|---|---|---|---|---|
| **nocap** | `q38Bhqs2t-lr3e6-nocap` | r5nocap | 3e-6 | 64 | 3 | full | **59.81%** | 🏆 最高 |
| **kE / kEh3** | `q38Bhqs2t-lr3e6` | r5 | 3e-6 | 64 | 3 | full | **57.81%** | 同权重,h3=3 图评测窗,分数相同 |
| img3h3 | `q38Bhqs2t-img3-lr3e6` | r5-img3 | 3e-6 | 64 | 3 | full | 53.81% | 3 图训练 × 3 图评(匹配窗) |
| **kD** | `q38Bhqs2t-gb64` | r5 | **1e-5** | 64 | 3 | full | 49.81% | ⚠ **48/50**,缺 2 题记 0;Klone L40S |
| kG | `q38Bhqs2t-loranp` | r5np(去 prose) | 1e-4 | 64 | 3 | lora | 49.81% | |
| img3 | `q38Bhqs2t-img3-lr3e6` | r5-img3 | 3e-6 | 64 | 3 | full | 47.81% | 同 img3h3 权重,20 图评 |
| Bs-LoRA | `q38Bs-lora` | B+cap2048 | 1e-4 | 64 | 3 | lora | 47.81 / 45.81 | ⚠ 服务 ckpt-90(**1.02ep**),终点 264 |
| Bs-gb64 | `q38Bs-gb64` | B+cap2048 | 1e-5 | 64 | 3 | full | 45.81 / 43.81 | ⚠ 同上,服务 ckpt-90 |
| gb128ep2 | `q38e3B-gb128` | B | 1e-5 | 128 | 取 ep2 | full | 43.81% | 49/50;3ep 从未跑完(六连 OOM) |
| B-gb64o | `q38e3B-gb64o` | B | 1e-5 | 64 | 3 | full | 41.81% | 47/50;服务 ckpt-90(1.01ep) |
| r5lora | `q38Bhqs2t-lora` | r5 | 1e-4 | 64 | 3 | lora | 41.81% | |
| kD15 | `q38Bhqs2t-gb64` @ckpt-150 | r5 | 1e-5 | 64 | **1.5** | full | 39.81% | kD 的中途存档 |
| B-1ep | `q38e1B` | B | 1e-5 | **8** | 1 | full | 31.81% | |
| rich | `q38e3-rich` | v11100 | 1e-5 | 8 | 3 | full | 28.00 / 30.00 | 两读数=同配置重跑(§5.7) |
| lean | `q38e3-lean` | v11100 | 1e-5 | 8 | 3 | full | 23.81 / 25.81 | 训练侧 `preserve_thinking false` |

### Qwen3-VL-4B 线

| 臂 | 权重目录 | 语料 | lr | gb | ep | **eval50** |
|---|---|---|---|---|---|---|
| vl20 | `vl20pic-lr1e5` | r5vl(20 图) | 1e-5 | 64 | 3 | **45.81%** |
| vlsft | `q3vl-r5vl-lr3e6` | r5vl | 3e-6 | 64 | 3 | 44.00% |
| gb128 | `vl3pic-gb128-lr1e5` | vl3pic(3 图) | 1e-5 | 128 | 3 | 37.81% |

### 基线

| | eval50 |
|---|---|
| 教师 Qwen3.8-27B(t38) | **69.81%** |
| Qwen3.5-4B 基座 | 39.81% |
| Qwen3-VL-4B 基座 | 33.31% |

### 训练完成但未 eval

| 权重目录 | 语料 | lr | gb | ckpt 数 | 状态 |
|---|---|---|---|---|---|
| **`q38Bhqs-gb64`** | Bhqs-v11100 | 1e-5 | 64 | 9 | Bhqs-1;sbatch 明写"不花 eval slot",被 curation rev2 取代 |
| `q38Bhqs2t-img1-lr3e6` | r5-img1 | 3e-6 | 64 | 12 | 完训,链上待评 |
| **`vl3pic-base`**(=vl3b) | vl3pic | 3e-6 | 64 | 12 | 完训待评;**gb128 的干净拆解** |
| **`vl20pic-gb128-lr1e5`**(=vl20g) | r5vl | 1e-5 | **128** | 4 | 完训待评;累积 lr 7.5e-4 = §5.13 剂量曲线中点 |
| `q38Bhqs2t-nocapnp` | r5nocapnp | 3e-6 | 64 | 2 | 在训 |
| `vl20nocap-lr1e5` | r5vlnocap | 1e-5 | 64 | 2 | 训练已停(0.6ep,非完整臂) |
| `q38Bhqs2t-nocaplean` · `vlnocapnp-lr3e6` | — | 3e-6 | 64 | **0** | 无存档 |
| `q38e3B-gb128o` | B | 1e-5 | 128 | **0** | 六连 OOM 全灭 |
| `q38e3B` | B | 1e-5 | 8 | 1 | 未评 |

早期 9 题面板时代(`e1`/`e3`/`more`/`more3`/`more3np`/`ep5np`/`ep5pt`,
全部 lr 1e-5、gb 8、abs-pilot 语料)与 eval50 口径不可比,不列入。

### 从这张表读出来的三件事

1. **lr 只有两档**:1e-5 与 3e-6。**5e-6 全项目空白** —— `sft/sbatch/` 里
   `sft-q38Bhqs-lr5e6.sbatch` 与 `-lr3e6.sbatch` 都自称
   "EXACT twin of Bhqs-gb64 except learning_rate",但 Tillicum `out/` 无产出、
   全库 md 无结果:**这组三点单变量 lr 曲线设计好了从没跑**。
2. **三个臂的分数其实是 1 epoch 权重**(Bs-gb64 / Bs-LoRA / B-gb64o 都服务
   ckpt-90,因挑选器按字典序取)。与 3ep 臂并排读会低估。
3. **kD vs kE 的 +8pp 被缺题放大**:kD 只有 48/50,缺 2 题按 0 入分,
   光这一项最多压低 4pp(每题 2pp)。kD 上界 53.81% 与 kE 57.81% 之差
   落在 5-6pp 噪声底内,再叠加语义(拆行/合并)与硬件(Klone/Tillicum)两个
   混杂 —— **"3e-6 优于 1e-5"目前不是干净结论**,干净做法是只比共同题。

## 2.1 存储占用盘点(2026-08-17 07:00,总占用 4.1 TB)

> **只看体积。** 本表的 eval 列是 08-17 当时的整数题数口径(不含部分分),
> 已被 §2 总表取代;引用分数请用 §2 或 `sft/RESULTS.md` §6。

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

## 2.2 在训/待训模型登记(2026-08-19 深夜更新;eval 顺序=用户令)

当前链(`tools/tillicum_chain.sh`,全 no-split,08-19 深夜版):**vl20(跑动中)
→ kEh1 → baseh1 → nocapt0 → nocapnp → img1 → vlnocapnp(尾,训练 249567
完训闸)**,
之后 eval100 决赛。baseh1/vlbaseh1 = 两个未训基座 @ 1 图窗(用户令);
nocapt0 = 冠军贪心重跑;后三臂带完训闸。kF 不排;vl3b/vl20g 已撤评
(训毕保留待评,见下方撤单注记);nocaplean 已撤(前提反转,见其行)。
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

**vl3b/vl20g 评测撤单(08-19 深夜,用户令)**:两炉训练**完整**在盘
(out/vl3pic-base 12 ckpt 至 checkpoint-300、out/vl20pic-gb128-lr1e5 15 ckpt
至 checkpoint-150,均满 3 epoch),eval 臂从链上撤下——eval 已成瓶颈
(彼时 9 臂待评 18-27h),而"VL 骨干负收益"已由 vlsft 44.00 vs kE 57.81
立住,这两个细分变体信息量最低。**归类:保留待评,不许清理**;随时可
按原臂配置(vl3b @3图匹配窗、vl20g @20图,均 json)补评。
**vl20nc 同令撤评,训练亦停(用户令"不评就释放资源")**:249500 中止于
**66/306(仅 0.6 epoch,checkpoint-30/60)——非完整臂**,与 vl3b/vl20g 的
"完整 3ep 训毕待评"性质不同,补评前必须先补训;释放 g[001,004,017,020]。
**vlbaseh1 同令撤**(VL 线连基座参照一起清空)。用户点名必跑:img1、kEh1、
baseh1、nocapt0(nocapnp 原位保留);serve-chain-vl20nocap-stock.sbatch
(8044)留盘。

OOM 验尸(248818/248809,均第 8/16 步死):峰值 ∝ bs × 批内最长样本(语料 max
39,552 token);bs2 两条长样本同批 → 136G+34G 索求 > 139.79G。**治好它的是
bs2→1,不是节点拓扑**(1 rank/节点多的是 CPU 内存,显存还是那一张卡);accum16
的 ~4G 增长仍在,bs1 基线低才装得下——**谁再开 bs2 照爆**。248869 系设计外第五臂
(与在跑的 248781 仅差 gb 64/128),去留待用户裁。三个脚本的 WANDB 注记已修正,
248868 在跑改不了注记,以本表为准。

### 08-19 傍晚新增训练(两炉)

| job | 臂 | 数据 | 配置 | 状态 |
|---|---|---|---|---|
| **249492**(原 249458 撤) | **img1** | q38-Bhqs2t-img1-*(6385 条,窗 1,fold 1,cap 同 img3;自助构建,code e6b6e034,双端 md5 + 6385/6385 图片 resolve) | kE 配方同(lr3e-6/3ep/seed 同默认),仅窗口变量;**08-19 重拓扑 2×8→8×1,accum 4→8,gb64 梯度数学不变**(整节点申请卡到次日 01:15,碎片单卡秒排——**调度差异是唯一成立的理由**;曾附的"1 卡/节点避 PCIe 争用快 2.3×/rank"归因已由另一会话撤回:误把续训作业的墙钟除以全步数,拓扑对吞吐的影响**无定论**,教训见 TRAINING.md;原 sbatch 注记已同步撤回标注,存 .bak-2x8) | **完训**(EXIT 0,1h42m,endpoint=checkpoint-300 @epoch3.00,12 ckpt;eval 臂 img1 已接链 @1图匹配窗;当时 8 节点 g001/002/006/010/011/017/019/020,新规前豁免形状) |
| **249500**(249457→249486→249496→249500,定稿) | **vl20nocap** | q38-Bhqs2t-r5vlnocap-*(6474 条,另一会话建+过闸) | **4 节点×2 卡×bs1×accum8 = gb64**(用户新规 ≤4 节点;训练超参与 249486 一字未动,cpus 16/mem 400G/墙钟 10h——实测 95.87 s/it×306 步=8h09m,6h 会在 74% 处砍出一个"看着像 3ep 实为 2.2ep"的不可比 checkpoint),**max_length 81920**(smoke 实测 99% 峰值可容;65536-delete 会恰好丢掉 3 条轨迹的 terminate 目标行——19a5b6dd/acd3db2e/128c9ca6 终止行各 18 图),lr1e-5/3ep | **跑动中**(另一会话管理,g[001,004,017,020];249486 撤于墙钟 6h<ETA 8.1h、249496 撤于拓扑新规,两次都在个位数步、零 checkpoint 损失) |
| ~~249536~~ | ~~nocaplean~~ | r5nocap 同 nocap | nocap 配方 + preserve_thinking false | **已撤(用户令,27/306,零 ckpt 损失)**:真实 payload 渲染证明 **eval 历史 think 全保留(27/27)**——"匹配 eval 模板"的立项前提反了,false 训的是最坏方向 skew;旧 lean/rich(23.81<28.00)同向。eval 臂已撤、img1 重连 nocapnp;serve-chain-4b-nocaplean-stock.sbatch 留盘未用。§5.14/CONTEXT§4 口径修正由 64333 会话统一负责 |
| **249612** | **np2e6** | r5nocapnp 同 nocapnp | **nocapnp 配方唯一变量 lr 3e-6→2e-6**(累积 3.1e-4,冠军剂量 4.5e-4 以左从未采样区;4×2/3ep/81920/save34);对照 nocapnp;用户阶梯假设:loss 台阶轻→分高 | 排队(与 249613 同波,等 01:10 nocapnp 释放) |
| **249613** | **np1e6e5** | r5nocapnp 同 nocapnp | **lr 1e-6 × 5ep**(累积 2.6e-4 ≈ np2e6 的 3.1e-4,差 20%)——**与 np2e6 构成"总剂量 vs 重复次数"配对**:重复记忆有害则输给 np2e6,只看剂量则平;510 步,墙钟 12h(实测 74s/it≈10.5h) | 排队 |
| 249567 | vlnocapnp(另一会话) | r5vlnocapnp(VL 语料,think 无 cap + 去 prose,strip_prose d7d14632) | 4×2×bs1×accum8=gb64,lr3e-6/3ep,81920,freeze_vit;对照 vlsft 44.00(cap+prose 双变量);硬证据:no-prose 模型 eval 输出 0/1293 含 prose | 排队(12h 墙钟);eval 臂 vlnocapnp 已接链尾 @标准20图+json |
| **249538**(249531→249537→249538) | nocapnp(同事建,我修数据) | r5nocapnp(prose 唯一变量,ostg strip_prose 56a3bb70;**249537 四秒死于 preflight:13,436 引用全是相对路径且目录无 images/——jsonl 已改写为指向 r5nocap 绝对路径(截图逐名复用,零传输),6474 行 63,146 引用 0 缺失,原文件存 .bak-relpaths;**同事从源头重生成交叉验证:两 pool 逐字节一致 630f0350/bce56618**;builder 已修 --images-prefix d7d14632**) | **4×2×bs1×accum8=gb64**、墙钟 10h、81920;对照 nocap 59.81,先验 kG +8pp | **死于 73%**(step 226/306,cuDNN fused-attention 在 checkpointing 反向重算时申请 workspace 失败——该路径不走 caching allocator 故无重试,而全程 136.7/139.79 GiB;留下 v0 ckpt-204 @ epoch 2.00)→ **16 卡重训 249689 排队中** |

**nocapnp 与 nocap 不是严格单变量对(2026-08-20 补,另一会话指出)**:除散文外还差
`max_length 65536 → 81920`。算术自洽旁证:语料 6474 条,nocapnp(81920)全留 →
102 步/epoch → **306 步**;nocap(65536)丢掉 14 条超长样本 → 6460 条 →
101 步/epoch → **303 步**,两边步数差正好由那 14 条解释。所以"prose is the only
variable"应读作"prose + 14 条超长样本的去留"。

**中途快照读法警告(nocapnp2 臂适用)**:ckpt-204 **不是"2 epoch 模型"而是
"跑到 2 epoch 的中途快照"** —— cosine schedule 按 306 步定,该点学习率仍有
**9.08e-7**(峰值 3e-6 的 30%),整段退火没走完;实测同族对照 nocap ckpt-210
@epoch2.079 是 7.85e-7、其终点 ckpt-303 才降到 1.0e-10。故 nocapnp2 **系统性
偏低,幅度未知**,只能读"崩没崩",不能读"提升多少"。若要让散文重新成为唯一
变量,现成对照是 **nocap ckpt-210**(同阶段未退火,权重在盘,只花一个 eval 槽)。

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
