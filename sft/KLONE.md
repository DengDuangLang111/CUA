# 在 Klone 上训练:环境、启动方式、以及三次 OOM 的机理

> 2026-08-28 建。Tillicum 之外的第二条训练链路。**这里只放 Klone 特有的事实**;
> 配方本身(lr / epoch / loss_scale / 步数算术)在 `sft/TRAINING.md`,不重复。
>
> 写这份文档的直接原因:同一批坑在两个 session 里各踩了一遍。

## 0 一句话

Klone 能训 9B,但**节点形状与 Tillicum 差得远**(80GB 显存 / 只有 64GB 主机内存,
对 Tillicum 的 400GB),这一条否掉了 a2 原配方的 offload 路线,并把
**跨节点通信**变成主要成本 —— 306 步在这里要 70-85 小时,Tillicum 上是 6.4 小时。

## 1 硬件与账号(实测,不是文档抄的)

```
NVIDIA A100 80GB PCIe · 81920 MiB · driver 580.178.04 · compute_cap 8.0
```

| 事实 | 后果 |
|---|---|
| **80 GB**(不是 40G) | 9B 全参 + a2 的 2040tok 装不下,必须降 token 或分片 |
| **sm_80** | **FP8 不可用**(需 sm_89+)。serve 侧 `--kv-cache-dtype fp8` 必须改 `auto`;`*-FP8` 权重在 A100 上跑不了 |
| **PCIe 版,不是 SXM** | 卡间无 NVLink;跨节点更是走网络 |
| driver 580 | ✅ 支持 CUDA 13 / torch cu130 |

**账号必须用 `gpu-a100-krishna`**:

```
gpu-a100-cse       MaxWall = 1-00:00:00   ← 只能 1 天
gpu-a100-krishna   MaxWall = (无限制)      ← 7 天占位作业就在这
```

放 cse 会在提交时被 `AssocMaxWallDurationPerJobLimit` 直接拒。
另注 **krishna 的 CPU 很紧**(39 总额,四个占位各 8 = 32),编排作业申请 8 CPU
会 `AssocGrpCpuLimit` 排不上,给 2 就够。

存储:`/gscratch/cse`(剩 ~1.2TB,inode 已用 86%)、`/gscratch/krishna`(99% 满,
inode 97%,**不要往里灌小文件**)、home 仅 10GB **写满会让整个账户登不上去**。

## 2 环境:用容器,不要搬 venv

`/gscratch/cse/jy050706/sif/sft-train.sif` (5.8G),定义在 `sft-train.def`。

**为什么不是 venv**:Tillicum 的 venv 有 **50,579 个文件**,而 `/gscratch/cse` 的
inode 配额已用 86%,且 GPFS 处理小文件极差(八月三次卡死都是这个模式)。
SIF 是单文件 = 1 个 inode + 一次顺序读,正是 GPFS 擅长的。

版本**逐包**复现自 Tillicum freeze(180 包):

```
Python 3.11.15        ← uv 装。ubuntu22.04 只有 3.10、24.04 是 3.12,apt 装不到
torch 2.13.0+cu130    ← 含 sm_80,原版 wheel 覆盖 Ampere,不用降版本
transformers 5.15.0 · deepspeed 0.19.5 · torchvision 0.28.0+cu130
ms_swift 4.5.0.dev0 @ git 1a7977b7f36025b0bb7528ec121cd3feac3032e3
wandb 0.28.2 · pillow 11.3.0 · fsspec 2026.7.0 · pandas 2.3.3
```

**两个必须知道的构建坑**:

1. **不要手列包**。第一版手写 12 个包 + `--no-deps` 装 ms-swift,结果只有 93 个包,
   **漏了 wandb(完全没法上报)、json_repair(`swift.loss_scale` import 就炸)、
   fla-core/flash-linear-attention**(Qwen3.5 文本栈 32 层里 24 层是 linear
   attention),还有一批版本漂移(pandas 2.3.3→3.0.5 跨大版本)。
   正确做法:从 Tillicum 导出完整 freeze,除 torch/torchvision/ms_swift 外全部照装。
2. **必须 `--no-deps`,原因反直觉**:Tillicum 环境**自身不满足自己的依赖声明**
   (`datasets 4.8.4` 要求 `fsspec<=2026.2.0`,实际装的是 `2026.7.0`)。pip 允许
   后装的包顶掉先前约束,uv 的解析器直接拒(`No solution found`)。目标是与产出
   a2 的环境逐包一致,不是一棵自洽的依赖树,所以按清单硬装、不做解析。

**build 必须在节点本地盘**(`APPTAINER_TMPDIR`/`CACHEDIR` 都指 `$SLURM_TMPDIR`):
gscratch 上 build 曾 >50 分钟未完成,本地盘 5 分 17 秒。构建完的单个 SIF 写回
gscratch 只要 **2.87 秒**(5.8G)—— 大文件顺序写正是 GPFS 的强项。

## 3 数据:模型走 HF,语料只能从 Tillicum 传

