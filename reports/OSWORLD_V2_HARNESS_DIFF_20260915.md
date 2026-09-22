# OSWorld-V2 workstation harness 与官方 v2026.08.08 的 diff

> **后续变更（2026-09-15，用户明确授权）**：仅将失败判定、非 ASCII 输入、`call_user` 及相应提示词恢复到官方语义，其他适配保留。本文下方完整 repo diff 是该恢复操作**之前**的审计快照。此次变更见 [三项恢复 patch](OSWORLD_V2_THREE_OFFICIAL_REVERTS_20260915.patch) 和 [18 项验证结果](OSWORLD_V2_THREE_OFFICIAL_REVERTS_20260915.validation.json)。workstation 的实际模块也通过全部 18 项测试。新文件 SHA-256：`8198beea2eb41bb2a49356e3328dc02b5b47d4661481cc320b95ca2d1a2b588d`；备份位于 `resume-20260915/qwen_internal_agent.before-three-reverts.py`。当前仍不是完全原版 harness。

## 结论

workstation 当前 `/home/yanji/research/OSWorld-V2-0808` **不是未修改的官方 harness**。
官方主仓库的 1,086 个普通文件中：1,080 个逐字节相同，6 个有实质修改，0 个仅换行差异，0 个缺失。
此外，源码目录中新增了 `scripts/python/run_multienv_qwen_internal_agent.py`，809 行。
这 7 个文件合计 **+1,016 / −22 行**。

底层单任务循环、任务加载器与 evaluator 源码一致，但 agent 的提示词、历史消息、动作解析，以及 VM 初始化和 runner 有差异。
因此“官方任务与判分 + 自定义 Qwen harness”是准确描述；不能写成“完全原版官方 harness”。

完整差异：[OSWORLD_V2_OFFICIAL_0808_WORKSTATION_20260915.patch](OSWORLD_V2_OFFICIAL_0808_WORKSTATION_20260915.patch)。

## 对照来源与校验方式

- 官方仓库：<https://github.com/xlang-ai/OSWorld-V2>。
- 官方 tag：`v2026.08.08`；本次 `git ls-remote` 核对到 commit **`d578d2d4e0dc82b43e270fdaa7fa89d9708cd154`**，与本地该 tag 的 commit 一致。
- 实际目标：`jy-eval-wsl` 的 `/home/yanji/research/OSWorld-V2-0808`。该目录没有 `.git`，因此采用官方 tag 文件列表逐文件 SHA-256 比较，不依赖 `git status`。
- 对新增源码的检查覆盖 `desktop_env/`、`mm_agents/`、`scripts/` 和根目录的 Python、shell、TOML、YAML、lock 文件；任务缓存、轨迹、环境密钥和依赖安装目录不混入源码 patch。
- 实际差异文件从旧 WSL 对应 checkout 获取；**7/7 文件 SHA-256 与 workstation 实时读取值相同**，以此确认用于生成 patch 的内容就是目标机器内容。
- patch 已在干净的官方 tag 快照上通过 `git apply --check`。

## 文件级差异

| 文件 | 行数 | 实际改动 | 影响范围 |
|---|---:|---|---|
| `scripts/python/run_multienv_qwen_internal_agent.py` | +809 | 官方 tag 中不存在的完整启动入口；创建 QwenInternalAgent，管理进程/任务队列、VM 生命周期、代理预检、结果恢复；每题调用官方 `lib_run_single.run_single_example` | 启动编排、参数、失败处理与恢复 |
| `mm_agents/qwen_internal_agent.py` | +106 / −18 | 修改提示词；接入并保存 user-simulator 回答；调整 `call_user` 和无可执行动作时的处理；移除全文 infeasible 子串判定；补 think 块；改变 chat-template 参数结构；非 ASCII 输入改用剪贴板 | 模型看到的上下文、可执行动作、任务终止与用户交互 |
| `mm_agents/qwen35vl_agent.py` | +11 / −2 | 从 API 的 `reasoning_content`/`reasoning` 取思考文本，拼入 `<think>…</think>`；官方仅返回 content | API 响应处理与可进入历史的内容 |
| `desktop_env/desktop_env.py` | +39 | Docker Ubuntu 启动后调用 xrandr 设置请求的分辨率，并轮询确认 | 观察画面与环境初始化 |
| `desktop_env/providers/docker/manager.py` | +14 / −1 | Ubuntu VM 优先选择配置/默认的字体补丁 qcow2，本地文件不存在则失败；替代官方原有 URL 路径 | VM 镜像选择 |
| `desktop_env/providers/docker/provider.py` | +29 | 启动后检查 `/etc/osworld-font-bundle.sha256` 与 Calibri 字体，失败则中断 | VM 启动门槛 |
| `desktop_env/controllers/setup.py` | +8 / −1 | 浏览历史 sqlite 下载源从 HF `resolve/main` 固定到 `711e0811642364e7aa8f10a8918367d0b626d578`，支持环境变量覆盖 | 特定任务 setup 的素材来源 |

