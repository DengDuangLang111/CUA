# TMAX-9B → v11 r5 CUA SFT 实验计划

**训练后的操作入口（2026-09-16 更新）**：复用 [SFT → Klone serving → eval 操作说明](../docs/EVAL_AUTOMATION.md#从-sft-到评测复用入口)。其中包含 step306 的配置示例、直接传输校验、Slurm 服务准备、两台 Windows 的 registry/并发衔接、Verified100 命令和恢复方法。准备脚本本地测试通过不代表本轮已完成传输或启动评测；下面作业号与进度仍是各自日期的历史记录。

更新：2026-09-15 19:25 PDT。用户已授权在 Tillicum 部署，最终配置为 **4 张 H200、最多2个节点、跳过冒烟直接正式训练、时限8小时**。作业 **296948** 已提交，申请 **1节点×4 H200**；19:25通过scontrol原位将时限从24h缩短为8h，保留作业号和原提交时间。旧 OSWorld2 试跑未因本次部署被修改。

## 2026-09-16 13:14：最后一段续训

297496已于10:03因8h时间限制停止，最新完整checkpoint为 `v1-20260916-020337/checkpoint-272`，不是进度条最后显示的285。已重新核对完整模型/optimizer/RNG/scheduler并提交 **297872**，从272接到总306步；4H200、800G RAM、32CPU不变，时限3h。提交时PENDING/Priority，无调度开始时间预测。剩34步预计约89分钟实际训练，另加加载、保存与排队；最终完成需确认checkpoint-306和作业成功退出。记录见部署目录的`finish-job.json`。

## 2026-09-16 续训记录

原作业296948在01:03因**主机内存OOM**退出（Slurm MaxRSS419361900K，申请400G），不是8h超时。日志运行到136/306附近，但checkpoint-136没有完整保存；恢复点为 `out/tmax9b-full-r5-ml65k/v0-20260915-193501/checkpoint-102`。已核对trainer_state/global_step102、全部模型分片边界与索引、四组optimizer/RNG、scheduler及checkpoint ZIP目录。

复用同一个训练脚本，以 `RESUME_FROM` 启用完整恢复（`resume_only_model=false`），继续原3epoch/306总步，不重置optimizer、scheduler或warmup。申请1节点4H200、800G内存、32CPU、8h；其它训练参数保持。Swift创建新的v1输出目录，旧v0和检查点保留。32CPU用于匹配大内存资源分配，避免Slurm自动调整CPUS_PER_TASK后与TRES_PER_TASK冲突。

当前续训作业 **297496**，g017；已实际续到**104/306**，学习率2.51e-6，`resume_only_model=false`。原/新args关键配方一致，原数据SHA一致，W&B：[6k8109qq](https://wandb.ai/yanjiayuan/cua-sft/runs/6k8109qq)。297495因上述CPU环境变量冲突在训练前退出，记录保留。部署/申请记录在 `/gpfs/scrubbed/jy050706/sft/deploy/tmax9b-r5-resume-20260916/`，日志 `tmax9b_r5_297496.out`。上轮约144.5秒/步，从102到306还需约8.2小时；时限仍遵循用户8h要求，若达到时限，依据新保存的完整checkpoint继续，不能把提交或启动算作306步已完成。

## 1. 要回答的问题

在同一份 v11 r5 数据、同一 CUA SFT 配方和同一评测协议下，把语言模型初始化从原始 Qwen3.5-9B 换成经过 terminal RL 的 TMAX-9B，能否提高 CUA 表现？

首轮只改变语言模型初始化。沿用旧 r5 已完成的数据处理，不增加 v16、不重新生成 rollout、不再做一遍 terminalfix，也不同时改学习率、图像预算或 loss 权重。

“r5 tmf”在本计划中按**旧 a2 / img10-9b 使用的 r5 terminalfix 版本**理解。仓库没有独立 `tmf` 语料登记；本计划用下面的两个具体数据文件及 SHA-256 固定含义。若用户指另一版本，应先更新此映射，不能静默换数据。

## 2. 已准备的输入

### 论文

- **Tmax: A simple recipe for terminal agents**，arXiv `2606.23321v1`，20 页。
- Mac 文件：[2606.23321v1.pdf](/Users/knight/uw/paper/cua/2606.23321v1.pdf)。
- 大小：948,653 bytes；SHA-256：`00fd77e4a4212c7616863d13a7439d1fc3ba62bdc29455f604fbf647d456b0f3`。
- 已读与本实验相关的模型来源、迁移结果、SFT 讨论及对应表格。论文报告 terminal 训练的跨任务/跨 harness 收益；**没有验证恢复视觉模块后再做 GUI SFT 的效果**。§5.1 的 SFT 结果也不是本计划的“terminal RL → GUI SFT”实验，不能直接作为这里会提升或退化的结论。[论文](https://arxiv.org/pdf/2606.23321v1)

### TMAX 原始模型：已下载并校验

| 项目 | 固定值 |
|---|---|
| 来源 | [`allenai/tmax-9b`](https://huggingface.co/allenai/tmax-9b) |
| HF revision | `81ec54b29986d78191596d81900c0f8de2fa1b35` |
| 发布版本 | 模型卡所述的 RL step 200 checkpoint |
| Klone 目录 | `/gscratch/cse/jy050706/sft/models/tmax-9b` |
| Tillicum 目录 | `/gpfs/scrubbed/jy050706/sft/models/tmax-9b`，已独立下载相同revision并校验 |
| 已装配 CUA 初始化 | `/gpfs/scrubbed/jy050706/sft/models/tmax-9b-cua-init`，manifest状态verified |
| 文件范围 | 8 个根目录模型/配置/tokenizer 文件；未下载附带的 terminal rollout 档案 |
| 总大小 | 17,927,685,433 bytes，约 17.93 GB |
| 主权重 | `model.safetensors`，17,907,663,008 bytes |
| 主权重 SHA-256 | `4ed8d66d0a4b71aac79a98502882f88f5e53bb98251d19b0a88e237bacb7c052` |
| 实际张量 | 427 个，全部 BF16；8,953,803,264 个参数 |
| 验收记录 | 模型目录下 `DOWNLOAD_MANIFEST.json`；另见 `sft/downloads/tmax-9b-81ec54b/verified.json` |

模型卡说明它从 Qwen3.5-9B 进行 terminal DPPO 训练，并移除了视觉模块，示例使用 `--language_model_only`。这里已直接读取 safetensors 文件头，确认没有 `model.visual.*` 张量。模型卡的训练 FP32 LM-head 设置不等于发布权重的 dtype；下载文件中的 `lm_head.weight` 实际是 BF16。[模型卡](https://huggingface.co/allenai/tmax-9b)

## 3. 必须先恢复完整的截图输入结构

**不能直接把原 SFT 命令中的 `--model` 换成 TMAX 目录。** `config.json` 虽然保留 `Qwen3_5ForConditionalGeneration` 和 vision_config，文件中并没有视觉权重，也缺少图像 processor 文件。

已与 Klone 原始 `/gscratch/cse/jy050706/sft/models/Qwen3.5-9B` 对比：

| 部分 | 核对结果 | 初始化来源 |
|---|---|---|
| language model + LM head | TMAX 的 427 个键全部能在原模型中找到，形状全部一致，无意外键 | **TMAX 发布权重** |
| `model.visual.*`，包括 merger | 原模型有 333 个键，TMAX 全部缺失 | **原始 Qwen3.5-9B** |
| `mtp.*` | 原模型另有 15 个键，TMAX 缺失 | 保留原始值作结构兼容；本实验不开 MTP 辅助损失或 speculative decoding |
| config | text_config、vision_config 一致；图像/视频及视觉边界 token ID 一致 | 使用原完整结构，保存两份来源配置供比对 |
| tokenizer | 普通词表的 token→ID 一致；merges 规范化格式后相同；TMAX 多 7 个 audio/TTS added tokens | CUA 路径沿用冻结的原 Qwen tokenizer，沿用原tokenizer；用户已取消额外编码/训练冒烟 |

以下装配已在 Tillicum 完成，TMAX语言分片逐文件SHA一致，补入张量逐个比较一致；原始输入目录保持不变。具体做法：

1. 新建独立的 **`tmax-9b-cua-init`**，不覆盖两份原始模型。
2. 保留 TMAX 的 427 个张量；从原 Qwen 补入 333 个视觉张量和 15 个 MTP 张量。不能把缺失视觉模块留给随机初始化，也不能回填未知的语言层。
3. 采用一个明确的 safetensors index：TMAX 语言权重文件 + 只含补入张量的 companion shard。**不把包含整套原语言权重的 Qwen 分片直接混进新目录**，避免加载顺序覆盖 TMAX 参数。
4. 复制原 Qwen 的 image/video processor 配置；CUA 训练与评测沿用同一套冻结模板和 computer 工具定义。TMAX 的 terminal system prompt、terminal 工具配置不带入 CUA。
5. 不扩大 embedding、不重排词表。检查真实 r5 文本及 image/tool/think 特殊标记的 token IDs；7 个额外 audio/TTS token 的处理必须记录，不能把不同 tokenizer 文件当成字节相同。
6. 写 `INIT_MANIFEST.json`：两份来源、HF revision、原模型分片哈希、逐组张量数量、形状/dtype、processor/template 哈希、MTP 是否使用。框架若忽略 MTP 键，必须按明确清单核对；其他 missing/unexpected keys 均视为失败。

这一步只是结构和初始化准备，不能据此声称恢复了原来的 GUI 能力。

## 4. 数据：复用旧 r5 成品

Klone 数据根目录：`/gscratch/cse/jy050706/sft/data/`。2026-09-15 已逐文件核对：

| 数据目录 | 轨迹数 | 训练行数 | 去重图片数 | 最后目标含 terminate |
|---|---:|---:|---:|---:|
| `q38-Bhqs2t-r5nocapimg10-v11100` | 75 | 1,358 | 1,358 | 75/75 |
| `q38-Bhqs2t-r5nocapimg10-v11500` | 287 | 5,116 | 5,131 | 287/287 |
| 合计 | **362** | **6,474** | **6,489** | **362/362** |

冻结的源文件均为各目录下的 `train_swift.jsonl`：

```text
v11100 SHA-256  8b51274fc75995fd23feeb37c476ebbf2c992e52e6cabe11964cee4d4f36394f
v11500 SHA-256  58742f01056c742da1e4a37fa715e656f00f6281982a0377446649988151cdc7
```

这份 r5 为训练时 **img10 / fold1、think 不截断、末步已做 terminalfix** 的版本。不要误用旧的 `r5.cap2k.img20`、v11new、mixB 或 mixbtf。

JSON 当前图片路径仍指向 `/gpfs/scrubbed/jy050706/sft/...`。在 Klone 上按根目录映射后，**6,489/6,489 张图片都存在**；原路径在 Klone 不可直接解析。若在 Klone 训练，只生成新的路径适配 JSON，冻结源文件不改；若回 Tillicum 训练，则复核原路径和文件。用现有 data/verify 工具检查图片占位符、目标文本、轨迹边界和末步规范，不能因图片路径错误而退化为纯文本 SFT。

## 5. 训练配方与对照

主对照：旧 `a2 / img10-9b`，已登记为 `9b-full-r5`；历史评测结果的 `@20f10` 是**推理窗口**，不是训练窗口。

| 项目 | 首轮设置 |
|---|---|
| 训练方式 | 复用旧 `tuner_type=full`；语言模型全参数 SFT，不改成 LoRA |
| 视觉冻结 | 旧 Swift 配方的 `freeze_vit=true`、`freeze_aligner=true`；执行前以 a2 实际 args 和 trainable-parameter 清单复核 |
| 数据 | 上述两份 r5；6,474 行；不增加验证切分或重新筛选 |
| 图像窗口 | 数据中固定 img10 / fold1；`IMAGE_MAX_TOKEN_NUM=2048` |
| loss | `last_round`，保留最后 assistant 的 thinking 和 action；维持原 channel-loss 行为，无新 token/trajectory 加权 |
| `preserve_thinking`（训练） | **true**，沿用旧 SFT 配方；不照搬当前 OSWorld2 teacher 试跑的推理开关 |
| 学习率 / 调度 | `3e-6` / cosine；warmup ratio `0.1` |
| epoch / global batch | `3` / `64` |
| micro batch | 每卡 `1` |
| 本次拓扑 | **1节点×4 H200×batch1×accum16=64**；最多2节点。旧a2为4×2×accum8，拓扑变化单独记录 |
| 作业时限 | **08:00:00**；按用户要求缩短以便回填调度。训练仍为306步；若超时，需从已保存的完整checkpoint续训 |
| 优化器 | 旧 AdamW 配置；weight decay `0`，beta2 `0.999`；beta1=0.9、epsilon=1e-8、seed=data_seed=42（实际旧args已核对） |
| 精度 / attention | BF16 / SDPA，沿用旧版本与必要运行时修复 |
| 内存设置 | **`max_length=65536`**、gradient checkpointing、`zero2_offload`，与旧配方核对 |
| 步数 | `ceil(6474/64)=102` step/epoch，合计 **306** steps |
| checkpoint | 每34步保存，limit12；保留102/204/306，主结果固定epoch3/step306 |

历史账本记录 a2 的 9B/img10 配方曾达到约 115.8 GiB/GPU；当前 teacher 的 2×L40S 不是这份训练配方的直接替代。**本次已采用 Tillicum H200 训练环境**，Klone 保留下载权重和数据副本。若需要在 Klone 训练，按 [KLONE.md](../docs/KLONE.md) 另列资源适配，不能悄悄缩图、换量化或改训练方式。

已读取 Tillicum 原始 `$B/img10-9b.sbatch`（在根目录，不在sbatch子目录）、`out/img10-9b/v0-20260822-024940/args.json`；checkpoint-306仍在。真实a2的max_length=65536、seed/data_seed=42、beta1=0.9、epsilon=1e-8、save_steps=34、limit=12、freeze_vit/aligner=True，均据此对齐。环境：Python3.11.15、torch2.13.0、transformers5.15.0、ms-swift4.5.0.dev0、DeepSpeed0.19.5。运行沿用已有nocudnn补丁以禁用cuDNN SDPA；此运行时差别写入deployment.json，不冒称与历史内核逐位相同。

## 6. 最小实验矩阵与评测

| 臂 | 初始化 | CUA SFT | 用途 |
|---|---|---|---|
| A：`9b-full-r5` | 原始 Qwen3.5-9B | 旧 r5 同配方 | 主对照；优先复用核验后的旧权重，在当前固定协议下重评 |
| C：`tmax9b-full-r5-ml65k` | TMAX 语言权重 + 原 Qwen 视觉组件 | 同一份 r5、同一配方 | 本次唯一新训练的主臂 |
| B：`tmax9b-base`（可选） | 同 C 的装配起点 | 无本项目 CUA SFT | 分离初始化零点与 CUA SFT 增量；先用于加载/工具格式冒烟，不强制追加完整大评测 |

`tmax9b` 已登记为本实验骨干标记；`base` 只表示未做本项目 CUA SFT，不表示没有 terminal RL。`armname.py` 已支持从非Qwen模型路径提取登记过的骨干，旧配方命名回归通过；本次规范名带 `ml65k` 以准确表示65536长度。

主评测采用原 SFT 研究线的 **OSWorld Verified 冻结 eval100**：

- A/C 使用同一 task manifest/hash、同一 harness commit、host/VM 镜像、工具定义、服务精度与解码参数。
- 首选两臂都按训练匹配的 `image_max=10 / fold_size=1` 重评；max_steps 50、temperature 1.0、top_p 0.95、max_tokens 81920 作为现有命名标准的起点，启动时把所有实际参数写入配置。
- inference 的 `enable_thinking`、`preserve_thinking` 和具体 template 必须两臂一致，并用真实请求验证；不能把训练的 preserve 标志当推理实测，也不能自动继承另一个 teacher/V2 run。
- 历史 a2 的 61.0% / 均分62.9 来自 `@20f10`，仅作背景；不直接与新 `@10f1` 相减。若必须复现旧表，则 A/C 都另用同一 `@20f10`。
- 主要报告满分通过率、含部分分的均分及逐题配对变化；环境异常、缺结果和模型实际0分分开列。
- 记录输出/think token、步数、重复动作和工具格式错误，复用原始轨迹分析，不生成 LLM 失败总结。
- 每题结束默认接现有 recorder → ready record → 独立 post-processing → 轨迹网页/Index。主对照的采集范围保持一致；视觉信号只给实际 full-attention 层配置，例如本模型最后一层为31，不能照搬27B的L63。
- OSWorld2 作为后续外部迁移检查，单独记账，不与 Verified eval100 混分母。Terminal 能力保留测试可后续增加，首轮不开展学习率网格或多数据配比。

## 7. 执行顺序与验收

1. **冻结输入**：确认本计划采用的 r5 版本，保留两份数据 SHA、模型下载 manifest，恢复 a2 的实际训练参数与可比 checkpoint。
2. **装配 CUA 初始化**：新增一个小型权重装配工具；输出独立目录和 manifest。验证427个TMAX张量没有被原始语言权重覆盖，补入键严格属于视觉/MTP清单，无随机视觉初始化。
3. **已完成的静态准备**：config、processor、词表和张量结构已核对；Tillicum的6489张图片存在且两份数据SHA与冻结值相同；视觉组件冻结，MTP不参与目标。
4. **按用户最新指令跳过额外测试**：不执行GPU冒烟，也不增加待执行的测试依赖。权重装配的3个回归测试在该指令前已通过；没有把它们写成GPU/显存验收。
5. **完整 SFT**：作业296948从装配权重直接开始306步训练，没有smoke产物或smoke阶段；当前等待Slurm分配4张H200。
6. **配对 eval**：先核对A/C同协议，再运行固定eval100；检查首题网页、截图、原始记录及最终评分输入。正常网页不等于采集完整，必须检查validation结果。
7. **结果归档**：记录训练参数/代码hash、模型谱系、数据hash、原始得分、错误题、配对表和轨迹链接；在 `RESULTS.md` 登记实际结果，不预填提升结论。

最小代码改动预计是：一个 checkpoint 装配工具、一个从旧配方派生的训练脚本、`armname.py` 对新骨干的支持，以及相应的键映射/编码检查。数据 builder、任务生成、评分器和既有网页框架不需要重写。

### 当前完成状态

- [x] PDF 已保存，标题和20页内容确认。
- [x] TMAX step200 固定revision的8个文件下载完成，大小和LFS SHA-256校验通过。
- [x] TMAX/原Qwen键与形状、config、tokenizer差异已核对。
- [x] 旧r5的行数、轨迹数、terminate末步、源文件SHA和Klone图片副本已核对。
- [x] a2实际sbatch/args/checkpoint已读取，4张整卡H200配置已确定。
- [x] 视觉结构装配完成，427个语言张量和348个补入张量验证通过。
- [x] 正式训练已提交：296948，初始状态PENDING/Priority；无smoke。
- [ ] 资源分配、正式训练完成及新模型评测。

部署目录：`/gpfs/scrubbed/jy050706/sft/deploy/tmax9b-r5-20260915/`。`deployment.json`保存基线参数、数据/代码/初始化hash；`job.json`保存作业号。训练输出：`/gpfs/scrubbed/jy050706/sft/out/tmax9b-full-r5-ml65k/`；日志：`/gpfs/scrubbed/jy050706/sft/tmax9b_r5_296948.out`。训练脚本：[tmax9b-r5.sbatch](../scripts/train/tmax9b-r5.sbatch)，装配工具：[restore_vision.py](../data/restore_vision.py)。

## 8. 原始证据和项目入口

- [TMAX模型与模型卡](https://huggingface.co/allenai/tmax-9b)、[固定revision文件](https://huggingface.co/allenai/tmax-9b/tree/81ec54b29986d78191596d81900c0f8de2fa1b35)、[论文v1](https://arxiv.org/pdf/2606.23321v1)。
- Klone：`/gscratch/cse/jy050706/sft/downloads/tmax-9b-81ec54b/` 下的 `remote-manifest.json`、`verified.json`、`compatibility.json`、`tokenizer-compatibility.json`、`tokenizer-differences.json`。
- [命名规范](../../docs/NAMING.md)、[旧训练与loss口径](../../outdated/docs/SFT_TRAINING_20260822.md)、[数据/权重台账](../docs/CHECKPOINTS.md)、[Klone资源约束](../docs/KLONE.md)、[默认评测管道](../docs/TRAINING.md)。