**带宽差 12 倍,别选错**:

| 路径 | 实测 |
|---|---|
| HF → Klone 登录节点 | **98 MB/s**(80G 权重约 15 分钟) |
| Tillicum → WSL → Klone 管道 | **< 8.5 MB/s**(3.6G 语料花了 11 分钟) |

模型权重(`Qwen/Qwen3.5-4B` `-9B` `Qwen/Qwen3.8-27B`)都是公开 apache-2.0,
`gated:false`,**直接从 HF 拉**,不要从 Tillicum 拷。注意 HF 上的分片名是
`model.safetensors-0000N-of-0000M.safetensors`(非常规命名),transformers 靠
读 `index.json` 而不是命名约定,能正确加载 —— 已验证。

语料没有公开源,只能走管道。两集群**文件系统不通**,Klone 也**没有免密到
Tillicum**,所以用 WSL 做中转(两端各有 ControlMaster,数据不落地):

```bash
ssh -n tillicum "tar cf - -C <src> <dirs>" | ssh klone "tar xf - -C <dst>"
```

## 4 图片路径:必须两个 bind,少一个就静默失败

语料 jsonl 里是**写死的绝对路径** `/gpfs/scrubbed/jy050706/sft/data/...`,
而 Klone 根本没有 `/gpfs`。不改 6474 条记录,用 bind 映射:

```bash
--bind $BASE:$BASE                                    # jsonl 文件本身可读
--bind $BASE/sft/data:/gpfs/scrubbed/jy050706/sft/data # jsonl 内部的图片路径可解析
```

**两个都要给**,它们各管一件事。第一次只给了后者,preflight 直接
`FileNotFoundError` 在 jsonl 上 —— 还没走到查图片就死了。

**preflight 必须在容器内、bind 之后跑**,逐条 stat 全部图片引用
(img10 两份语料共 **48,741 个引用**,正确时 0 unresolved)。
不验的失败模式是**静默地只拿文本训练**,不报错 —— 见 `DATA_PIPELINE.md` 静默失效那节。

## 5 启动:钻进预先占好的卡,不新申请 GPU

用户会预先用长时限作业占住 A100(例:四个 7 天作业,每节点 1 张,
分处 g3083/3084/3085/3087,`0% 利用率 / 0 MiB`)。训练**不新申请 GPU**,
而是钻进这些分配:

```bash
srun --jobid=<占位作业ID> --overlap -N1 -n1 --gpus=1 apptainer exec --nv ... \
  torchrun --nnodes=4 --node_rank=$r --nproc_per_node=1 --master_addr=<rank0节点> ...
```

编排作业自己只要 **2 CPU / 8G / 不要 GPU**,秒上、不排队。

三条配套:
- **SIF 要分发到每个节点的本地盘**(四个 rank 在四台机器上,编排节点拷一份没用)
- **`--overlap` 是必须的**,否则 srun 会一直等占位作业自己的 step 结束
- **共调度安全闸**:启动前逐张查显存,任何一张已用 >1GiB 就 `exit 1` 拒绝启动。
  防的是占位作业哪天真开始干活时两边一起 OOM。这个闸真的救过场:上一轮 OOM
  作业被 scancel 后进程没退干净、还占着 80.5GB,新作业启动时被它拦下。

## 6 显存与速度:三次 OOM 的机理

**节点形状 80GB 显存 + 64GB 主机内存**(a2 在 Tillicum 是 `--mem=400G`),
这一条否掉了两条 offload 路线:

| # | 配置 | 结果 |
|---|---|---|
| 1 | `zero2_offload`(a2 原配方) | **主机 cgroup OOM**,四节点全挂。stage-2 offload 把 ~108GB 的 fp32 Adam 状态放**主机内存**,4 路分片后每 rank 27GB,加上加载权重的峰值 |
| 2 | `zero2` + `pin_memory:false` + `workers 0` | **仍主机 OOM**。解除锁页不够 |
| 3 | **`zero3`**(全部分片在 GPU) | **训练正确**:71.8/80 GB、loss 0.7825、grad_norm 5.885。唯一问题是 **1010 s/step** |

**zero3 是这个节点上唯一装得下的配置。**

### 通信参数:三个点画出曲线

zero3 慢的原因是**每层**都 all-gather 参数、reduce-scatter 梯度,而四张卡在
**四个不同节点**,每次都过网络。swift 内置 zero3 预设的 `overlap_comm=False`
让通信完全阻塞计算流。

| 桶配置 | s/it | 显存 | 结果 |
|---|---|---|---|
| auto,`overlap_comm` 关 | **1010.6** | 71.8 GB | 能跑,慢 |
| `live 6e8 / reduce 2e8` | 更慢 | 59 GB | **收紧桶反而更慢**,白省显存 |
| `live 2e9 / reduce 5e8` | **831.8** | 爆 80 | 快 18%,但 OOM |
| `live 1e9 / reduce 3e8` | 824.7 | **三卡全 80 GB** | 仍 OOM |

