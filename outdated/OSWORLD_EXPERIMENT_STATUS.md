> **SUPERSEDED(2026-08-15 收编)**:停在 2026-07-31 的官方 361 campaign 状态页。
> 现状一律看 `EXPERIMENTS.md` 顶部现状块;此页职能已由它接管。

# OSWorld 实验现状与模型选择

> 最后更新：2026-07-31（America/Los_Angeles）  
> 远端最后一次成功核验：2026-07-31 21:58 PDT。Tailscale/SSH连接已经恢复；进度数字仍按核验时刻记录，不冒充持续实时值。

## 一句话结论

- 当前用于跑 baseline 和生成 teacher trajectory 的模型是 **`Qwen/Qwen3.6-27B` BF16**，服务别名为 **`qwen36-27b-bf16-local`**。
- 你现在有两套互相独立的实验：
  1. **OSWorld-V2**：针对少量任务做重复运行和温度消融，主要用来观察随机性、积累成功/失败 trajectory。
  2. **OSWorld-Verified（OSWorld1新版）**：计划跑官方 `test_nogdrive` 的 **361个任务**，作为覆盖面更广的 baseline 和 trajectory 来源。
- 后续用于 SFT 的小模型尚未最终确定。候选是 **Qwen3.5-4B 或 Qwen3.5-9B**；4B/9B属于Qwen3.5，不是Qwen3.6。

## 模型选择

| 角色 | 当前选择 | 状态 |
|---|---|---|
| Teacher / baseline agent | `Qwen/Qwen3.6-27B`，BF16 | 已确定，两个OSWorld实验共用 |
| API服务名 | `qwen36-27b-bf16-local` | 已部署为OpenAI-compatible vLLM接口 |
| 服务入口 | WSL侧 `http://127.0.0.1:18001/v1` | 通过隧道指向Tillicum上的模型服务；计算节点会随Slurm接力变化 |
| Student / SFT目标 | `Qwen3.5-4B`或`Qwen3.5-9B` | **尚未最终选择** |
| OpenCUA模型 | 未选作当前teacher/base model | 当前使用Qwen3.6权重和OSWorld内的Qwen agent，而不是OpenCUA权重 |

这里的“base model”如果指**负责生成trajectory的强模型**，答案就是 `Qwen/Qwen3.6-27B`；如果指**最后接受SFT的小模型**，目前还没有定死。

---

## 1. OSWorld-V2

### 用途

- 先在明确任务上跑Qwen3.6 baseline。
- 对同一任务重复采样，量化GUI agent的随机性。
- 保存完整成功/失败trajectory，为后续success filtering和SFT数据处理做准备。
- 重点看过/运行过的任务包括 `010`、`045`、`073`、`074`；系统化温度对照集中在 `045` 和 `073`。

### 版本与环境

| 项目 | 配置 |
|---|---|
| Benchmark | OSWorld-V2 release `v2026.06.24` |
| 远端checkout | `/mnt/d/research/OSWorld-V2-qwen-official-agent-ablation` |
| 环境 | Windows主机上的WSL + Docker/KVM + OSWorld-V2 QCOW2 |
| Observation | screenshot |
| Action space | pyautogui |
| Agent | 以OSWorld/Qwen internal agent为主体，通过自定义runner连接本地OpenAI-compatible vLLM服务 |
| Prompt | 当前对照checkout保持既定Qwen agent prompt；自定义部分主要是runner、服务接入、解析和恢复逻辑 |

### 温度消融固定参数

| 参数 | 值 |
|---|---:|
| model | `qwen36-27b-bf16-local` |
| temperature | `0.6` 对比 `1.0` |
| top_p | `0.95` |
| top_k | 不传 |
| max_tokens | `81920` |
| max_steps | `500` |
| sleep_after_execution | `3`秒 |
| history_n | `100` |
| image_max | `20` |
| fold_size | `10` |
| thinking | enabled |
| num_envs | `1` |

### 已核验的前三轮结果