## 最影响可比性的具体行为

### 1. `call_user`、无动作输出和终止规则

- 官方 `qwen_internal_agent.py`：`call_user` 会转成 DONE/FAIL；无解析到的动作也转成 DONE/FAIL；FAIL 与回复全文是否含 `infeasible` 有关。
- workstation：`call_user` 保存问题并清空该轮其他动作，让官方 `lib_run_single` 走 ASK_USER；没有可执行动作时把正文作为问题；明确失败通过 `terminate(status=failure)`。
- 官方 `lib_run_single.py` 自身有 ASK_USER/user-simulator 支持，而且这个文件与官方相同。变化发生在 **Qwen adapter 是否触发及怎样触发该路径**，不是新增了一个不同的 evaluator。
- 空白回复在 parser 前部提前返回；不能把所有空白回复行为概括成同一个新增分支。

### 2. 历史思考和模板参数

workstation 会把 API reasoning 字段拼回输出，并在回放历史 assistant 消息时调用 `_normalize_think`；缺少 think 块时补空块。
模板参数也从官方 `extra_body={enable_thinking: false}` 改为 `extra_body={chat_template_kwargs: {...}}`。
旧 args 中 `enable_thinking=false`、`preserve_thinking=false`，所以本次不能说“旧 run 开启了 preserve_thinking”；但这两个 false **不等于 adapter 与官方相同**。

### 3. 非 ASCII 文本输入

官方走 typewrite；workstation 对非 ASCII 文本使用 base64 传输、pyperclip.copy 和 Ctrl+V。
这是实际动作执行方式的变化，可能改变原本无法输入的文本是否成功。

### 4. WAIT 本次没有语义差异

两边均返回 `WAIT`。本次 patch 该处只有解释注释。
旧文档中“模型指定 0–60 秒”的描述不适用于本次核对的实际文件。

### 5. 自定义 runner 仍复用了官方底层循环

每个 worker 创建一个 QwenInternalAgent，取任务队列并调用官方 `lib_run_single.run_single_example`。
这是并行运行独立任务，不是引入 MACU manager/planner 或同题多 agent 协作。
但该 runner 本身不是官方文件，不能因复用了官方循环就称为官方原版。
其中 `OPENAI_BASE_URL = args.base_url` 也解释了之前 evaluator/user-simulator fallback 误用 Teacher 地址的风险；独立 BASE_URL 已另行配置并测试。

## 已确认不变的内容

- `lib_run_single.py`、`task_loader.py`、`desktop_env/user_simulator.py` 与官方 tag 逐字节一致。
- 官方主仓库的 `desktop_env/evaluators/` 文件未出现在差异清单中，均逐字节一致。
- 在前一步独立的 gated task 校验中，108/108 个任务文件与官方 `v2026.08.08` hash manifest 一致。该任务校验与本次源码校验是两件事。
- 本轮工作没有改动这些 harness 文件；前一步操作只创建了外部续跑脚本/清单、保存模型认证文件，以及备份并修复 `.env` 中两个独立判官端点。

## 额外边界：server 子模块、镜像和运行环境

官方主仓库另有一个 gitlink：`desktop_env/server` 固定在 `a3cc3f0c64e463f020d1a44780307e9b46cbcab1`，对应 <https://github.com/xlang-ai/osworld-server>，该提交含 19 个普通文件。
workstation 上该目录存在但为空，所以它不是完整递归 checkout；此项不包含在上述 1,086 个主仓库普通文件计数内。
这不能直接证明 VM 中运行的 server 版本错误，因为 Docker 客机服务可能来自预构建镜像；**客机内 server 的实际版本尚未核验**。

本轮也没有对 26GB qcow2 的每个字节、已安装 Python 包、正在托管的模拟网站部署做完整一致性证明。
源码锁文件一致，不等于运行时包集已核验；任务文件一致，不等于镜像和网站都已核验。

## 对后续运行的约束

用户明确要求 harness 与官方原版一致。当前自定义续跑入口不满足这个要求，因此 benchmark 保持未启动。
后续应基于固定官方 tag 的干净目录选择官方入口，并单独核对 Teacher 接入、server/镜像和运行参数。
该 tag 虽含 `QwenInternalAgent` / `Qwen35VLAgent` 类，但没有当前这份 Qwen internal runner；不能把旧 runner 复制进新目录后宣称“零修改官方”。
既有 39 个结果属于旧 adapter 协议；如改用原版协议，应独立保存、汇报，不能直接拼成一个同协议的官方总分。

本轮交付为审计与 patch，没有回滚、覆盖或启动 benchmark。
