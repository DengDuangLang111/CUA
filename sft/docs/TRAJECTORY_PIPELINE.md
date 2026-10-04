# 独立轨迹与视觉信号 pipeline：使用指南

更新：2026-09-15。本文是日常配置、启动、查看和恢复的统一入口；[原计划](../plans/PLAN-20260914-visual-signal-monitoring.md)保留设计定义与历史验收记录。具体实验的进度和资源见[实验账本](../../docs/EXPERIMENTS.md)。

新评测的模型登记、唯一run ID、两机2+6 VM分配、启动/status/resume命令统一见 [EVAL_AUTOMATION.md](EVAL_AUTOMATION.md)。本文负责采集、导出和页面层。

## 1. 默认约定与流程

**每次新开或恢复 eval，默认接入此 pipeline；每道 task 结束后自动生成页面。** 这是配置好的程序流程，不需要为每次实验重新写网页。图、表、截图和评测证据由原始记录生成，没有额外 LLM 做行为总结、失败归因或语义节点分类。

```text
模型服务：真实 forward → attention / token 诊断 → 原始文件与描述信息
                                    ↓
eval worker：请求、回复、截图、动作、实际 evaluator 输入/返回 → 持久化
            └─ attention 下载清单 → 同一后处理进程内的后台下载线程
                                    ↓ task 返回或异常结束
after_task.wrap_task → pending/<task-key>.json（只发布 ready 记录）
                                    ↓
独立 process-pending worker → 等待全部下载完成 → 导出与完整性校验 → task JSON / HTML / Index
                                    ↓
独立 serve 进程 → 浏览器：轨迹图、逐步图片、热力图、原始评分证据
       ↓ 多个已登记的 source viewer
固定 catalog → 正式 Eval / 测试与功能调试 → 同源 task 页面和原始图片
```

三个运行单元要区分：**eval 负责采集，post-processing worker 负责生成，HTTP server 负责提供页面和文件**。只开网页服务器不会处理 pending；只安装结束回调，也不会让普通模型 API 自动返回 attention。采集发生在 **eval/rollout 的推理阶段**，不是 SFT 训练阶段。

模型服务和 eval 可以在不同机器；截图、请求和下载后的 attention 文件留在对应 Windows/WSL。后处理读取这些已保存文件，不重新调用模型，不重新评分。

### 固定入口与分类

固定入口是 `http://127.0.0.1:8793/index.html`，通过 `?collection=eval` / `?collection=test` 切换两个目录，分别保存筛选、折叠与返回位置。

**跨机器合并显示（2026-09-17）**：同一标准命名run、相同已登记模型/checkpoint与推理配置的Windows/workstation分片，在Index中合成一个折叠组，按全部逐题得分重新计算统计。机器路径、端口和并发等本地运行字段不拆组；不同run或10/1与20/10等不同推理条件仍独立显示。任务表保留“来源”，原始run ID、截图URL和证据不改；上一题/下一题可跨两台机器导航，返回列表继续保存展开和滚动状态。只在目录展示层合并，不搬图片、不改分数、不重跑eval。

- **正式 Eval**：按正式评测配置运行的真实任务，包含早上6个source run（500 tasks），以及当前8题OSWorld2运行。题数少或名称含pilot不影响分类。
- **测试 / 功能调试**：用于增加、调整和验证新功能的运行，例如Qwen3.5-0.8B的采集、网格和热力图验证；该小模型只验证管道，不代表9B SFT结果。不是把所有小规模运行都当测试。
- eval profile明确填写 `collection: "eval"` 或 `"test"`；export把它写进每条Index记录。历史记录没有该字段时，使用catalog里该来源的显式默认分类，不通过名字猜。
- **正式目录仅列有最终分数的任务（包括0分）**；未评分/中断任务保留原始文件和详情直链，但不出现在正式列表或前后任务导航中。空分组自动隐藏；新任务最终评分后自动加入。测试区仍可查看未评分调试任务。此规则按分数存在性判断，不把截图或采集校验通过当作评测完成。
- **新模型只换run目录，不换已登记的results_root/output_dir，不新建网站。** 同一来源的Index保留所有run；catalog自动读入新增条目。新增主机/新的独立output根目录，才需要一次性登记source。

catalog最多每10秒读取一次各来源Index，打开的目录页每15秒检查更新并保持界面状态。每道任务仍有单独详情HTML；目录始终是同一个入口。未完成/没有可导出轨迹的任务不会伪造成已完成记录。

catalog只缓存Index元数据；图片、raw JSON和attention文件按需转发，attention保留Range和字节内容。来源离线时显示缓存目录、离线提示及最后同步时间；从未连上且没有缓存时，只列来源状态，不虚构任务列表。分类不同的结果不混算。

## 2. 本次页面能力

| 功能 | 具体行为 |
|---|---|
| 独立轨迹图 | 节点点击在同一页显示证据；不跳转到旧研究汇报网站 |
| 回边与重复步骤 | 同一指令＋已记录应用可合并成节点，保留每次 occurrence；重复访问形成回边或自环 |
| 三种图模式 | 相同指令＋应用、完全相同截图＋应用、每次执行独立；不使用语义模型合并控件 |
| 原始步骤 | 显示整体 instruction、原始 thinking/prediction、实际执行指令、工具返回和时间信息 |
| 截图 | 执行前、执行后、前后对照；执行前图标实际动作位置；点击图片可放大 |
| 最终评分 | 最后一步可看原始 score、判定标准、实际捕获的 expected/actual 输入和结果；没有实际输入时明确缺失 |
| Index | 实验分组默认折叠，支持全部展开/折叠、搜索、模型/数据/应用/得分/参数等组合过滤 |
| 返回与切 task | 返回列表恢复筛选和滚动位置；上一/下一 task 按进入时同一 run 的筛选顺序切换 |
| 单 token 热力图 | 选择 layer/head/输出位置，显示该位置对应的真实图片 key 权重 |
| 整步热力图 | 同一模型决策、同一 layer/head，跨已采集输出 token 等权平均；显示完整或部分覆盖率 |
| 长 thinking | 原始权重独立无损存储；按需加载一个决策的信号和一个输出位置的权重，避免全部塞进 HTML |
| 清晰显示 | 默认共享对数色标、低权重更透明、隐藏网格；可切线性、显示网格、调整不透明度 |

同一模型决策可以产生多个环境动作；不能把这些动作重复计成多次 thinking/token 成本。`image_max` 表示历史策略的配置，不是实际输入图片数或视觉 token 数的证据。

## 3. 文件在哪里、哪些是原始记录

每个 output directory 只能对应一个 `results_root`，且 **output_dir 必须位于 results_root 外部**。不要给不同机器的两个结果根目录共用同一个本地 manifest。