这些分数来自先前读取的正式 `result.txt` / `summary/results.json`，不是根据日志或`DONE`猜测。

| Task | Temperature | Trial 1 | Trial 2 | Trial 3 | Mean |
|---|---:|---:|---:|---:|---:|
| 045 | 0.6 | 0 | 0 | 0 | 0.0000 |
| 045 | 1.0 | 0 | 0 | 0.92 | 0.3067 |
| 073 | 0.6 | 0.575 | 0 | 0.3875 | 0.3208 |
| 073 | 1.0 | 0.5666 | 0.5875 | 0 | 0.3847 |

额外已知证据：

- `045 / temperature=0.6 / trial4` 的正式分数为 `1.0`。
- 后续trial4/5队列采用独立目录并保留旧结果；最后的045补跑watcher已经确认其等待的两个缺失结果文件有效。
- 由于目前无法连接远端，完整的五轮表（尤其新增trial4/5全部精确分数）需要恢复Tailscale后重新从文件汇总，本文不补猜。
- `010`和`074`的历史运行/trajectory不纳入上表，因为本次没有重新读取它们的正式result文件。

### 结果与trajectory目录

```text
/mnt/d/research/OSWorld-V2-qwen-official-agent-ablation/results/qwen36-27b-bf16-local/
├── temp-ablation-045-sleep3-20260729/
└── temp-ablation-073-sleep3-20260729/
```

单次运行通常包含：

```text
tasks/<task_id>/result.txt
summary/results.json
tasks/<task_id>/traj.jsonl
tasks/<task_id>/recording.mp4
tasks/<task_id>/step_*.png
tasks/<task_id>/runtime.log
```

### 当前能说明什么

- Qwen3.6-27B在同一个任务上波动很大，单次成功或失败不足以代表能力。
- 045与073都出现过0分和较高分/满分trajectory，因此适合做success filtering和行为差异分析。
- 这套数据是“针对性重复试验”，不是完整OSWorld-V2总体成功率。

---

## 2. OSWorld-Verified（OSWorld1新版）

### 用途

- 使用官方任务定义、Ubuntu VM、evaluator和Qwen agent，跑覆盖面更广的baseline。
- 最终目标为官方允许的 `test_nogdrive` **361/361个有效结果**。
- 成功trajectory将作为后续任务筛选、类似任务扩增和SFT的候选数据。

### 官方性边界

| 项目 | 当前设置 |
|---|---|
| OSWorld commit | `091f5ef1d5544bc74953c77875d5feb5bed30108` |
| Task manifest | 官方 `evaluation_examples/test_nogdrive.json`，361 tasks |
| VM | OSWorld1 `Ubuntu.qcow2` |
| Evaluator | 官方evaluator |
| Agent | 官方 `mm_agents.qwen.QwenAgent` |
| Prompt | 不修改 |
| 自定义部分 | 外层campaign控制：健康检查、断点续跑、结果审计、nonproxy/proxy拆分 |

### 任务拆分

| 阶段 | 数量 | 状态 |
|---|---:|---|
| Non-proxy | 312 | 正在串行运行 |
| Proxy | 49 | 尚未运行，需要有效DataImpulse配置 |
| 合计 | 361 | 目标是361/361有效 `result.txt` |

### Agent参数

| 参数 | 值 |
|---|---:|
| model | `qwen36-27b-bf16-local` |
| temperature | `0.6` |
| top_p | `0.95` |
| top_k | 不传 |
| max_tokens | `81920` |
| max_steps | `50` |
| history_n | `100` |
| image_max | `20` |
| fold_size | `10` |
| coord | relative |
| thinking | enabled |
| num_envs | `1` |

### Sleep切换记录

这个campaign中途按用户要求从3秒改为0秒：

| 结果序号 | sleep_after_execution |
|---|---:|
| 前58个有效结果 | 3秒 |
| 第59个及之后 | 0秒 |

因此当前结果目录是**混合sleep协议**。目录名仍包含`sleep3`，是为了保留并跳过前58个结果；不能仅根据目录名判断后续参数。