**关键判读**:桶从 2e9 收到 1e9,**速度没变、显存没降** —— 这说明吃掉那 20GB 的
**根本不是通信缓冲区**,调桶方向从一开始就是错的。

### 真凶:`enable_channel_loss`

`seq2seq_trainer.py:134` 那个 OR 条件会摘走 labels、强制走 ms-swift 的
**外部 loss 路径**,而该路径**按微批持有一份 logits 大小的张量**。
9B 上:`vocab 248,320 × ~11,800 token × 2 bytes = 5.9 GB`(bf16)。

`TRAINING.md` 记的可行域是 **`batch=1 且 accum≤8`**,而 4 卡凑 global batch 64
需要 **accum 16** —— 正好是那个泄漏被验证过能承受的两倍。a2 在 8 卡上用 accum 8,
从没越过这条线。

**关掉它对实验无害**:同一份文档记着它**不进梯度**,"只往
`metrics[f'loss_{channel}']` 写日志,真正的 loss 仍是那个分母"。代价仅是日志里
没有 `loss_chrome` / `loss_gimp` 分域拆解。

> ⚠️ 2026-08-28 状态:`enable_channel_loss=false` 这个修复**尚未上机验证**
> (用户在它提交后叫停)。恢复训练时这是第一个该验的点。

### 速度参照

| | s/step | 306 步 |
|---|---|---|
| a2 @ 8×H200 | 75.7 | 6.4 h |
| Klone 4×A100 跨节点 zero3 | 824-1010 | **70-85 h** |
| 纯计算理论(无通信,MFU 40%) | ~60 | 5 h |

zero3 那轮**97.6% 的时间花在通信上**。要根治只能拿到**单机 4 卡**(通信走 PCIe
不过网络)。注:多模态 SFT 的 MFU 本来就低,a2 自己也只有 11.7% —— 序列里 97%
以上是无梯度的 prompt token。

## 7 vision token 换算(实测,非推算)

`IMAGE_MAX_TOKEN_NUM` 是**上限**,不是精确值。一个 token 固定吃 32×32 像素
(`patch_size 16 × spatial_merge_size 2`),16:9 下网格必须是整数,所以可选值离散:

| cap | 实际 token | 分辨率 | 相对 2040 |
|---|---|---|---|
| 2048(现行) | **2040** | 1920×1088 | 100% |
| 1024 | 1008 | 1344×768 | 49% |
| **512** | **480** | **960×512** | **23.5%** |
| 256 | 252 | 672×384 | 12.4% |

**拿不到正好 512**:512 落在 480(16×30) 和 510(17×30) 之间,processor 取不超过
上限的最大值 = 480。

**480 不需要重建语料** —— 语料存的是原始 1920×1080 PNG,token 化在训练时发生,
加一个环境变量即可。推理侧的等价开关是 `OSTG_MAX_PIXELS=491520`(=960×512)。

## 8 排错清单(按出现顺序)

| 症状 | 原因 |
|---|---|
| `AssocMaxWallDurationPerJobLimit` | 用了 cse 账号(1 天上限),改 krishna |
| `AssocGrpCpuLimit` | krishna CPU 只剩个位数,编排作业申请 2 个就够 |
| 提交后参数没生效 | **SBATCH 参数在提交时固化**,改文件不影响已入队作业,必须 scancel 重发 |
| `FileNotFoundError` on jsonl | 少了 `--bind $BASE:$BASE` |
| `oom_kill event in StepId` | **主机内存** OOM(cgroup),不是显存 —— 看 offload |
| `torch.OutOfMemoryError` | **显存** OOM —— 看 channel_loss / 桶 |
| `FATAL: job X already has N MiB in use` | 安全闸生效,前一轮进程没退干净,等几分钟 |
| 容器在登录节点起不来 | Klone 的 apptainer 要挂 `/var/run/slurm`,**只能在计算节点跑** |

## 9 文件位置

```
/gscratch/cse/jy050706/          ← 热数据(inode 宽裕)
├── sft-train.def                容器定义
├── build_sft_sif.sbatch         构建(GPU 只为 build 后冒烟)
├── test_env.sbatch              六项自检:分片完整性/model_type/2040token/加载forward/swift模块/CLI
├── requirements-tillicum.txt    165 包,Tillicum freeze
├── zero3_klone.json             DeepSpeed 配置
├── img10tok480-9b.sbatch        训练编排脚本
├── wandb.env                    (600 权限)
├── sif/sft-train.sif            5.8G
└── sft/{models,data}/           权重 80G + 语料

/gscratch/krishna/jy050706/      ← 输出(大文件、少 inode)
├── out/                         checkpoint
└── logs/
```

**密钥不要走命令行**:用 `APPTAINERENV_WANDB_API_KEY` 传进容器。另外**不要照抄
Tillicum 的 `set +x; . wandb.env; set -x`** —— 那些脚本全程开着 `set -x`,
照搬到没开 `-x` 的脚本里会**打开**追踪,把展开后的命令行(含密钥)打进作业日志。