```text
results_root/<run>/
  args.json / version.json / MODEL_BOUNDARY.json  # 已记录的模型、数据、协议与来源
  .../<domain>/<task-id>/
    traj.jsonl                                  # benchmark 原始轨迹，不改写
    result.txt / result.json / phase_results.json# 原始评分；按实际存在展示
    visual_signals.jsonl                        # 按模型决策关联的信号记录
    capture/
      task.json                                # 当时的任务元数据
      manifest.json                            # resume 前的原生轨迹前缀/hash
      trajectory.jsonl                         # 捕获的动作及已返回截图引用
      events.jsonl                             # 决策、评测调用、用户模拟器、错误
      requests/<id>.json                       # 可重建请求、API回复与身份字段
      assets/<sha256>.*                        # 原始图片、data URI、API body、评测文件
      attention/<request-hash>.rank<N>.attn    # 全 token 模式的无损权重文件
      downloads/*.attn.json                    # 后台下载描述、状态、字节数/SHA与耗时
  # results_root/.attention-downloads/*.json 是跨run共享的下载队列索引

output_dir/
  pending/<task-key>.json                       # ready/处理状态/原配置/版本
  index.html / index.json                       # 实验与 task 目录
  manifest.json                                # 原始文件的路径白名单
  task-<task-key>.html                          # 独立轨迹页面
  tasks/<task-key>.json                         # 派生导出数据与图结构
  signals/<task-key>-<frame-index>.json          # 大型信号按决策延迟加载
  validation/<task-key>.json                    # 完整性报告
```

JSON/JSONL 保存结构化信息，**长 attention 不内联成庞大的 JSON 浮点数组**。`.attn` 内每行是独立 zlib 压缩的 little-endian float32；`weights_ref` 保存 offset、length、key_count、codec、chunk SHA-256、原始文件 SHA-256 和本地路径。GPU服务另保留其原始 spool JSONL/`.attn`。

客户端通过模型服务的 `/v1/cua-attention/<name>` 下载文件，复用模型服务的 API-key 认证。下载采用流式写临时文件、大小与全文件 SHA 检查、fsync、原子替换；最多重试3次。后处理逐行读取，网页通过 HTTP Range 取选中行并再次校验、解压。旧的内联 JSON attention 仍兼容。

核心关联字段：`run/source`、task、episode/phase、model decision、`step_num`、request ID/hash、response hash、checkpoint、图片顺序及字节 hash。相同图片重复出现仍是不同的输入 occurrence；来源步无法唯一确定时保留候选，不猜测。

### Image-key storage: same visual values, less transport (2026-09-17)

The deployed serving configuration now sets `capture.weights_scope="image_keys"`.
It still captures **all output positions and all input-image patches**, on the
selected layer/head (current9B: L31/H0). This is not all layers/heads.
Softmax is computed against the full causal context first; image weights are
selected afterward and are never renormalized to sum to one over images.

- `key_count` remains the original full causal length (`query + 1`).
- `stored_key_count` is the concatenated image-patch count. Binary values follow
  `images` order and each image's `key_indices` order; do not zero-fill omitted
  text positions or pretend that the packed array is the full context.
- Per-query `weights_sum`, `non_image_mass`, `full_attention_entropy_nats` and
  `non_image_entropy_nats` retain full/non-image summaries. Non-image includes
  text and special tokens. The individual non-image weights are intentionally
  not saved; their mean-vector entropy cannot be reconstructed from summary
  entropies. Per-query entropies and image-only mean heatmaps remain available.
- Image masses/shares, per-patch values, spatial entropy and average image
  heatmaps match the full-row path. The client/exporter/browser accept both
  full and compact historical rows. The page labels the omitted text weights.
- `weights_scope="full"` remains supported (the backward-compatible default if
  unspecified). `raw_retention=keep/delete-after-export` is a separate switch.
  With delete-after-export, every token's rendered heatmap and exact image
  statistics remain, while raw selected-patch weights are removed only after
  successful validation. Klone spool cleanup is still not automatic.