审计记录：

```text
/mnt/d/research/osworld-verified-control/PROTOCOL_CHANGE_SLEEP0_20260731.md
/mnt/d/research/osworld-verified-control/protocol.sleep3-before-sleep0-58-results.json
/mnt/d/research/osworld-verified-control/protocol.json
```

### 最后一次确认的进度

截至 **2026-07-31 21:58 PDT**：

- 有效结果：`158/312` non-proxy，无效结果为0。
- 正式evaluator累计得分：`78.9294`；当前平均分为 `78.9294/158 = 49.96%`。
- 分布：77个满分、78个0分、3个部分分（`0.0286`、`0.9030`、`0.9977`）。
- 前58个`sleep=3`结果累计38分，平均 `65.52%`。
- 后100个`sleep=0`结果累计约40.9294分，平均 `40.93%`；前后任务领域不同，不能把差异归因于sleep。
- 模型 `/health` 为200，runner命令明确包含 `--sleep_after_execution 0`。
- Runner持续自动进入后续任务。

这个49.96%不能当最终OSWorld-Verified分数，因为：

1. 仅完成158/361，且任务顺序并非随机抽样；
2. Impress、Writer、multi-app、OS、VS Code等大量领域尚未覆盖；
3. 49个proxy任务尚未开始；
4. sleep在第58个结果后发生切换，最终报告需要披露或分段分析。

### 结果目录

WSL：

```text
/mnt/d/research/OSWorld/results/qwen36-27b-bf16-local/osworld-verified-361-temp06-sleep3-maxsteps50-20260731
```

Windows / VS Code：

```text
D:\research\OSWorld\results\qwen36-27b-bf16-local\osworld-verified-361-temp06-sleep3-maxsteps50-20260731
```

Campaign控制与日志：

```text
D:\research\osworld-verified-control\
├── state.txt
├── protocol.json
├── PROTOCOL_CHANGE_SLEEP0_20260731.md
└── logs\
    ├── campaign.log
    └── NONPROXY_312-*.log
```

每个task目录包含：

```text
result.txt
traj.jsonl
recording.mp4
runtime.log
step_*.png
```

---

## 目前已经拥有的数据资产

1. **OSWorld-V2少量任务的多次随机采样trajectory**：适合比较temperature、分析成功与失败行为。
2. **045/073的可量化温度消融**：已经证明单任务方差很大，需要多轮而非挑最好成绩。
3. **OSWorld-Verified的逐步增长trajectory池**：最后确认已有158个正式evaluator结果和对应过程文件。
4. **自动恢复与审计基础设施**：模型健康检查、唯一tmux接力、跳过有效结果、归档不完整结果、最终361任务审计。

## 仍缺少的关键部分

1. 恢复Mac到`osworld-windows`的Tailscale/MagicDNS连接，重新核验实时进度。
2. 跑完312个non-proxy任务。
3. 为49个proxy任务提供有效DataImpulse配置；没有凭据时campaign会停在`WAIT_PROXY_CREDENTIALS_FOR_49_TASKS`，不会伪造结果。
4. 对361个任务做最终有效性审计，再计算正式总分和分领域分数。
5. 从成功trajectory中做质量过滤：不能只看`DONE`，必须以正式`result.txt`和trajectory完整性为准。
6. 最终确定student：Qwen3.5-4B还是Qwen3.5-9B，并确定SFT数据格式、训练预算和同任务/保留任务评测划分。

## 建议的实验命名

- OSWorld-V2：  
  `OSWorld-V2 v2026.06.24 + Qwen3.6-27B BF16 + single-env temperature ablation`
- OSWorld-Verified：  
  `OSWorld-Verified test_nogdrive + Qwen3.6-27B BF16 + official QwenAgent + max_steps=50`
- 当前OSWorld-Verified结果在完整报告中必须追加：  
  `sleep=3 for first 58 valid tasks, sleep=0 afterward`