The same release removes the Python-list roundtrip, reuses log-softmax, and moves
response collect/hash off the API event loop. Six real serving probes, exact
visual-stat comparisons, CPU/CUDA checks, and a completed real task page passed.
The c2751594 task page has22 decisions and47 decoded screenshots; its inspected
step loaded275/275-token mean attention and both history/current-image overlays.
See [six-GPU validation](../../reports/SIX_GPU_IMAGE_CAPTURE_20260917.validation.json)
and [operational commands](EVAL_AUTOMATION.md#reuse-a-held-allocation-and-preserve-active-tasks).

## 4. 配置与启动

### 4.1 eval 主机配置

使用该 benchmark 的实际 Python 环境。以下路径是占位示例，需要替换；`run_dir` 必须是 results_root 下的新结果目录。

```json
{
  "results_root": "/absolute/path/experiments/results",
  "output_dir": "/absolute/path/experiments/pages",
  "source": "workstation-cua",
  "collection": "eval",
  "evaluator_source": "/absolute/path/harness/desktop_env/desktop_env.py",
  "postprocess": "deferred",
  "capture": {
    "enabled": true,
    "backend": "vllm",
    "attention_every": 1,
    "top_logprobs": 5,
    "attention_download": "background",
    "key_file": "/home/your-user/.config/cua-v2/teacher_api_key",
    "download_queue": "/absolute/path/experiments/results/.attention-downloads",
    "download_min_free_gib": 100,
    "checkpoint": "/actual/model/path/on/the/model/server"
  }
}
```

`checkpoint` 可省略并由实际服务记录，但填写时必须与服务报告的路径一致。`attention_every=1` 表示每个模型决策都请求 attention；**每个决策内采哪些输出 token，由下面的服务器配置决定**。`postprocess` 默认就是 deferred，显式写出来便于检查。

新采集运行使用回调传入的实际任务对象与 `capture/task.json`。不要随意填入历史 `task_config_dir` 覆盖它；该选项主要用于指定清楚的历史 JSON 任务配置。

### 4.2 在真正的启动路径启用 recorder

优先使用已验证的 native runner + startup hook，无需改 benchmark 源文件：

```bash
export CUA_ROOT=/absolute/path/CUA
export HARNESS_ROOT=/absolute/path/harness
export CUA_INSPECTION_CONFIG=/absolute/path/inspection.json
export PYTHONPATH="$CUA_ROOT/sft/scripts/eval/capture_runtime:$CUA_ROOT:$HARNESS_ROOT:$HARNESS_ROOT/scripts/python${PYTHONPATH:+:$PYTHONPATH}"

"$HARNESS_ROOT/.venv/bin/python" -c \
  'import lib_run_single; from sft.scripts.eval import after_task; print(after_task.__file__); print(getattr(lib_run_single.run_single_example,"_cua_capture_wrapped",False))'
# 应看到所选工具路径和 True；随后运行已确定协议的正常 benchmark 命令。
```

该路径已在真实 Verified `scripts/python/run_multienv_qwen.py` 和 shared V2 `scripts/python/run_multienv_qwen_internal_agent.py` 验证。模型、任务面板、并发和解码参数继续来自实验配置，不在 pipeline 文档中另定义一套。

环境变量要在启动父进程前设置，并由多进程 worker、tmux/nohup 等继承。复用既有 launcher 时，检查其实际导入的 `after_task.py`，不要认为设置了环境变量就一定用到了新代码。V2 `local_eval/entry.py` 有历史 vendored wrapper，需核对 `CUA_TRAJECTORY_TOOL` 指向的版本；wrapper 可幂等，但不要依赖导入顺序混用两个工具副本。

对于确需持久安装的旧入口，可用 `after_task.py install /path/to/lib_run_single.py [--function NAME]`。安装器保留原文件备份并记录工具的绝对路径；工具搬家后需要重新安装。正常 native 启动已有 startup hook 时，不必再改源文件。

### 4.3 模型服务端启用视觉信号

在模型所在机器单独配置，不能与 eval 的 inspection.json 混用：

```json
{
  "directory": "/absolute/path/server-signal-spool",
  "heads": [0],
  "output_indices": "all",
  "attention_storage": "binary",
  "top_k": 5,
  "validate_kernel": true
}
```

省略 `layers` 会选择该模型实际配置中的最后一个 `full_attention` 层。**全输出 token ≠ 全层/全 head**。例如当前27B pilot为 L63/H0，9B 的对应最后层为31；不能复制一个模型的层号给另一个模型。旧采样配置可以写 `output_indices: [0, 16, 64]`，页面会显示部分覆盖。

```bash
export CUA_VLLM_CAPTURE_CONFIG=/absolute/path/server-capture.json
export PYTHONPATH="$CUA_ROOT/sft/scripts/serve/visual_capture:$CUA_ROOT${PYTHONPATH:+:$PYTHONPATH}"
# 在原 vLLM 0.25.1 启动命令中使用：
# --enforce-eager --attention-backend FLASH_ATTN --kv-cache-dtype auto
# --no-enable-prefix-caching --mm-processor-cache-gb 0 --no-async-scheduling
# 保留实验规定的 model、API key、TP、context、图像预算等参数。
```

这是显式的诊断服务协议。当前验证范围是 Qwen3.5 系图像结构、静态截图、vLLM 0.25.1、eager FlashAttention、非量化 KV；TP1和TP2已有真实检查。未支持 speculative decoding、pipeline/context parallelism、任意 attention backend 或线性注意力层的伪造 dense 热力图。`validate_kernel` 比较重建权重乘V的结果与实际kernel输出，会增加采集开销。

图片的空间粒度取决于真实 processor 输出。已验证的1920×1088输入对应60×34＝2040视觉token；旧320×192对应60个。想增加真实粒度，需要改变记录在案的图像预算并重新 rollout，不能靠网页插值补出原始 attention。

### 4.4 分别启动后处理和页面服务

另开两个终端/已有的进程管理会话，使用同一 profile。运行前检查是否已有对应 worker/listener，避免重复实例。

```bash
PY=/absolute/path/harness/.venv/bin/python
TOOL=/absolute/path/CUA
PROFILE=/absolute/path/inspection.json
PAGES=/absolute/path/experiments/pages

# 独立 worker：每题结束后的 ready 记录会自动进入这里。
"$PY" "$TOOL/sft/scripts/eval/after_task.py" process-pending --config "$PROFILE" --watch

# 在另一终端启动服务器；它本身不处理 pending。
"$PY" "$TOOL/sft/scripts/eval/after_task.py" serve "$PAGES" --port 8796
```

**内存边界（2026-09-16 修复）**：Linux `process-pending` 默认使用
`--memory-limit-gib 4`，限制的是页面处理进程的虚拟地址空间，不是 guest VM 内存。
标准 `run_eval.py` 的控制进程只监督独立子进程，不在自身线程里解析轨迹。
JSONL 先记录每步的字节位置，再逐步读取、计算并写入 `signals/<task-key>-<n>.json`；
页面按需加载这份文件。task JSON 保留 `signals_url`，全量原始数据仍由原始下载链接提供。
导出 JSON 使用流式写入和原子替换，避免整条长轨迹及 JSON 编码的多份内存副本。
超过上限会留下 `failed` / `MemoryError` 记录（或 `export-error.json` 和 `export.log`），
不会因页面失败重跑模型；修复后用 `--retry-failed` 重新处理原始记录。
不要为了修复页面 OOM 增大两台 VM 的 `RAM_SIZE`：两者共享 WSL 主机内存预算。

worker 每5秒检查 ready 文件；它不是定期重跑 eval，也不是整站刷新。服务器只监听127.0.0.1。打开页面用 `http://127.0.0.1:8796/index.html`；跨主机通过已验证的 SSH loopback 转发访问，见[运维说明](../../docs/OPS.md#trajectory-viewer-access)。


### 用固定配置启动后续完整评测

兼容旧的整批runner入口（新任务优先使用上述标准命令）：`launch_captured.py --profile /absolute/path/host.json` 复用已验证的native runner和startup hook，检查固定commit、原始结果目录、任务清单和实际hook；启动独立后处理与本机viewer，已有相同profile的worker会复用。它不登录远端，不循环认证，不改变benchmark评分逻辑；异常仍按原生runner记录，不无限重试任务。

两机2026-09-16完整续跑的profile位于 `~/cua-v2-pilot-20260915/remaining-20260916/host.json`，结果仍在已有results/pages根目录，正式Index自动归集。旧Windows本机8796作为第二个正式来源转发到Mac18796。每次重新尝试用新的result_dir，旧异常轨迹和已完成得分保留。

### 页面与 visual signal 的分阶段发布（2026-09-16）

`process-pending` 先给所有待处理任务发布轻量页面：instruction、动作图、前后截图、
原始 evaluator 信息与实际最终分数。此时验证状态明确为 `processing`，不会表示
attention 已验证。正式 Index 仍只包含有真实最终分数的任务。

完整信号随后在限内存的后处理进程里生成；同一进程的轻量 preview 线程每 5 秒
检查新完成任务，使用独立 `.preview.lock`，因此新任务的图和截图不必等待前一个
大任务的所有热力图。完整处理由 `.postprocess.lock` 保证只有一个协调进程；该进程按 `export_workers` 启动有限数量的导出子进程，每个任务另有独立锁。
处理失败保留可用的动作图、截图与原始数据，并显示失败原因；修复后通过
`--retry-failed` 重试页面处理。预览页面的“刷新处理状态”按钮加载完成后的页面。

每个 attention row 只解压一次，在同一遍计算逐 token 的 mass / share / entropy
并累计整步平均热力图；固定的图片 token 映射每个决策只校验一次。float32 二进制
行仍检查 chunk hash、shape、有限值、非负值和归一化；不降低采集精度或采样 token。
整体图仍然先平均原始权重，再计算 share 和 entropy。

输出分为 `signals/<task-key>-<step>.json`（热力图与统计）和 `...-raw.json`
（完整 API response、input token IDs、request）。浏览器初始只读取前者，展开原始
记录时再读取后者。完整性校验会合并两份记录；原始 rollout 文件不改动。
浏览器最多保留两个已加载的 step signal 对象；重复请求会合并，已释放的步骤
再次打开时重新读取。旧版内嵌 signal 页面继续兼容。

实测：同一旧 Windows 的 OSWorld2 task 016（100 次决策、165 次动作）完整重放，
导出由 1334.44 秒降至 569.03 秒，预览在 2.34 秒发布；峰值 RSS 从
633,784 KiB 降至 484,692 KiB。全部 100 步与旧输出逐字段比较，数值差异为 0；
262 张图片及信号完整性校验通过。单步 94 的三次交替计时中位数由 1.694 秒降至
0.553 秒。完整导出为单次同机对比，不能视为跨任务的固定加速比。
详见 [验证记录](../../reports/TRAJECTORY_EXPORT_OPTIMIZATION_20260916.validation.json)。
两台 Windows 的工具副本已校验部署；workstation 在后处理 worker 空闲时仅替换该
worker 与 viewer，原 6 VM eval runner 的进程身份保持不变。新 eval 与现有 queue
沿用上述默认流程，不需要为每个模型另写导出脚本。

<a id="raw-retention"></a>
### 原始数据保留策略：原有脚本中的参数

后续新计划默认 `raw_retention=delete-after-export`；`keep` 开关保留。旧计划/旧配置缺少该字段时仍按 keep 处理，防止追溯清理。新标准 eval 使用 `run_eval.py plan --raw-retention
keep|delete-after-export`，不再要求 agent 为每轮实验拼一套处理命令。保存到
inspection 配置的对应字段为：

```json
{"raw_retention": "delete-after-export"}
```

已有保存结果可以通过原来的入口显式选择（仅示例，不自动应用到旧实验）：

```bash
"$PY" "$TOOL/sft/scripts/eval/after_task.py" render \
  --config "$PROFILE" --run-dir "$RUN" --task-dir "$TASK" \
  --raw-retention delete-after-export

"$PY" "$TOOL/sft/scripts/eval/after_task.py" process-pending \
  --config "$PROFILE" --raw-retention delete-after-export
```

第二条会作用于该配置下的待处理队列；只处理某一题时使用第一条。
`render-run` 也接受同名参数。已经标记 processed 的任务不会因重启 worker 被
自动重新清理；对旧结果需要显式 `render`，失败处理用已有 `--retry-failed`。

清理模式依次完成：读取并核验原始数据 → 生成每个 output token 的两种色标热力图
及精确图片级统计 → 保存压缩原始文本、图片、网页 → 验证结果和源文件未变化 →
写 durable receipt → 删除 receipt 明确列出的本 task `.attn`、已归档 JSONL，
以及经语义比较确认重复的 `capture/requests/*.json`、结构化 API 回复已完整包含的 `.response.json`，和网页没有引用的 `recording.mp4`。

- **永久保留**：所有已采集 token/层/head 的线性和对数 8-bit 渲染图片，精确 mass、
  share、entropy、token 诊断、整步 mean 的数值、原始截图、动作、得分、评测记录、
  canonical 请求/回复文本。热力图仍可逐 token 查看；原始 patch 精确权重不再存在。
- `heatmaps/<task>-<step>.heat`：带 byte-range 索引的 PNG 包，避免数十万小文件。
  每张 PNG 包含线性/对数强度；viewer 在原 patch 网格显示，图片/透明度/网格仍可切换。
- `archives/<task>.jsonl.gz`：由独立 gzip member 组成的 canonical 原始文本；浏览器
  按 byte range 读取单次请求，也可以下载整体归档。散落的请求副本只在与归档一致时删除。
- `signals/*.json.gz`：压缩的显示统计，仍通过原来的 `.json` URL 加载；viewer 和
  catalog 传递 gzip encoding，不在整页内展开大型文本。
- `retention/<task>.json`：验证过的 source/artifact hashes、来源快照、删除字节数与状态。
  崩溃后可继续已验证的清理；若改为 keep，不继续尚未完成的删除。raw 已删不能由 keep 恢复。
- 校验失败、没有最终分数、图片/源文件变化、attention 行没有完整转换时，保留原数据。
  保留完整 output token 覆盖与 exact 图片级统计，不将 8-bit 渲染强度冒充原始 patch 数值。

**边界**：此参数只管理本 eval task 的本地采集文件，不清理 teacher 服务端的独立
capture spool，也不删除 benchmark/VM/权重。运行期间仍需原始数据的临时磁盘空间；
该版本在整题成功导出后清理，不在 rollout 中途丢弃原始行。旧计划的显式策略保持不变。新计划默认只保留最终网页所需的结果。

验证记录：[TRAJECTORY_RETENTION_20260916.validation.json](../../reports/TRAJECTORY_RETENTION_20260916.validation.json)。
65 项本地检查中 60 通过、5 因平台/依赖跳过；Linux 侧25项针对性检查通过。
真实三步任务的隔离副本由54.42MB raw降至15.53MB（保留文件+网页），删除46.01MB，
原研究任务hash未改变。浏览器实测raw删除后逐token图片和精确统计仍可加载；
故障、未完成任务、来源变化、归档损坏、外部路径与中断恢复均有测试。
此小样本不代表完整108题的最终占用。既有运行配置仍为keep；新计划默认清理，但两个保留策略开关均保留。

### Attention 后台下载与正在运行的任务衔接（2026-09-17）

标准 `run_eval.py` 新运行默认生成 `capture.attention_download: "background"`。
原有采集配置不填该字段时保持 `sync`，避免悄悄改变旧脚本的行为。采集哪些层、head、
输出 token，以及 `keep` / `delete-after-export` 开关都保持独立。

1. **Klone** 完成当前请求的真实推理/采集，保存完整 `.attn`，回复动作与文件描述（字节数、SHA）。服务端保存/压缩仍在回复前，这次未改它。
2. **Eval** 持久化原始请求/回复和下载清单，随即把同一模型回复交回原生 runner 执行动作；不等待 `.attn` 跨机器传完。请求记录中写 `attention_download_mode`。不再用未使用的列表把全部历史请求常驻 RAM。
3. **已有 `process-pending` 进程** 内使用标准库下载线程，无需另开服务。`download_workers` 控制并发（缺省 1，当前两机为 2）；每个下载槽位及文件均持独立锁，同一文件不会重复传输。使用独立 HTTP 客户端，避免把下载请求混入模型 SDK 的下一步采集 hooks。API key 只从私有文件读取，队列不存密钥正文。
4. 下载每次使用 1 MiB 缓冲；中断保留 `.tmp`，重试发送 `Range`。服务端不支持 Range 时从头下载。大小、全文件 SHA 校验通过并 `fsync` 后才原子替换成最终 `.attn`；最多连续尝试 3 次，失败后保留记录等待显式重试。磁盘空间须足够容纳剩余文件及配置的预留空间。
5. **任务完成即先发布得分、动作图和截图**。attention 未齐时，后处理状态为 `waiting_for_attention`，不将其误报成数据缺失或成功处理；下载完成后才生成完整 visual signals、逐 token/整体热力图及精确图片级统计。
6. 完整性验证成功后才执行已选的保留策略。本地清理本身不删除 Klone spool；显式启用下文 `producer_cleanup` 后，另一线程按完成回执清理对应 `.attn`。网页 preview 有分数不等于热力图已处理完成；详情页已打开时，处理结束后需要刷新。

**配置字段**（在 `inspection.json` 的 `capture` 下）：

| 字段 | 作用 |
|---|---|
| `attention_download` | `background` 后台下载；`sync` 回复后同步下载 |
| `key_file` | WSL 本机现有私有 API-key 文件路径；不填密钥正文 |
| `download_queue` | `results_root/.attention-downloads`；同一 host/output 根目录的各 run 共用 |
| `download_min_free_gib` | 预留磁盘 GiB；标准脚本沿用 host 的 `min_free_gib` |

多个 teacher 使用不同密钥时，新 controller 给每个 task 设置 `CUA_CAPTURE_KEY_FILE`，
覆盖该 task 的默认 key-file 路径。每份下载记录保留**真实请求的服务 URL**，不会把三张卡的
blob 都发到第一个 teacher 下载。同步/后台配置改变的是传输方式，不改变评测协议和 teacher 分配。

**案例 A：新 Verified100**。照 [EVAL_AUTOMATION.md](EVAL_AUTOMATION.md) 的 `plan → doctor → run`
命令启动，脚本自动生成上述配置并启动已有后处理 worker；无需每轮另写下载脚本。
同样适用于经共享 recorder 接入的 OSWorld2。无采集能力的普通 API 无法凭此得到 attention。

**案例 B：连接中断后的恢复**。以下在对应 WSL 上执行；`RUN` 替换成实际 run 目录。
不要用旧日期示例的 run ID 去操作另一轮实验。

```bash
TOOL="$HOME/cua-v2-pilot-20260915/tool"
PY="$HOME/research/OSWorld-V2-shared/.venv/bin/python"
RUN="$HOME/cua-v2-pilot-20260915/results/<actual-run-id>"
PROFILE="$RUN/inspection.json"

# 查看下载收据：pending / downloading / complete / failed。
find "$RUN" -path '*/capture/downloads/*.json' -print

# 普通 pending 和被中断的 downloading 会继续；不重跑模型或改写分数。
"$PY" "$TOOL/sft/scripts/eval/after_task.py" process-pending --config "$PROFILE"

# 修复网络/磁盘/认证后，重试 failed 下载及失败的页面导出。
"$PY" "$TOOL/sft/scripts/eval/after_task.py" process-pending --config "$PROFILE" --retry-failed
```

该 worker 已由 controller 管理时不必手动重复启动；重复运行由共享锁限制下载和渲染并发。
`process-pending` 一次运行会等当前后台下载排空并再检查一遍待导出任务；`--watch` 才持续等待新任务。
校验失败时不清理来源，诊断信息在每份下载收据与 `pages/pending/*.json`、`export.log` 中。

**案例 C：现有 eval 无缝切换或回退**。先隔离测试，再备份并按 SHA 核对部署四个工具文件：
`attention_download.py`、`capture.py`、`after_task.py`、`run_eval.py`；原子更新该 run 的
`inspection.json`。controller/VM/model server 不重启，**当前 native task 保留启动时已载入的
配置和代码，下一个 task 才切换**。不要声称正在运行的某一步已经热替换。
回退新任务只需把 `capture.attention_download` 改为 `sync`，保留 `download_queue` 和新版下载/导出模块，
让已经排队的后台文件继续传完；不要删队列或回滚掉仍被 pending 使用的模块。
冻结 plan、任务清单、采样设置、得分都不变，部署时间、前后代码 SHA 和 profile 备份另存部署收据。

**性能边界**：移除的是动作执行前的跨机器文件下载等待，不消除 GPU attention 重建、服务端
压缩/写盘、模型长 thinking，以及 VM 中的任务操作耗时。下载总字节数未减少；网络跟不上时
会积压，热力图晚于分数发布，最终收尾仍需等待。不能由这次改动推算固定倍数加速。

本次验证：[ATTENTION_ASYNC_DOWNLOAD_20260917.validation.json](../../reports/ATTENTION_ASYNC_DOWNLOAD_20260917.validation.json)。
Mac、Workstation WSL、旧 Windows WSL 各29项针对性测试通过；包含动作回复不等下载、
待传完才导出/清理、断点续传、SHA失败与重试、并发锁、进程退出前排空及已有采集/页面测试。
另外用两台机器上真实模型生成的767,356 / 2,201,060字节文件做隔离续传，SHA一致、研究原件未改动。
这是传输和管道验证，不冒充重新运行两种benchmark或已经量到完整eval加速。
真实运行随后也已验证：Workstation任务`68a25bd4-59c7-4f4d-975e-da0c8509c848`第1步，
06:05:35 PT开始执行WAIT，06:05:41动作记录已落盘；33,786,246字节attention于06:05:53
完成下载及SHA校验，传输耗时19.41秒。动作先于下载完成，新任务没有等待该文件；
这只证明传输与执行已重叠，不代表整轮eval的固定加速比例。

### 后续性能检查：不要把所有等待都算成下载（2026-09-17）

第一道异步任务前7步从decision 1开始到decision 8开始共276.27秒，其中API请求236.34秒、
动作/截图/客户端处理39.93秒；后台文件下载合计64.42秒。若同步模式仍需串行等待同样的传输，
估算为340.69秒，即耗时少18.9%、吞吐约1.23倍。**这是时间账估算，不是同题同轨迹的开关对照**，
也不包含最终热力图排空时间，不能直接外推全部100题。

| 检查项 | 实际证据 | 处理原则 |
|---|---|---|
| 模型排队 | 三路服务采样时waiting=0；自启动累计平均queue约0.04–0.07秒 | 当前不把加GPU/复杂负载均衡作为第一优先级 |
| 生成与采集 | 三路累计decode均值约27–36秒；新任务7步约85.5%墙钟时间在API请求 | API计时包含采集等开销，不能叫作纯模型推理时间 |
| 上下文与thinking | 部分后段prompt约5.2万–6.4万token；1635输出中1543为thinking | 本轮保留协议；截短thinking/取消preserve须作为另一实验 |
| 服务端同步处理 | 当时实际collector SHA与优化前源码一致；每token `.tolist()`→float32数组→zlib→open/write/close；response merge同步读文件、算SHA | 这三项已有本地候选代码及隔离测试（见下文）；尚未部署线上，整轮增益未测 |
| VM动作等待 | 当前`--sleep_after_execution 3`，多动作步骤逐个付等待成本 | 不直接减sleep以免影响UI稳定与评测可比性 |
| 内存与后处理 | 两机可用23.6/5.9GiB，memory PSI=0、oom_kill=0；当前run无pending/validation_failed积压 | 不因vmmem看起来大就重启WSL；host目录内历史失败不能混算本轮 |

后台下载不会减少总字节。若后续所有VM的产出超过网络速度，仍会积压并推迟热力图；
以下载收据的queued/started/completed时间和字节数判断，避免只看score数量。
完整测量与源码检查见[验证报告](../../reports/ATTENTION_ASYNC_DOWNLOAD_20260917.validation.json)的`remaining_bottlenecks_audit`。

### 服务端三项最小改动的隔离测试（2026-09-17）

**历史测试记录；随后已与image-key存储一起部署到六路服务。**
用户随后要求本轮立即启用；六路部署已完成，后续20/fold10复用这些服务。
具体接续步骤统一见[EVAL_AUTOMATION](EVAL_AUTOMATION.md#required-serving-upgrade-before-the-queued-2010-run-authorized-2026-09-17)，通过保存回复后的短暂停顿保留当前任务进程/VM进行切换。
隔离测试时线上collector为`a17f24a6…`、候选为`783e18e…`；随后加入image-key存储的已部署版本为`432324bf…`。最新状态以六卡验证报告为准。
测试目录独立于生产tool/spool：`/gscratch/cse/jy050706/cua-v2-pilot-20260915/capture-opt-test-20260917`。

只改两个实现文件：`attention_store.py`接受float32 buffer，保留原list与JSON兼容路径；
`vllm_capture.py`二进制模式直接传CPU数组、复用已有log-softmax、用`asyncio.to_thread`执行collect。
采集层/head/output token、浮点精度、压缩级别、SHA校验和保留策略不变。

Klone相同vLLM镜像、PyTorch 2.11.0+cu130、L40S小张量测试；旧/新交替5轮取中位数，
写入隔离GPFS目录。测试不加载模型，不修改原研究文件；与正在运行的服务共享节点，存在计时噪声。

| 局部操作 | 旧版 | 候选 | 解释 |
|---|---:|---:|---|
| 每行20,400个权重：GPU→CPU转换、压缩、写盘 | 2.899ms | 2.322ms | 该操作耗时约少20% |
| 每行64,000个权重：同上 | 9.627ms | 7.844ms | 该操作耗时约少19% |
| 每token entropy＋top-k诊断 | 0.243ms | 0.167ms | 该操作耗时约少31%；绝对节省仅0.076ms |
| 整理约59.5MB文件期间，事件循环最长停顿的中位数 | 44.81ms | 2.72ms | 改善其他请求响应；collect本身42.69→43.45ms，未变快 |

不能把这些局部百分比当成整轮eval提升。按单层/单head和本次测量，前两类去重复操作合计
约省0.65–1.86ms/输出token，即每1000 token约0.65–1.86秒；实际整轮收益须另测。

验证：本地32项中27通过、5因无Torch跳过；Klone11项全通过，覆盖本地跳过的数值检查。
CPU/CUDA、float32/bfloat16/float16来源均比较；二进制字节和SHA、entropy/top-k完全一致。
真实任务attention的输出位置0/1011/2022三行重新编码，与原始压缩块SHA逐一一致。
并发测试验证慢collect不挡另一个请求、不串request，读取失败仍保留显式capture_errors。
测试目录最初带了旧viewer，已对齐当前接口后重跑通过，生产viewer未替换。

复用方式：在安装Torch的相同环境内，从候选代码根目录运行。baseline目录放修改前的
`attention_store.py`和`vllm_capture.py`，工作目录用独立测试目录；不要指向生产spool。

```bash
python3 -m unittest sft.tests.test_attention_store sft.tests.test_vllm_capture -v
python3 -m sft.tests.benchmark_capture_overhead \
  --baseline-dir /absolute/path/baseline \
  --work-dir /absolute/path/isolated-test-scratch \
  --device cuda --output /absolute/path/benchmark.json
# 可附加 --capture-jsonl /absolute/path/existing-request.rank0.jsonl
# 只读回放该真实记录首/中/末三行，不重新调用模型。
```

完整原始轮次、hash和环境：[CAPTURE_SERVER_OPTIMIZATION_20260917.validation.json](../../reports/CAPTURE_SERVER_OPTIMIZATION_20260917.validation.json)。
本次已完成六路独立模型请求验证与切换。未来修改仍须验证，并保留请求边界和维护回执；单纯覆盖文件不是热更新。

## 5. 已有结果、失败恢复与页面更新

以下命令都复用同一导出器，不调用模型、不修改原始轨迹或得分。先设置上一节的 PY/TOOL/PROFILE，额外设置 RUN 为实际运行目录、TASK 为其中的某个 task 目录。

```bash
# 处理当前 pending 一次。
"$PY" "$TOOL/sft/scripts/eval/after_task.py" process-pending --config "$PROFILE"

# 修复文件/工具问题后，重试后处理失败或校验失败的记录。
"$PY" "$TOOL/sft/scripts/eval/after_task.py" process-pending --config "$PROFILE" --retry-failed

# 已生成过的单题需要刷新模板，或 ready 记录未生成时：
"$PY" "$TOOL/sft/scripts/eval/after_task.py" render \
  --config "$PROFILE" --run-dir "$RUN" --task-dir "$TASK"

# 同一完整面板批量导入/重建；数量按真实面板填写。
"$PY" "$TOOL/sft/scripts/eval/after_task.py" render-run \
  --config "$PROFILE" --run-dir "$RUN" --panel "$PANEL" --expected-tasks "$TASK_COUNT"
```

`PANEL` 格式是 `{"chrome": ["task-id", "..."]}`；V2示例是 `{"tasks": ["007", "008"]}`。面板重复、缺轨迹或数量不符会报错。历史 Verified 没有保存 task metadata 时，可以给 `render-run` 额外传 `--task-config-dir "$EXAMPLES"`，其目录按 domain/task-id.json 组织。V2 Python task class 不能冒充这样的 JSON 目录。

直接访问source viewer时，旧HTML要通过 `render` / `render-run` 重建才能更新模板。**统一catalog会用当前共享模板展示已有HTML里的已导出数据**，因此界面更新不必重新解析所有原始轨迹；修改数据/图结构仍需render。已经标为processed的pending，普通process-pending不会重复处理。

只更新 Index 的分组/筛选显示，可用 `refresh-index "$PAGES"`。旧 `refresh-pages` / `refresh` 依赖当前磁盘上的 JSON task 配置，会重新构造历史 evaluator 说明；**不把它们作为新捕获运行或 V2 的通用刷新命令**，以免用当前静态说明替代已记录的实际评测证据。

## 6. 网页和指标怎么读

- Index 分组是具体 run，规范模型名相同也不合并不同运行。模型名由[命名注册表](../armname.py)解析，参数/数据来源保留 args、version、MODEL_BOUNDARY；缺失信息显示未记录。
- 图节点是可复核的指令/应用或截图字节匹配，不等于语义上的同一个控件。应用名没采到就显示未知。原始 chronological occurrence 永远保留。
- “前后截图”描述环境实际返回的状态；heatmap只能叠在该决策真正输入模型的图片上。当前点击标记不移植到历史截图。
- “整步平均”先平均原始图片-key权重，再计算 mass、share 和熵；不平均RGB颜色，不把每个token先归一化成图片内100%，不混合不同layer/head/决策。缺失输出位置不补零。
- `image_mass`：全部图片获得的权重，占所有可注意key的比例。`frame_share`：某图片mass除以全部图片mass。比如17.53%和51.18%使用两个不同分母。
- 同时展示每图实际视觉token数、每视觉token平均权重。图片token数不同时，仅比较总share可能受到图片大小影响。
- 空间熵在单张图内部计算；图片选择熵在图片之间计算；完整词表熵来自生成logits。三者不是同一个指标，top-k logprobs也不能代替完整词表熵。
- 对数色标使用 `log1p(w/m)/log1p(max/m)`，m为当前所有输入图片非零权重的中位数；所有图片共享范围，切换单张也不重标定。可切回线性 `w/max`。色标随决策/输出选择重新计算，跨步强弱比较应看原始数值。
- 颜色和透明度只改善显示，不修改数据；网格开关不改变真实patch数。放大图片可查看patch，hover显示原权重和模型输入坐标。
- 单head热力图不能直接证明模型看懂了控件或失败原因。整段回复平均会混合thinking、动作格式和正文；要检查某次点击，可切到相应决策与坐标输出位置。

URL保留 `episode`、`occurrence`、`group`、`panel`、`attention=mean|token`、`output`（从0计）、`layer`、`head`、`scale=log|linear`、`grid=0|1`、`opacity`。旧链接仅有output时仍按单token处理。Index的筛选/折叠/返回位置由浏览器sessionStorage保存，不是服务端账户数据。

## 7. 完整性与排障

`validation/<task-key>.json` 的状态是 `passed`、`incomplete` 或 `failed`，与任务score分开。全token配置会核对每个声明的layer/head是否覆盖全部生成位置，熵记录是否齐全，以及query/output/图片token映射、实际截图、原始动作顺序和request/checkpoint身份。

| 现象 | 先检查什么 | 正确处理 |
|---|---|---|
| 新任务没有页面 | 原始traj、pending是否存在；worker是否使用同一profile | 无pending时用render；有pending时检查独立worker |
| processed数量增加但仍报错 | `invalid`、pending.status、validation.errors | `processed`只表示完成导出尝试；校验失败不能报采集完整 |
| 命令返回busy | 同一output_dir已有后处理锁持有者 | 检查已有worker；不要启动一群重复watch进程 |
| 有截图但没有attention | API是否真的返回cua_signals；服务端hook/config；capture_errors | 修采集配置；历史截图不能补出原始运行的attention |
| 热力图“全蓝”或像噪声 | 色标范围、token覆盖、所选head/输出、实际processor网格 | 使用显示对照；不能据此篡改权重或推断模型理解 |
| 单token加载失败 | signals JSON的HTTP状态、Range是否206、blob/chunk SHA | 恢复文件/服务器版本后重建；不能静默显示别的行 |
| 截图缺失/动作数不一致 | native runtime错误、env.step是否返回None、capture events | 保留错误；任务012曾因此正确标为校验失败，不伪造截图或score |
| localhost打不开 | 远端serve、远端HTTP、Mac listener、SSH转发分别检查 | 只恢复所属viewer/tunnel；不为网页问题重跑eval或重启WSL |
| task退回Index顶部 | 是否同浏览器tab/session、是否由Index进入、存储是否被清理 | 同源返回列表可恢复位置；直链则按整个run导航 |

startup hook 导入失败会退出（78）；运行中 recorder/backend 的异常通常记录后保留原始评测行为；后处理再明确标出缺失。原子写和校验能发现多种问题，不代表网络/磁盘/环境失败时一定能获得完整记录。

后处理重新生成只解决派生产物问题，不能恢复当时没有采到的原始信息。新的 replay/区域干预属于新诊断，应有独立来源标记，不混进原始分数。

## 8. 实际部署与代码入口

以下是2026-09-15核对过的目录；端口可用性取决于对应server与SSH转发。**用户入口固定为Mac8793，其他端口作为上游来源保留。**

| 本地入口 | 数据/用途 | 远端位置 |
|---|---|---|
| 8793 | 统一目录，正式/测试两个入口；不存原始图片 | Mac `computeragent/cua-trajectory-catalog/catalog.json` |
| 18793 → 旧Windows8793 | 正式：历史500 task、6个source run；原运行未采attention | 旧Windows `/home/daniel_yan/cua-trajectory-output`；工具 `cua-trajectory-tool-20260915` |
| 8794 → workstation8794 | 测试：0.8B Verified/V2功能诊断，含60-token和2040-token网格 | workstation `/home/yanji/cua-signal-diagnostic-20260915/{tool,results,pages}` |
| 8796 → workstation8796 | 正式：27B OSWorld2，8题计划；已完成任务逐题出现 | workstation `/home/yanji/cua-v2-pilot-20260915/{tool,results,pages}` |

当前运行仍用 `/home/yanji/cua-v2-pilot-20260915/inspection.json`；不为接入catalog重启eval。后续正式运行用 `/home/yanji/cua-trajectory-eval.json`，功能调试用 `/home/yanji/cua-trajectory-test.json`。这两份host profile分别沿用上表已有results/pages根目录；模型服务、benchmark evaluator路径及capture配置仍需按实际run核对。新profile未固定teacher checkpoint，由真实服务报告身份，避免复制旧模型路径。

当前Python环境是 `/home/yanji/research/OSWorld-V2-shared/.venv/bin/python`。服务器capture配置及spool在Klone `/gscratch/cse/jy050706/cua-v2-pilot-20260915/`。本次仅更新工具文件和目录配置，未重启eval/VM/model server。文件hash记录在两个工具部署根目录的 `catalog-support-hashes.json`。

### 启动统一catalog

```bash
# Mac；没有8793监听时启动，不重复开启。
python3 /Users/knight/uw/computeragent/CUA/sft/scripts/eval/after_task.py catalog \
  --config /Users/knight/uw/computeragent/cua-trajectory-catalog/catalog.json --port 8793
```

catalog配置采用一个source对应一个现有viewer，而不是一个source对应一个模型：

```json
{
  "sources": [
    {"id": "workstation-eval", "label": "Workstation 正式评测",
     "url": "http://127.0.0.1:8796", "collection": "eval"},
    {"id": "workstation-test", "label": "Workstation 功能调试",
     "url": "http://127.0.0.1:8794", "collection": "test"}
  ]
}
```

实际配置另含旧Windows来源。2026-09-16用户要求避免递归或循环登录。当前catalog配置不含`ssh`字段，**不启用自动SSH重连**；复用已有已认证会话，一次性建立loopback转发。网页转发采用独立`ssh -fNT -o ControlMaster=no -o ControlPath=none`连接，避免管理ControlMaster结束时同时丢失网页转发；只建立一次，不循环登录。失效时先查会话/网络，认证问题停止并交由用户完成。已有连接恢复且来源HTTP服务正常后，catalog仍自动刷新目录。

旧Windows在09-15接入时SSH超时；09-16已恢复连接。六组历史结果仍在原目录，可用性以catalog的来源状态为准。旧的根路径task链接通过 `legacy_source` 转到已登记历史来源；新链接使用 `/sources/<id>/task-<hash>.html`，保留同源返回、图片与信号请求。

| 源码 | 职责 |
|---|---|
| [capture.py](../analysis/capture.py) | eval请求/回复、截图、执行和评分证据采集；发布下载清单 |
| [attention_download.py](../analysis/attention_download.py) | 持久下载队列、Range续传、SHA校验、按host限并发 |
| [vllm_capture.py](../analysis/vllm_capture.py) | serving侧真实位置、attention与logit诊断 |
| [attention_store.py](../analysis/attention_store.py) | 无损attention行写入、分段校验和读取 |
| [visual_signals.py](../analysis/visual_signals.py) | 身份对齐、指标、导出与完整性检查 |
| [after_task.py](../scripts/eval/after_task.py) | 回调、ready队列、独立worker、render与serve CLI |
| [trajectory_viewer.py](../analysis/trajectory_viewer.py) | 图结构、生成页面、同源白名单HTTP和Range |
| [trajectory_catalog.py](../analysis/trajectory_catalog.py) | 多来源固定目录、正式/测试分类、离线Index缓存、同源原始文件转发 |
| [task模板](../analysis/trajectory_viewer.html) / [Index模板](../analysis/trajectory_index.html) | 显示、导航、过滤、原始证据和热力图 |

日后改采集代码时再运行相关 capture/attention/viewer 检查；仅改本文无需占用GPU。合成fixture只能验证代码/UI，不能当真实模型结果。验收数量与历史实验细节保留在[原计划](../plans/PLAN-20260914-visual-signal-monitoring.md)。

### Trajectory-page language (2026-09-17)

The standalone task viewer has an `English / 中文` button. `?lang=en` or `?lang=zh` selects the UI language; the choice is remembered in browser local storage (`cua-trajectory-language`). The query parameter takes precedence. Language switching preserves the task and hash parameters for the episode, action, graph grouping, and attention view. UI labels, graph explanations, signal controls, and evaluator headings are translated; original instructions, model responses, actions, JSON, and evaluator evidence remain verbatim.

Example: `http://127.0.0.1:8793/sources/workstation-eval/task-243d2e95c1eaf6c6d527d40fe70ae683.html?lang=en#episode=0&occurrence=44&group=action&attention=mean&panel=signals`. Open it in a browser on the Mac running the catalog. The catalog reads the shared template on each task-page request, so existing catalog pages get the update on refresh without rerunning evaluation or regenerating heatmaps. The same template is used by new pipeline exports; previously exported standalone HTML outside the catalog requires `refresh-pages` to adopt new UI.

### 2026-09-17：目录只显示旧缓存时的修复

现象：远端20/fold10已完成51题，但Mac8793只有旧10/fold1。先读取 `/index.json` 的 `sources`，这次四个来源均为 `online=false, cached=true, Connection refused`；两台WSL的实际8796服务均正常，新结果已写入index。问题位于Mac网页SSH转发，不是评测任务或结果文件丢失。

已在 `cua-trajectory-catalog/catalog.json` 为每个source补齐现有catalog支持的 `ssh` 配置，启用有节制的自动重连（BatchMode、ConnectTimeout、ServerAlive、仅127.0.0.1转发）。Workstation使用 `yanji@100.64.148.22:2222`，正式远端8796、测试8794；旧Windows使用 `osworld-windows:2222`，历史8793、正式8796。注意Windows别名真实SSH端口也是2222；catalog未显式配置时默认22，会导致连接失败。保留原hosts校验，不进入密码/Duo循环。

修复后核对：四来源online，新20/fold10两机结果在同一组显示。必要时使用已有 `after_task.py refresh-index <pages>` 从已导出的任务元数据重建目录（持有 `.index.lock`）；不重跑模型、不重绘截图。尤其手动导出中断任务后，简略run args可能暂时让旧两机结果分组分开，refresh-index可从完整任务导出恢复目录元数据。


<a id="bounded-postprocessing"></a>
### 有限并发、精确热力图与断点恢复（2026-09-17）

后处理仍使用一个 `process-pending` 入口，没有额外队列服务。顺序如下：

```text
rollout 保存请求/回复/截图 + 下载清单 → 模型动作继续执行
  ├─ 下载线程：Range 续传 → 大小/SHA 验证 → .attn 原子发布
  └─ task 评分完成：先发布动作图/截图/分数
       → 导出进程逐决策生成 signal、全部已采集 token 的热力图、原始文本归档
       → 整题校验 + retention receipt → 按策略清理 WSL 原始副本
       → producer cleanup 线程复核网页产物与下载身份 → Klone 验证 → 清理明确列出的 .attn
```

默认值兼容原配置；当前 Workstation 为 `export_workers=2`，Windows 为 `1`，
两边 `download_workers=2`，`resume_render=true`。范围均为 1–4，不能按 VM 数盲目放大。
4 GiB 地址空间限制适用于每个导出进程，**不是所有子进程合计 4 GiB**；线程数限制为 1，
避免 NumPy/BLAS 再放大并发。下载领取任务时共同计算磁盘剩余量和其他在途文件的剩余字节。

可在 host 的 `postprocess` 配置里填写；已有运行可在 `pages/worker-options.json` 设置：

```json
{"export_workers": 2, "download_workers": 2, "resume_render": true}
```

仅支持这三个字段和 `producer_cleanup`。加载顺序：run `inspection.json` → host 页面目录
`worker-options.json` → 显式 CLI 参数。导出数量/恢复设置在下一轮队列处理读取；下载线程数
需在当前任务完成后重启**后处理 worker**。该覆盖文件影响同一页面根目录的 worker，不改冻结
plan、VM 配额、采样参数或 attention 采集范围。新 worker 收到 SIGTERM/SIGINT 后停止领取新
任务，完成在途导出、保存可续传下载后退出；旧版本没有这个信号行为，须先确认当前任务已发布。

```bash
# 使用当前 benchmark 对应的 Python 环境；Verified 的示例：
PY=/mnt/d/research/OSWorld/.venv/bin/python
TOOL="$HOME/cua-v2-pilot-20260915/tool"
PROFILE="$HOME/cua-v2-pilot-20260915/results/<actual-run-id>/inspection.json"
"$PY" "$TOOL/sft/scripts/eval/after_task.py" process-pending \
  --config "$PROFILE" --export-workers 2 --download-workers 2 --resume-render
# 调试时强制重新计算待处理任务：--no-resume-render
# 失败任务显式重试：--retry-failed。不要启动另一套 eval 来修网页。
```

NumPy 只用于 heatmap 的 float64 量化；临近舍入边界回到原 Python 算式。仍使用 PNG level 6、
读回验证、fsync 和原子替换，图片级精确统计的求和方式不变。JSON 经 TextIOWrapper 缓冲后
流式 gzip 写出，解压后的内容不变。`pages/resume/` 保存每个决策的输入指纹、渲染版本、signal/
heatpack 哈希及文本归档索引；只有身份和实际产物哈希匹配才复用。半写 `.tmp`、变动输入或损坏
缓存都不能跳过计算，整题最终校验仍必做。`keep` 模式不执行该渲染归档清理路径。

实测与部署状态见[优化验证](../../reports/pipeline-optimization-20260917/deployment-validation.json)。
热力图写入子阶段加速不等于模型推理或整轮 eval 同比例加速。

<a id="producer-cleanup"></a>
### Klone 原始 attention 清理：明确回执，不扫描删除

脚本：[`cleanup_capture.py`](../scripts/eval/cleanup_capture.py)。默认未启用。
只有 `raw_retention=delete-after-export` 且 `producer_cleanup.enabled=true` 才运行；`keep`
始终保留开关。将 checkpoint 专属配置放在该 run 的 `inspection.json` 或对应模型 registry 的
host `postprocess` 中；换模型必须核对 checkpoint、spool 和 SSH 路由，不复用错误目录。

```json
{
  "producer_cleanup": {
    "enabled": true,
    "checkpoint": "/absolute/serving/model",
    "command": ["ssh", "-T", "-S", "/absolute/existing-master.sock",
      "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ConnectionAttempts=1",
      "user@producer", "python3 /absolute/cleanup_capture.py --spool /absolute/capture-spool --apply"],
    "timeout_seconds": 300
  }
}
```

这是参数列表，不包含密码/API key。先安装脚本并以去掉 `--apply` 的命令跑 dry-run。
客户端只接受已完成、已校验的本地 retention receipt，重查留存产物和下载 SHA/大小；
生产端仅处理请求中显式列出的 `64hex.rankN.attn`，再次核对 SHA/大小和文件未变，并拒绝
符号链接、路径逃逸和最近仍在写的文件。删除前写意图回执，删除后写完成回执，重复调用可恢复。
本地主动复用同一个 producer blob 的任务要全部完成归档；跨 host 的手工共享/replay 不由此工具
协调，若有这种用法应关闭 cleanup 并完成所有消费者核验。当前两机已核对无共享 blob。

- 保留：网页截图、逐 token/整体热力图、精确统计、原始请求/回复归档、得分与轨迹。
- 删除：通过上述核验并明确列出的生产端二进制 `.attn`。
- **生产端 JSONL 元数据仍保留**；未知归属、未完成、校验失败或 `keep` 的来源不删除。
- 回执：WSL `pages/producer-cleanup/<task-key>.json`；Klone `.cleanup-receipts/<receipt-id>.json`。
- SSH/校验第一次失败后写 `pages/.producer-cleanup-blocked.json`，停止同配置的后续尝试，
  不循环认证，也不阻塞 eval/导出。修复后用 `process-pending --retry-producer-cleanup` 显式恢复；
  正在工作的旧 worker 需正常退出后再启动。关掉 `enabled` 停止后续清理，不能恢复已删除的原始权重。
