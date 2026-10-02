# CUA RL 环境：源码副本、缺失项与进度

更新：2026-09-22，America/Los_Angeles。

## 2026-10-02：改走 Zixian 的 OpenWebRL 框架做 CUA 适配(用户确认)

**框架**：`zixianma/OpenWebRL` 的 `arm` 分支(`e3bbd52`)，slime(Megatron + SGLang)。本地工作区 `openwebrl-cua/`，分支 `cua-desktop`，Zixian 仓库的推送已禁用。cua-rl-gigpo(verl)那条线暂停，不再投 8 卡。

**她的 GRPO 基线**(`scripts/run_small_baseline.py --profile reference` → `scripts/run_h200_browser.sh`)：OpenWebRL-4B-SFT(Qwen3-VL-4B)全参数，2×H200 TP2 共卡；48 组 × 5 条，组内同分过滤后补采到 48 组；全局 256 轮次样本/次更新，micro 1，PPO 2(用 rollout logprob)；clip 0.2/0.28；KL 0、entropy 0；Adam lr 1e-6 常数、wd 0.1、β(0.9, 0.98)；temperature 0.8、回复 1024、上下文 32,768；上下文只放 1 张截图、思考全保留；步数课程 90 轮×15 步 → 50 轮×30 步；GPT-4.1 判 0/1；每 10 轮评 Online-Mind2Web 300。advantage(`slime/ray/rollout.py:752-816`)：每轮一条样本，按轨迹取最终奖励、组内减均值除标准差，同一轨迹每轮相同 —— 与我们的 `grpo_episode_level` 同一算法。第 90 轮 stealth full300 三次均值 55.22 ± 2.14%。

**用户 10-02 确认的 CUA 设定**：
| 项 | 定为 |
|---|---|
| 截图历史 | **20/10，按 eval agent 的 fold 规则**(满 20 张时把最老 10 张折叠成文字)，不用她的"只留最近 K 张" |
| 每回合步数 | **50**(= r5 eval) |
| 奖励 | **部分分**(任务 `reward.py` 的 [0,1] 分数)，不用判官；基础设施出错的轨迹整条剔除 |
| 每轮规模 | **48 组 × 5 条 = 240 条轨迹**(= 她的基线) |
| 视觉塔 | **训练**(= 她的基线) |
| 卡数 | 用户写"9 张卡"，待澄清 |
| 其余 | 对齐：采样按 r5 eval(temperature 1.0、top_p 0.95、top_k 20)；回复上限 32,768、上下文约 14 万(实测见上)；GRPO 部分沿用她的基线(PPO 2、clip 0.2/0.28、lr 1e-6、全局 256、动态过滤) |

**适配清单**：
- A 提示：rollout 改用 `native_session.build/record`(r5 原生格式、XML 工具调用、0–999 坐标、20/10 fold、保留思考)，只沿用她的样本记录；绕开她的思考标签处理和历史压缩；在她的 token 管线上重跑 85 决策逐 token 对照。
- C 环境：与 `RemoteWebEnv` 同接口的桌面环境，后端是现有 bridge(VM 在两台 Windows，Mac 中转)，动作后停 3 秒；并发 10；题目转 parquet；奖励函数读 `reward.py` 分数。
- D 训练栈(先验证)：她的 fork 有 Qwen3.5 的 Megatron 插件和权重桥(含 GatedDeltaNet)，没有 9B 启动配置，需从上游 `MSR-Orchard/slime` 的 `run_browser_qwen3.5_9b.sh` 移植；视觉塔权重能否加载/训练待验证；SGLang 与 Megatron 的 logprob 对一次；14 万 token 的显存实测；照她的 `scripts/h200_env.sh` 在 Tillicum 自建环境。
- E 评测：她的训练中评测换成 P2 dev 24 题或关闭；checkpoint 转 HF 后用我们的 OSWorld 流程评。

### 10-02 进展(私有仓库 `DengDuangLang111/openwebrl-cua`，分支 `cua-desktop`)

**仓库**：`arm` = Zixian `e3bbd52` 原样；适配只**新增**文件(`openwebrl/cua/`、`scripts/cua/`、`scripts/model_configs/qwen3.5-9B.sh`、`tests/cua/`)，不改她的文件，便于以后合回她的仓库。Zixian 仓库从未推送过(本地对应 remote 的 push 地址为 DISABLED)。用户要求先在私有仓库测好。

**代码**(提交 `66a7cee`…`9a344be`)：
- `openwebrl/cua/native_session.py` + `native_vendor/`、`remote_bridge.py`、`worker.py`：从 cua-rl-gigpo 原样复制，`SOURCE.json` 记 sha256。
- `desktop.py`：10 个常驻 worker 的 VM 池(VM 跨回合保持热状态)。
- `generate_desktop.py`：每轮一条样本，沿用她 rollout 的样本记录；提示/fold/思考/动作解析走 eval agent；断言 SGLang 的提示 token 数等于训练端；基础设施或超限的轨迹奖励记 `None`。
- `reward_desktop.py`：`reward.py` 部分分；`None` 由她现成的 `check_reward_nonempty_nonzero_std` 移出所在组的统计(她提交的代码里被剔除样本仍参与组内统计，这样处理不用改她的代码)。
- `scripts/cua/build_task_parquet.py`、`run_cua_desktop.sh`、`install_overlay.sh`；`tests/cua/native_parity.py`、`fake_desktop_bridge.py`、`smoke.sbatch`。
- 9B Megatron 参数：上游 MSR-Orchard 只有 Qwen3.5 0.8B/4B/27B/35B-A3B，9B 按 r5 `config.json` 填(32 层、4096/12288、16 头/4 组、head_dim 256、不共享 embedding、词表 248,320、rope 1e7、partial 0.25)。

**她的代码里两个 Qwen3.5 不兼容点**(我们的 rollout 不走这些路径)：`_ensure_im_end_w_new_line` 写死 Qwen2/3 的 `<|im_end|>` = 151645(r5 为 248046)；她现成环境 transformers 4.57.1 / sglang 0.5.6.post2 无 `qwen3_5`、未装 mbridge，不能训 r5。

**环境**：镜像 `slimerl/slime:nightly-dev-20260930a-cu129` → `rl/images/slime-nightly-20260930a-cu129.sif`(18.3 GB)。GPFS 上解包太慢(1.5 h 未完)、登录节点 mksquashfs 被杀(137)，最终在计算节点本地盘构建(debug 作业 340356，约 $0.9)。容器内：Python 3.12.3、torch 2.11.0+cu129、**transformers 5.12.1(有 qwen3_5)**、**sglang 0.5.15.post1(有 qwen3_5)**、Megatron-LM `1dcf0daf`(= 上游固定提交，带 slime 补丁)、fla 0.4.2、TE 2.16.1、flash_attn 2.8.3、ray 2.58.0。**缺 megatron-bridge 与 mbridge**(bridge 模式训视觉塔必需)→ 用 `install_overlay.sh` 装进 `rl/envs/slime-overlay`(不改镜像)。radixark `Megatron-Bridge@bridge` 最新提交 `8cd3466` 需要 `megatron.training.models`，镜像的 Megatron-LM 没有 → 正在找与 `1dcf0daf` 兼容的提交。

**已验证**：
- **逐 token 对照(容器内，她的 processor 编码路径，transformers 5.12.1)：85 决策 / 8 轨迹全部一致**。
- **真 VM 冒烟**(Mac → 中转 → 工作站 1 台 VM，P2 dev Calc 题 `5143f1f7`)：reset 51.2 s(开机+setup)、点击 3.6 s(含 3 s 停顿)、DONE 后 `reward.py` 0/4 项、r0 = 0；截图确认 Calc 打开题目文件。途中修了两处(cua-rl-gigpo `770d6bb`)：主机 OSWorld 的 `DesktopEnv` 不收 `force_disable_recording`/`volume_size`(改为只传支持的参数并记日志)；VM 内 Python 缺 openpyxl/docx/pptx(沿用 P0–P2 的 6 个纯 Python wheel，每次 reset 上传解压，setup/打分走 `PYTHONPATH`，镜像不改)。动作后停顿改为 3 s(`eff2cd9`)。
- 训练/验证 parquet：`rl/cua-data/train_20261001.parquet`(2,366)、`val_20261001.parquet`(24)。

**排队中**：8 卡冒烟 340365(假 bridge、完整协议、每 10 s 记显存，2 h，约 $14.4)。

**时间估算**(待实测)：10 台 VM 跑 240 条轨迹，每条平均约 15 步 × 约 25 秒 ≈ 6 分钟，一轮约 24 批 ≈ 2.4 小时，未计入 50 步长尾。

## 2026-10-01：Zixian(OpenWebRL)的 RL 算法与结果，和 Arijit GiGPO 的对比

依据：`zixianma/OpenWebRL` 的 `arm` 分支 `openwebrl/docs/ARM_SUMMARY.md`(10-01 06:54 版本 `2ed62d1`；main 仍停在 `9da6dc1`)。

- **算法**：outcome-only 的 GRPO 式 PPO。
  - 每题 5 条轨迹为一组，终局结果做组内归一化，得到优势值 A；同一条轨迹的每个 turn 用同一个 A。
  - 每次迭代 48 组(约 240 条轨迹)，batch 256，PPO 2 个 epoch，lr 1e-6。
  - 网页任务在实网上跑，由 VLM 裁判打分。
  - ARM 系列在此基础上，给部分 turn 加上动作奖励模型的加分(β=0.5，抽样 20% 的 turn)。
- **outcome-only 基线**(本地浏览器，GPT-4.1 裁判，Online-Mind2Web 全 300 题)：迭代 10 为 23.33%，20 为 31.67%，50 为 35.00%，80 为 38.00%，100 为 34.67%。迭代 0(SFT 起点)在同一口径下没有列出，所以 RL 相对 SFT 的增量无法从这张表读出。
- **ARM 在线变体**：迭代 90 在 stealth 浏览器上各评 3 次，基线 55.22%，Additive 58.44%(+3.2pp)，Gate B 58.78%(+3.6pp)。校正多重比较后不显著(Holm p=0.22)；WebVoyager 上持平或更低。作者结论：ARM 最可靠的用法是推理时多选一(30.0% 提到 42.7%)，在线 RL 加分尚未达到这个效果。
- **与 Arijit GiGPO 的对比**：Arijit 4B 跑了 36 步，每步 16 个回合，共约 576 个回合，OSWorld 19 题上没有提升。Zixian 每次迭代约 240 条轨迹、跑了约 100 次迭代，约 2.4 万条轨迹，曲线有上升。**两者的规模、环境、模型、评测口径都不同，不能据此判断算法本身孰优孰劣。**能说的只是：**有正面信号的是大规模的 outcome-only GRPO**。
- **对本项目的含义**：P2 计划每组 256 个回合，比 Zixian 小两个数量级。8 台 VM、平均每回合约 7.5 分钟，一小时约 64 个回合，跑到 2.4 万个回合要约 375 小时。

## 2026-10-01：cua-rl-gigpo——Arijit 的 GiGPO 框架改为本地 docker VM + r5 原生格式

用户要求：把 Arijit 的环境复制进自己的私有仓库，9B、截图不缩放、用原生格式，VM 改成本地 docker；两台 Windows 跑 VM，Tillicum 只做 GPU 训练和推理；训练题不要只限于 64 道。

**仓库**：私有仓库 `DengDuangLang111/cua-rl-gigpo`(用户要求不用 fork)。本地 `/Users/knight/uw/computeragent/cua-rl-gigpo`。`main` = Arijit `cac0a51`，完整 123 个提交；`upstream` 指向他的仓库，只拉不推。改动都在 `native-docker` 分支，已推送，代码停在 `29a1ac5`(10-01 晚)。为此在 Mac 上装了 `gh` 2.102.0(Homebrew)，用户自行登录。

**改动(每项都已提交)**：
1. `worker_bridge.py`：
   - `OSWORLD_PROVIDER=docker` 并用绝对路径的 qcow2 时走本地 docker，默认仍是 AWS；
   - setup 和评分改为经 VM `/execute` 同步执行，原来是后台启动后固定等 8 秒，评分写文件、睡 3 秒、再读回；
   - **评分脚本出错时抛错，丢弃这条轨迹**，原来是悄悄记 0 分，与设计"评分器崩溃算基础设施故障"相违；
   - 支持原生 pyautogui 代码动作(每个动作后停 2 秒，同评测)；
   - 回合结束后不再执行动作、不再重复打分；
   - 远程模式下，题目文件随 reset 内联传来。
2. **原生格式**：
   - 从评测 harness `d552441` 原样拷入 `QwenInternalAgent` 等 4 个文件，哈希与评测 registry 一致；
   - `native_session.py` 把它的 `predict()` 拆成"拼提示 / 解析回复"两步，中间的模型调用交给 verl；
   - `render()` 用 processor chat template，带评测的 `enable_thinking`/`preserve_thinking` 渲染，verl 原来不传这两个参数；
   - `served_text()` 复现评测服务端(vLLM 0.25.1 `--reasoning-parser qwen3`)的思考/正文切分，以及评测 agent `call_llm` 补回 `<think>` 的方式。
   - **逐 token 对照**(`scripts/native_parity.py`，Tillicum SFT venv，transformers 5.15.0)：回放 R4 导出的 85 个真实评测决策(8 条轨迹)，**消息、提示 token、图片网格、回复文本全部一致**。途中查出两处差异并修正：系统提示含运行当天日期(训练沿用当天，回放固定为录制日)；输出开头的 `<think>` 由服务端解析器拆出、评测 agent 自行补回。
3. **训练循环**：
   - env manager 原生模式：每个桌面槽位一个 `NativeSession`；
   - rollout 预处理走 `render()`，超长报错、不截断；
   - `gigpo.py` 新增 `train.format: native` 与 `train.native` 协议，**rollout 采样参数与评测不一致时拒绝启动**；
   - 题目加载器支持 ID 清单，并可指定本地的题目索引和题包，路径相对仓库根目录。
4. **远程 VM**(Tillicum 无 `/dev/kvm`、无 docker，只有 apptainer)：训练节点 `remote_bridge.py` 监听端口并校验共享口令；relay 连入后逐行转发到 VM 主机上的 bridge。**全部从 Mac 操作**，见下节。
5. **配置** `experiments/r5_9b_native_desktop_h200.yaml`：
   - 采样与评测服务端一致：temperature 0.8、top_p 0.95、**top_k 20**(来自服务端 `--override-generation-config`)、4096 token；
   - 图片最多 10 张，折叠 1；提示上限 32768；
   - 不用 KL，不加卡死或无效动作惩罚；按最终状态给 [0,1] 部分分；
   - 每步 2 组 × 4 条 = 8 台 VM，32 步(P2 预算 256 回合)，8×H200。
   - Mac 上空跑通过：71 个 verl 参数，题目清单生成正确。**尚未经用户确认参数表。**

**训练题池** `cua-rl-local/split-20260922/rl_pool.py` → `artifacts/rl-pool-20261001`，副本在 cua-rl-gigpo `data/rl_pool_20261001`：
- 训练 **2,366 道 / 170 个家族**(Calc 806、Writer 615、VS Code 552、Impress 393)；验证 24 道 = P2 Dev。
- 条件：审计保留、非 Dev/留出家族、符合运行协议，不要求逐题人工审。
- 另剔除与 Dev/留出家族题目相似度 ≥0.30 的 449 道：跨家族的参数变体比预想的多。
- 对照：Arijit 那 282 道里有 90 道被审计排除，58 道落在我们的留出集家族，所以不能直接用。

### 10-01 晚：VM 主机全部从 Mac 操作(代码 `29a1ac5`，`native-docker` 已推送)

**为什么不让 Windows 自己连 Tillicum**：WSL 里原来那条 Tillicum 主连接(`~/.ssh/cm/qwen36-tillicum-login`，评测隧道用的)已经不在；Tillicum 只收密码+Duo(实测 `Permission denied (gssapi-keyex,gssapi-with-mic,keyboard-interactive)`，密钥 `id_ed25519_tillicum` 单独登不上)，所以每台主机自己连就得各过一次 Duo。改为 **Mac 中转**：Mac 的 Tillicum 主连接已过 Duo、保持 30 天，Mac 开一条转发到训练节点的 hub，每台主机一个 relay 进程跑在 Mac 上，经 ssh 在主机上拉起 bridge。**代价：训练期间 Mac 要开机联网**(`up` 给每个 relay 挂 caffeinate 防闲置睡眠；合盖仍会睡)。

**用法**(Mac，仓库根目录)：
```
python3 scripts/vmhosts.py push          # 把 bridge 及其同目录模块、bridge_host.sh、host.env 推到两台主机(md5 核对)
python3 scripts/vmhosts.py check         # 镜像、bridge 能否加载、正在跑的 VM 数、可用内存；Mac 的 Tillicum 主连接
python3 scripts/vmhosts.py token         # 生成共享口令(Mac 600 权限)，装到 Tillicum(600)，不显示内容
python3 scripts/vmhosts.py up <作业号>   # 转发 Mac:18900 → 作业节点:18900；每台主机起 relay，名额 = 上限 − 已在跑的 VM
python3 scripts/vmhosts.py status | down
```
- 配置 `envs/vm_hosts.json`：路由、路径、上限(Windows 3 台 = 铁律；工作站 7 台 = 用户 10-01 定)。上限按主机上**所有** docker 容器算(含别人的评测)，超了 `up` 拒绝该主机。
- 路由：Windows = `ssh osworld-windows wsl -e …`；工作站 = 经 Windows 的 WSL 再 `ssh yanji@100.72.191.125`(jy-eval-wsl)。Mac 直连工作站不通：Windows 节点 22 端口关、Tailscale SSH 卡住。所有远端命令只传简单参数，不套引号层。
- `down` 停 relay → 各 ssh 会话关闭 → 远端 bridge 读到 EOF → 关自己的 VM。

**实测(都不起 VM)**：
- 两条路由 4MB 单行原样到达；
- Mac 端 ssh 被 `kill -9` 或 stdin 关闭后，远端进程都读到 EOF 并退出，不留进程；
- 端到端：Mac 上的 hub ↔ relay ↔ ssh ↔ 两台主机上真实的 `worker_bridge.py` 来回通过(未知命令得到报错、close 得到 ok、bridge rc=0 退出后 relay 重新拨号)；
- 首次端到端抓到缺口：bridge 运行时还要加载同目录的 `reward_parse.py`、`hit_test.py`，已改为一起推送。`check` 现在会真的加载一遍 bridge，对照组缺这两个文件时报 FAILED；
- `tests/test_remote_bridge.py` 新增两个反例，都不拉起 bridge：口令错误；端口后没有 hub(relay 要等到 hub 的准入回复才启动 bridge，否则隧道空转时会不停拉起远端 bridge)。

**Tillicum 侧已就绪**：
- 训练环境 `verl-native` 里重跑逐 token 对照：**85 决策 / 8 轨迹全部一致**(transformers 5.16.1)；
- 模型目录 `models/r5-9b-s306`：软链 checkpoint-306 的权重与配置，加上 processor 目录多出的 merges/vocab/video 配置。两边重名的 7 个文件 md5 全同，`AutoProcessor` 加载得到 Qwen3VLProcessor / qwen3_5；
- 题目数据 `data/cuagym/` 两个文件 md5 与 Mac 一致；Tillicum 上空跑读出 2366 训练 + 24 验证；
- 两个实验的 verl 占位 parquet 已在登录节点生成(要下载 geometry3k，计算节点不一定能上网)；
- 训练 sbatch `launchers/tillicum_rl.sbatch <实验名>`：1 节点 8×H200、QOS normal、24h、作业名 `rlx`；`NCCL_P2P_DISABLE=1`(Tillicum 上 NVLink P2P 崩溃复现过两次，CUA `c4306e05`)。日志会打出代码 hash 和"从 Mac 运行 `vmhosts.py up <作业号>`"的提示。

**扩展编译**：339174 失败，原因是 venv 的解释器是系统 `/usr/bin/python3.12`，没有 `Python.h`。改为从 uv 管理的同一小版本(3.12.13)取头文件(CPython 同一小版本 ABI 不变)，并在编译前预检。预检在登录节点通过，不加修复的对照组照样报缺 `Python.h`。重投为 339202。

**未完成**：
- 339202 编译结果。
- 8×H200 正式训练：**参数表待用户确认后再投**。
- 真 VM 冒烟 `scripts/smoke_remote.py`：等两台 Windows 上别人的评测跑完。当前占用 Windows 3/3、工作站 6/7。
- 一轮训练步里实际做几次参数更新(`ppo_mini_batch_size` 在多轮展开后的含义)；clip 用 0.2 还是 0.28。
- Binary 对照组的二值化奖励开关。

### 10-01 晚：按 r5 的标准 eval 重新核对 RL 协议(用户指出 2x5 / temp1 / 20fold10)

**更正**：上文配置的采样与窗口(temperature 0.8、4096、10/1、30 步)来自 P1/P2 面板的 registry(`cua-eval/registry.cuagym-p{1,2}-r5*.json`)，那是 RL 设计文档 §4 写明的"待测量确认的起点"，**不是 r5 的 eval 协议**。yaml 注释"采样与 eval 服务端一致"是错的：eval agent 每个请求都显式发送 temperature/top_p/max_tokens(`qwen_internal_agent.py:309-311`)，服务端 `--override-generation-config` 只补未发送的项(top_k 等)。

**r5(a2 = `img10-9b/checkpoint-306`)标准 eval 的实际参数**(WSL `results_generated/qwen35-9b-sft/eval50-a2-20260823/args.json` 与 `MODEL_BOUNDARY.json`，serve `sft/scripts/train/archive/serve-chain-img10-a2261.sbatch`)：

| 项 | a2 eval(61.0%，RESULTS §5.30) | P1/P2 面板 / 原 RL 配置 |
|---|---|---|
| temperature / top_p / top_k | **1.0** / 0.95 / 20(服务端) | 0.8 / 0.95 / 20 |
| min_p / presence / repetition | 0 / 0 / 1.0 | 同(vLLM 默认) |
| max_tokens | **81,920** | 4,096 |
| 图片窗口 | **image_max 20 / fold 10**，history 100 | 10 / 1 |
| max_steps / 动作后停顿 | **50 / 3 秒** | 30 / 2 秒 |
| thinking / preserve_thinking | 开 / 开 | 同 |
| 服务端 | vLLM `--max-model-len 262144`、`--reasoning-parser qwen3`、fp8 kv-cache、每提示最多 20 图 | — |

- r5 的 SFT 数据是 **img10/fold1**、思考不截断(CHECKPOINTS.md 第 21 行)；a2 的 61.0% 是在 20/10 下评的，RESULTS 记为"训 10 图评 20 图的窗口错配"。现行主 registry 的 Verified 协议是 temp 1.0、10/1。
- **组大小**：用户 10-01 定"工作站开 7 台"，加 Windows 3 台共 10 台 = **2 组 × 5 条**，原配置仍写 2×4，已更正。
- **训练题出处**：HuggingFace `xlangai/CUA-Gym` 的 `artifacts/cua_gym_tasks_v1.tar.zst`(sha `2198e335…`)+ `data/tasks.parquet`；Calc/Writer/Impress/VS Code 7,249 道 → 去掉 OSWorld-Verified 重叠 2,247、dev/留出家族 1,627、不符合运行协议 560、与 eval 题近重复 449 → **2,366 道**。

**上下文实测**(a2 eval100 的 100 条轨迹、2,162 轮，用训练代码 `native_session.build` + chat template 逐轮重建；截图用同尺寸空白图，单图 2,040 token；每 50 轮做一次完整 render 对照，44 次全一致)：

| | 10/1 | **20/10** | 20/10 且只看前 30 步 |
|---|---|---|---|
| 提示 p50 / p90 / p99 | 25,084 / 53,230 / 95,033 | 32,088 / 65,689 / 106,199 | 25,482 / — / 87,014 |
| 提示最长 | 113,647 | **134,007** | — |
| 提示 + 回复 > 65,536 的轮 | 132(6.1%) | 225(10.4%) | 69 / 1,729(4.0%) |
| 提示 + 回复 > 81,920 的轮 | 38 | 98 | 27 |
| 提示 + 回复最长 | 114,508 | 134,868 | 109,760 |

- 回复(与窗口无关)：p50 188、p90 1,166、p99 5,190、最长 29,065 token；超过 4,096 的 37 轮(1.7%)，超过 8,192 的 11 轮，超过 16,384 的 4 轮。
- 长的原因：preserve_thinking + history 100，之前每轮的思考都留在上下文里。r5 的 SFT max_length 是 65,536。
- **两次测量踩到的坑**(已改正)：OSWorld 的 traj.jsonl 一条回复含多个动作时，每个动作各写一行(相同 step_num、相同回复)；第一次把它们当成多轮，得到"每题 195 步、提示 43 万"的假数字。同一原因让 P1 统计误报了"4096 截断 2.7%"：去重后 P1 为 48 次尝试 / 701 轮，**思考未闭合 0 轮**，无 tool_call 2 轮，最多 30 步，平均 14.6 步。

**由此暴露的训练端问题**(都在 `third_party/molmoweb-rl`，未改，待用户同意)：
1. **一律补齐到上限**：提示左补齐到 `max_prompt_length`(`rollout_loop._preprocess_native`)、回复右补齐到 `response_length`(`vllm_rollout_spmd.py:439`)，而配置是 `use_remove_padding=False`、actor 没有去补齐的步骤，所以每条轮次样本都按"提示上限 + 回复上限"整段计算。上限一旦按 eval 放到 13 万以上就算不动。
2. **整段 logits**：非 rmpad 分支先算整条序列的 logits 再切出回复段(`dp_actor.py`)，13.5 万 × 248,320 词表，bf16 也要约 67 GB。Qwen3.5 前向支持 `logits_to_keep`(transformers 5.16.1 `modeling_qwen3_5.py:1786`)，可以只算回复段。
3. **每步更新次数**：verl 把 `ppo_mini_batch_size` 乘 n 再除以卡数(`fsdp_workers.py:163-164`)，2×4/8 = 1、2×5/8 也取整为 1，于是每张卡每 1 条轮次样本更新一次参数，一步约 20–25 次优化器更新、每次全局 8 条样本(`dp_actor.py:435`)，与设计 §5"每次更新收集若干有效 task groups"不符。

**扩展编译**：339202 成功(causal_conv1d 1.7.0、flash_attn 2.8.3.post1，FA2 前向通过)。

## 2026-10-01：Arijit 的 CUA RL 能否训 r5(只读核对)

依据：`cua-rl-local/sources/multi-agent-framework`(`cac0a51`，2026-09-09；`git ls-remote` 显示远端 main 仍是这个提交，Arijit 未推送的本地改动看不到)。逐项核对 `CLAUDE.md`、`README.md`、`experiments/cuagym_sft35_gigpo_r2.yaml`、`experiments/cuagym_sft35_native_h10_osworld_v1.yaml`、`third_party/molmoweb-rl/agent_system/environments/env_package/cuagym/action_space.py`：

- **起点是用户的模型**：`DanielYanCua/osworld-verified-sft-qwen3.5`，快照 `b9de2332…/4b`；仓库内另有 9b 版本。配置注释引用了用户的数字：在改过的 OSWorld 361 题、50 步、20 图条件下，骨干 31.67% → SFT 47.00%。
- **训练采样不用原生格式**：
  - 他的环境把截图缩到 1280×736，坐标是 0–999 相对网格，动作用 JSON 工具调用，先 `<think>` 再出动作；
  - 每步只带 1 张历史截图(从 4 张降到 1 张，因为多模态前向太慢)，`max_tokens=1500`；
  - 他的原生格式实验(`OSWORLD_AGENT=qwen35vl`，用 mm_agents/qwen35vl_agent.py)只做了评测：4B 在 2 图 5.0%、最多 15 图 22.2%；在他自己的格式下 12%(37/308)的步骤无可用输出。
- **硬件**：4B 在 2×H200 上分配 102GB、保留 119GB，每步约 24 分钟，764 题按每步 4 题算一个 epoch 要 191 步(约 76 小时)。他实测 48GB L40S 会 OOM，80/96GB 档在 vLLM 占用后也放不下。9B 没有在这套栈上训过。
- **环境**：桌面题跑在 AWS EC2(`DesktopEnv`，provider 写死为 aws)，网页 mock 跑在 BU SCC，另有 WebGym 实网(LLM 裁判打分)。训练题为 CUA-Gym 桌面 282 + mock 网页 282 + WebGym 200；桌面题从四应用 7,249 题中随机抽取，没有做 OSWorld 重叠审计(其中会有 `osworld_` 家族)。
- **结果**：36 步没有可测提升(OSWorld 1.0 共同 19 题：SFT 2/19，step17 2/19，step24 3/19，step36 1/19；训练成功率 0.106 vs 前一次 0.108)。作者写明不确定是 setup 还是方法的问题，并建议下一步在 OpenWebRL 的题集上做阳性对照。
- **可借鉴**：
  - 奖励 v2：按最终状态给 [0,1] 分，不减初始分；之前 `r_end - r0` 会让"开局即满足"的题得 0；
  - 零优势过滤向上取整到真实除数；
  - 卡死循环提前终止并扣分；
  - 训练和评测的推理格式必须一致；
  - 比较 checkpoint 时，评测配置只能改模型路径；
  - 每步耗时主要在多模态样本的三遍前向(97.8%)。

**结论**：Arijit 的训练栈能加载 Qwen3.5，但要拿来训 r5，至少还要做四件事：把 r5 的原生格式接进训练采样、换一台 8×80GB 级别的机器、把 AWS 换成本地 docker、换成审计过的题单。对比之下，我们自己的单卡链路已经在原生格式下对 9B 做过两次更新(update1/2)，缺的是自动循环。两条路的取舍已写入设计文档 §11。

## 2026-09-22 23:57：P1 训练信号探测完成(π0，16 题 × 4 条)

12 道新题 × 4 轮 = 48 回合(17:51–23:57，workstation 单 VM 串行，平均每题约 7.5 分钟)，全部评分，failed/blocked/interrupted 为 0。与 09-18 的 4 题(同协议)合成 16 题。证据在 `cua-rl-local/artifacts/p1-pi0-20260922b/`(summary.json、episodes.json)。

| 题 | 应用 | 4 条得分 | 原始分差异 | Binary 差异 | 重叠审计 |
|---|---|---|---|---|---|
| 693b3046 | Calc | 0,0,0,0 | 否 | 否 | 排除 |
| e31f36af | Calc | 1,0,1,1 | 是 | 是 | 保留 |
| 86bc4aea | Calc | 0,0,0,0 | 否 | 否 | 保留 |
| f34a4410 | Calc | 0.7,1,0.7,0.64 | 是 | 是 | 排除 |
| f02c7f7f | Writer | 0,1,1,1 | 是 | 是 | 排除 |
| de0be554 | Writer | 0,0,0.8,0 | 是 | **否** | 排除 |
| c440c03f | Writer | 0,0,0,0 | 否 | 否 | 保留 |
| dc185455 | Writer | 0,1,1,1 | 是 | 是 | 保留 |
| 2ecc76ab | Impress | 1,1,1,0 | 是 | 是 | 排除 |
| e2b1a84c | Impress | 0,1,0.3,0 | 是 | 是 | 排除 |
| 4cd0f3c6 | Impress | 0,0,0,0 | 否 | 否 | 排除 |
| aed6f1eb | Impress | 0,0,0,0 | 否 | 否 | 排除 |
| d46f3728 | VS Code | 1,0.4,1,0.4 | 是 | 是 | 保留 |
| 73e6b00f | VS Code | 1,0.25,1,0.25 | 是 | 是 | 保留 |
| 38cb2821 | VS Code | 0,0,0,0 | 否 | 否 | 保留 |
| a1243b01 | VS Code | 0,0.3,1,0.7 | 是 | 是 | 保留 |

**按设计文档 §6 的 P1 条件逐条核对**：
- 环境无效率：0/48(09-18 为 0/16)。第一次启动时 harness 缺 `.env`，失败发生在 VM 启动前，没有产生回合，已修复并记录在上文。**通过**(≤5%)。
- 格式无效率：48 条轨迹共 701 次决策，未检出无法解析的输出(检查方法：动作为空/NONE/FAIL，以及日志里的解析错误字样)；37 条由模型自行 DONE 结束，11 条用满 30 步。**通过**。需说明：harness 是否还有其他记录解析失败的方式，本次没有逐一核实。
- 有奖励差异的组：原始分 10/16，Binary 9/16，≥4/16。**通过**。
- P0/P1 模型回合总数：09-18 单条 1 + 分组 16 + π1 16 + P1 48 = 81，未超过 128 的上限。

**对研究问题的含义(如实记录)**：
- 只有 Partial 奖励才有差异、Binary 全等的组只有 1 个(`de0be554`，且已被审计排除)。在重叠审计保留的 8 题里，两种奖励下有差异的组都是 5/8。
- 也就是说，在 π0 的这个样本上，部分分几乎没有带来额外的"有差异组"。C−B 的差别更可能来自组内优势值的不同(如 f34a4410、e2b1a84c、a1243b01 的多档分数)，而不是有效组数量。P2 应按设计同时记录两种奖励下的有效组比例与优势值差。
- 总体：平均分 0.38，完全做对 19/64。

## 2026-09-22：P2 选题与可复用夹具(用户要求"现在开始选题，夹具做成可复用的")

工具都在 `cua-rl-local`(分支 `iter2`；P1 驱动从工作区读脚本，期间不切分支)，运行前先提交。

**选题流水线**(每步都是参数化工具，P3 或以后的批次直接沿用)：
1. `split-20260922/make_pool.py`：审计保留的 5,002 题 → `screen.py` 的候选池格式。
2. `p1-20260922/screen.py`(原样复用)：机械初筛，排除清单 `split-20260922/exclude.json` 只列有记录原因的 17 题(09-18 评分缺陷 4、09-18 审过未选 7、P1 审题否决 6)。已用题不排除，由划分放到训练侧。结果：**1,364 题通过**(Calc 419、Writer 512、Impress 247、VS Code 186)。最大淘汰项"评分有副作用" 1,943 题(评分脚本含 subprocess、time.sleep 等)，这条规则偏严；题量够用，暂不放松。
3. `split-20260922/split.py`：家族级 train/dev/holdout(种子 20260922；每应用家族份额 holdout 25%、dev 15%)。已用题的家族强制归 train。评测侧与任一训练题相似度 ≥0.30 的剔除：校准时抽看 0.35–0.63 基本是跨家族的参数变体，如自定义放映、断字、奇偶页页眉、标题 3 样式；0.25–0.30 多为不同的题。共剔除 59 题。每份按家族轮转排出审题队列。

| 应用 | train 家族/题 | dev 家族/题 | holdout 家族/题 |
|---|---|---|---|
| Calc | 16 / 280 | 4 / 44 | 6 / 84 |
| Impress | 12 / 162 | 3 / 32 | 5 / 38 |
| Writer | 39 / 308 | 10 / 38 | 16 / 139 |
| VS Code | 15 / 113 | 4 / 29 | 6 / 38 |

已用题中 8 题合格且落在 train：e31f36af、86bc4aea、c440c03f、dc185455、73e6b00f、38cb2821、a1243b01、d46f3728；其余 8 题被审计排除。
- 初筛通过的题集中在少数大家族(Calc 审计后 548 个家族，初筛后只剩 26 个)，dev 多样性偏低。
- P3 holdout 需每应用 32 题，Impress、VS Code 各只有 38 道候选；按约一半的审题通过率会不够，届时需放宽"评分有副作用"这条初筛规则。

**可复用夹具 `qualify/`**：
- 构成：核心 `fixtures.py`(接口与 P1 相同：TASKS/PHASES/apply)，加按格式分开的原语模块 `ops_xlsx/ops_docx/ops_pptx/ops_text.py`，每题一份声明式清单 `specs/<id>.json`。
- partial 缺省由 solved 自动截取前一半目标，不合适时四态检查会失败，再显式写出。
- 只导入当前文件格式的模块，一个格式的改动不会影响其他格式。
- P1 的 15 个手写夹具已移植为清单；在 Windows WSL 回归，12 题四态得分与 `local-20260922c` **逐项相同**(拆模块前后各验证一次)。
- 配套：`qualify/REVIEW.md`(审题标准：不对称评分、假阳性、LibreOffice 存盘后假阴性、罚自然解法、OSWorld 参数变体、超 30 步、计分项不足)与 `qualify/check_remote.sh`(一条命令把包推到 Windows、跑四态检查、报告拷回)。

**VM 往返检查(Windows，镜像 v2026.06.24 official-fonts；21:22–22:22)**：共 99 道入选/备选题。每题先重置 VM，跑原 setup，要求初始分为 0，截图；再把四态文件经 VM 自带的 LibreOffice 另存一遍后重新评分。

| 批次 | 通过 | 失败(原因) |
|---|---|---|
| Writer + VS Code 48 道 | 45 | `b8c22ab3` 文档属性存盘后 solved 0.6；`f3c69e0f`、`b803bd24` 批注回复的关联存盘后丢失，solved 0.7(审题时已标此风险) |
| Calc + Impress 51 道 | 45 | Calc 入选 22 道全过；3 道 dev 备选因工作表密码哈希大小写失败(审题时已标)；Impress `35ce29dd` 存盘后部分完成状态也得 1.0(评分区分不出，会有假阳性)，`057a2a81` 存盘后 solved 0，`dc747924` 存盘后 solved 0.15 |

- 失败题一律否决，由通过 VM 检查的备选递补：Writer train `b194a3ec`、Writer dev `d8a4d1d0`、Impress train `01ebde10`。
- 抽看截图(VS Code `0b1338e1`、Writer `e7e7942a`)：题目文件正常打开，无恢复对话框，无上一题残留。
- 证据：`artifacts/split-20260922/vm/`。

**P2 最终题单 `artifacts/split-20260922/p2-panel.json`**：每题都有 VM 往返通过记录，P1 已用题引用 `vm-20260922d`。
- **train 64 道**：每应用 16，含已用题 8 道。
- **dev 24 道**(设计为 32)：Calc 8、Writer 7、**Impress 1**、VS Code 8。Impress dev 队列 32 道全部审完，只有 `0fac5efe` 一道同时通过审题和 VM。
- 备选：Calc 6、Writer 1、VS Code 2。
- dev 集中度：Calc 8 道中 6 道是 `calc_ps`(保护类)，VS Code 4 道是 `vscode_code`。

**P2 审题结果(21:30 完成，四态检查全部 PASS)**：按应用各派一个子代理，按队列顺序审题、写清单、在 Windows 上跑四态检查。各代理只能改自己格式的原语模块，新原语须参数化，并对本格式 P1 清单做回归(四个格式均逐项相同)。之后由我复核。审题记录见 `artifacts/split-20260922/review/<app>-review.json`，每题一条，含理由、风险与 OSWorld 近邻判断。

| 应用 | train 审/选/备选 | 通过率 | dev 审/选/备选 | 新增原语 |
|---|---|---|---|---|
| Calc | 112 / 14 / 4 | 12% | 44(全部) / 8 / 5 | 12 个(条件格式、页面设置、命名区域、数据验证、保护、图表、误差线等) |
| Writer | 58 / 14 / 2 | 24% | 38(全部) / 8 / 1 | 14 个(节、分页、页边框、页眉页脚、域、批注及回复、语言、底纹、制表位、属性等) |
| Impress | 162(全部) / 16 / 1 | 10% | 32(全部) / **3** / 0 | 15 个(表格格式与边框、编组、形状、背景、重排、自定义放映、动画、图表等) |
| VS Code | 49 / 12(+已用 d46f3728) / 2 | 27% | 29(全部) / 8 / 0 | 2 个(按行范围替换、按行块移动) |

训练集连同已用题每应用 16 道，已凑齐；dev 共 27 道(Impress 缺 5)。

**审题中发现并修复的检查器问题(均已提交，P1 回归不变)**：
1. 产物路径表达式是字面 `/home/user/...` 的题，`check_local` 没有把它映射到临时目录，误报找不到文件。VS Code 代理发现，`5eee446` 修复后，其 4 道 dev 题通过。
2. 四态判定要求 solved 严格等于 1，但评分脚本做浮点相加时，正确文件得 0.9999999999999999。改为与 RL binary 相同的阈值(r ≥ 1−1e-6)，由 `fixtures.four_states_pass` 统一给两个检查器使用(`9ff58d8`)。Writer 的 `d8a4d1d0` 因此恢复为 dev 备选。

**我的复核**：
- 抽查 VS Code `0b1338e1`、`8844e304`：评分检查项与指令一致，wrong 是真实的正则错误。
- Impress `1ef231c1` 改为否决：指令写 'product_launch.pptx'，setup 实际打开 impress_gf5_013.pptx。由备选 `2d5d8ba3` 递补。
- Impress `057a2a81` 保留："evenly distributed across the slide" 可以理解为铺满整页、两侧留白相同；只做"对齐 + 均匀分布"得 0.7，是真实的部分完成状态。
- 各代理新增的原语没有写死任何题目 ID 或路径。

**集中度与多样性问题(如实记录)**：
- dev：Calc 8 道中 6 道来自 `calc_ps`(工作表/单元格保护)；Writer 4 道来自 `writer_struct`(批注)；VS Code 4 道来自 `vscode_code`。原因是 dev 队列里其他题都没有通过审题。
- train：Impress 有 4 道来自 `impress_tct`。

**对 P3 的影响(重要)**：CUA-Gym 评分脚本的主要问题是要求指令没说的东西、依赖 LibreOffice 存盘会改写的细节，审题通过率只有 10–27%，远低于 P1 的约 55%。按这个比例，现有队列撑不起 P3(每应用 train 64 / dev 16 / holdout 32)：Calc train 约 280×12%≈34 道，VS Code 约 113×27%≈30 道；四个应用的 dev 队列都已审完，都凑不齐 16 道。进入 P3 前须扩大候选池，办法包括放宽初筛(如"评分有副作用"一条淘汰 1,943 题，评分前 postconfig 的题 552 道需要适配器支持)、引入其他题源。

**LibreOffice 存盘相关风险(交 VM 往返检查裁决)**：
- 若干否决依据是审题代理对 LibreOffice 导出行为的记忆，没有经过 VM 实测。例如 Calc 条件格式的填充色字段、工作表密码哈希的大小写；Writer 批注 ID 与脚注重新编号、分页、分栏等。这些题在 VM 中验证前不作最终结论。
- 入选题中依赖导出细节的，已逐题写入 risk 字段，如 Writer 批注回复线程、Impress 多母版与自定义放映。

## 2026-09-22：CUA-Gym 对 OSWorld-Verified 的重叠审计(用户选方案 a：CUA-Gym 去掉重叠后作训练来源)

代码 `cua-rl-local/split-20260922/overlap_audit.py`(`c4591d7`，运行前提交，输出记脚本 SHA)，产物 `artifacts/overlap-audit-20260922/t025/`(summary.json、families.json、tasks.jsonl.gz)。输入：CUA-Gym 包 `cua_gym_tasks_v1.tar.zst`(sha `2198e335…`)、OSWorld-upstream `test_nogdrive.json` 361 题(sha `fcb9497e…`)。审计 Calc/Writer/Impress/VS Code 共 7,249 题，耗时约 2 秒。

**方法**：每题两个相似度通道，都在删除参数(数字、引号内容、单元格区域、文件名)后算 tf-idf 余弦，idf 按参考集 361 题统计：
- 指令 ↔ OSWorld 指令；
- `reward.py` 的 "Component N:" 评分项 ↔ OSWorld 指令 + 评分函数名。

`osworld_` 家族、无 TASK_ID 的题整族排除；相似度按单题判定，因为 CUA-Gym 的"家族"是主题批次(如 `writer_tech` 120 题，操作各不相同)，不能因一个成员相似就排除整族。家族仍是之后划分训练/Dev 的单位。

**调试记录(对照发现的问题，均已修)**：
1. 已知重复 `de0be554`↔`66399b0d` 起初只排第 2(0.11)：没有单复数归一，idf 又按 CUA-Gym 统计，"table/insert"等词权重被压低。改为单复数归一、idf 按参考集统计后排第 1。
2. 参数替换成占位词("num num num")使只是列了几个数字的无关题相似(如"自定义放映第 1、2、5 页"↔"第 3、4、6 页图片高度")。改为直接删除参数。
3. 删引号的规则把缩写撇号(I'm、I've)当成引号，整句被删到只剩"desktop"，出现假 1.00；这也会让含缩写的题丢词、掩盖真重叠。改为引号外侧不能紧挨字母。

**召回检查**：抽查低分 `osworld_` 家族。多数是 `osworld_multi_apps_*`(按 OSWorld 领域原创，Verified 中无对应原题)；但 `osworld_calc_fill_blanks_above` 与 OSWorld `01b269ae`(用上方单元格填充空白)是同一操作，只得 0.18。原因是 CUA 指令带大段业务背景，稀释了余弦；它仍排第 1 近邻，因此已作为第二对照。试过"查询只保留参考词表中的词"：两对照分数升高，但 ≥0.30 的题从 85 暴涨到 740(泛化短题成为枢纽)，未采用。**结论：词面相似度能把真原题排在前面，但分数没有干净的分界。**

**阈值 0.25(两通道)的依据**：人工看 ≥0.30 的 85 题与评分项 ≥0.33 的 30 题，真实的同类操作重叠一直延续到约 0.30。例如：行距 `0810415c`、底部页码 `0e47de2a`、Impress 插表 `39be0d19`、簇状柱形图 `12382c62`、导出 CSV `3aaa4e37`、透视表 `535364ea`、工作表重命名/复制 `0cecd4f3`、演讲者备注 `841b50aa`、保存工作区 `5e2d93d8`(0.31)、切换效果 `21760ecb`(评分项 0.36)、分页 `ecc2413d`。噪音主要来自几道泛化短题(`c82632a4` 插图 none.png、`2b94c692` 移动图片等)。0.25 约为池子 95 分位，误删代价小。

**结果**：7,249 题保留 **5,002**(全部为 Python setup)。排除原因(可重叠)：`osworld_` 家族 995、无 TASK_ID 929、指令 ≥0.25 441、评分项 ≥0.25 227。

| 应用 | 保留题数 | 有保留题的家族 |
|---|---|---|
| Calc | 1,827 | 548 |
| Writer | 1,450 | 149 |
| Impress | 751 | **29** |
| VS Code | 974 | **26** |

Impress 与 VS Code 的家族少而大，P3 按家族分训练/Dev/留出三份时颗粒较粗。

**已用 16 题中 8 题被排除**：
- 09-18 P2 的 4 题排除 3 题：`693b3046`(`osworld_calc_zoom_adjustment`)、`f02c7f7f`(`osworld_writer_line_spacing_per_paragraph`，指令 0.51 ↔ `0810415c`)、`2ecc76ab`(指令 0.31 ↔ `9cf05d24`)。update1/update2 的训练信号正来自 Writer `f02c7f7f` 与 Impress `2ecc76ab` 两组。作为链路探针不影响结论，但这两次更新不能作为 OSWorld 效果的依据。
- 12 道新题排除 5 题：4 道 `osworld_` 家族，另加 `4cd0f3c6`(评分项 0.29 ↔ `7dbc52a6`)。
- P1 仍按原计划跑完：它只探测训练信号，不进入训练集。

**三道防线**：
1. 本审计自动排除。
2. 选入训练/Dev 的每道题人工复核两通道前 3 近邻，理由记入选题清单；这一步补上 fill_blanks 这类"排第 1 但分数低"的漏检。
3. 评测时回查 OSWorld 上 B/C 比 A 多做对的题，看训练集中有无近邻。

## 2026-09-22：题目来源与 OSWorld-Verified 重叠风险(只读测量，未处理)

- **来源**：RL 所用 16 题全部来自 xlang-ai 公开的 CUA-Gym(`datasets/tasks.parquet`，10,910 行)。筛选路径：desktop 四应用 7,249 道 → Python setup 6,391 道 → 09-18 只读候选池 2,041 道(每应用最多 600) → 机械初筛通过 1,014 道 → 人工审查 12 道；另 4 道为 09-18 选出的 P2 pilot。
- **与 SFT 数据的关系**：SFT 语料由自有 ostg 流水线生成，生成时以 CUA-Gym 为回避语料，入库闸门要求与 CUA-Gym、官方 361 的文本相似度 <0.50(`taskgen/docs/PIPELINE.md`)。因此 CUA-Gym 题在文本层面对 SFT 是新题；但该度量看不出只差参数的重复。
- **与 OSWorld-Verified 的关系(风险)**：CUA-Gym 与 OSWorld 出自同一实验室，按模板生成，`initial_setup.py` 的 `TASK_ID` 指明模板家族。机械初筛通过的 1,014 道中，有 **232 道(23%)属于 `osworld_` 开头的家族**：Impress 98/202、Calc 73/286、Writer 61/374、VS Code 0。本次 12 道新题中有 4 道属于这类家族：`de0be554` 插表、`e2b1a84c` 去项目符号、`f34a4410` VLOOKUP、`aed6f1eb` 全部居中。
- **实例**：`de0be554`(`osworld_writer_table_creation_001`，"在第二段下插入 3 列 4 行表格")与 OSWorld-Verified `66399b0d`("在光标处插入 7 列 5 行空表格")只差参数。粗略文本最近邻(SequenceMatcher，对照 test_nogdrive 361 题)中，最高的几道也都是 `osworld_` 家族的题(0.52–0.55)。
- **影响**：P1 是训练信号探测，这 4 题留在 P1 不影响探测结论；但若进入 P2/P3 训练集，OSWorld-Verified 上的"迁移"结论就不干净(RL_EXPERIMENT_DESIGN §4 要求的重叠审计尚未做)。训练集划分前须按家族做结构审计：比较每个家族的 `reward.py` 检查什么，与 OSWorld-Verified 四应用 140 题(Calc 47、Impress 47、Writer 23、VS Code 23)的 evaluator 检查什么。

## 2026-09-22：P1 审题——从 2030 道候选选出 12 道新题(每应用 3 道)

用户要求 P1 按计划推进、先审 12 道题。P1 = 已有 P2 的 4 题(π0 已各采 4 条)+ 12 道新题，共 16 题；新题的 π0 采样(12×4=48 条)在审题完成后进行。代码在 `cua-rl-local` 的 `p1-20260922/`，与 iter2 同在实验分支 `iter2`(R3 驱动运行期间不切分支)；审查清单 `p1-20260922/selection.json`，每条附审查理由与已知风险。

**初筛(只读，`screen.py`)**：候选池 2041 道(09-18 只读短候选，每应用最多 600)，按排除清单 `exclude-20260922.json` 去掉 15 道(P2 已用 4、09-18 pilot 4、09-18 细审未选 7，每条附原因)，筛 2030 道，1014 道过机械闸：Calc 286、Writer 374、Impress 202、VS Code 152。淘汰原因(可重叠)：评分不读单一约定产物 622(426 为 VS Code 无参 `verify_task()` 读固定配置位置，不适配本次夹具方法，不代表评分有缺陷)、setup 实际打开的应用与标签不符 401(候选池标签有误，如标 Calc 的终端截图、PDF 高亮、Vim 设置题)、评分前 postconfig 自动 Ctrl+S 与 config 需额外 open 步骤各 251(与"模型须自己保存"的协议不一致，适配器也不执行这些步骤)、setup 不生成被评文件 85、计分项少于 2 个 21、评分有副作用 15。

**人工审查评分(对称条款：评分只能要求指令说过的)**：淘汰 `30715c1e`(`'C2' in sqref` 子串匹配，与 09-18 E2 假阳性同类，且要求指令未提的错误提示)、`f742d285`(只认 SUMIF 与 'Project Code' 表头)、`b7df3500`(公式须逐字为 `…*100`，常见的百分比格式写法判错)、`23502e40`(LibreOffice 可能把"允许所有值"存成一条验证记录)、`e86ef99b`(分列最自然的做法会覆盖原列；前导 0 邮编)、`7c421304`(读公式文本而非值，公式生成学号的正确做法判 0)。

**四态夹具(`fixtures.py` + `check_local.py`)**：在每题 setup 自己生成的文件上造初始/典型错误/部分完成/正确完成四态，用未改动的 `verify_task` 评分，要求 0 / <1 / (0,1) / 1。首轮 11/12 通过；`a1243b01` 失败是我的夹具标签错(复制未剪切=做了一半应得 0.7，粘贴错一行=错误应得 0)，对调后通过。

**VM 往返检查(`check_vm.py` + `guest_check.py`，osworld-windows，与 workstation 同一 v2026.06.24 镜像、字节数一致)**：每题重置 VM、在真实 VM 里跑原 setup、要求初始分 0、截图，再把四态文件经 VM 自带 LibreOffice 另存一遍后重评。**查出两道在真实环境不可能得分的题**：
- `f6296ab4`(电话号码格式)：LibreOffice 把 `(000) 000-0000` 存成 `\(000") "000\-0000`，评分逐字比较 → 正确解存盘后 0 分。
- `f6c790b0`(标题下划线)：评分用 `shape.name.startswith('Title')` 找标题，LibreOffice 存 pptx 时给占位符改名 → 任何存过盘的文件都找不到标题，0 分。
替补 `f34a4410`(VLOOKUP；已知风险：查找区域写成含表头的 F1:G11 只得 0.7)与 `aed6f1eb`(全部文字居中；遍历形状不依赖名字)。`d41ae560` 同样按形状名找正文框，保留为备选但标注此风险。

**最终 12 道**：Calc `e31f36af` 月度 SUM 合计 · `86bc4aea` 合并居中 · `f34a4410` VLOOKUP；Writer `de0be554` 插 3×4 表 · `c440c03f` 项目符号列表 · `dc185455` Heading 3；Impress `e2b1a84c` 去掉第 1、3 条项目符号 · `4cd0f3c6` 9 张标题 32pt/加粗/深绿 · `aed6f1eb` 全部居中；VS Code `73e6b00f` 行排序 · `38cb2821` temp→temperature · `a1243b01` 剪切粘贴行。本地四态 12/12 通过；VM 往返 12/12 通过(`vm-20260922c`：真实 VM 初始分全为 0，Office 题往返前后四态得分逐项相同)。

**VM 检查自身的 bug(看截图发现，已修)**：`DesktopEnv.reset()` 只在 `step()` 把环境标为已用后才还原快照，而本检查只走 HTTP 执行接口，`vm-20260922b/c` 的 12 题实际在同一台未还原的 VM 里依次运行——Impress 截图里桌面留着 VS Code 题的 `todo.txt`/`names.txt`，并被上一道 Calc 题留下的"LibreOffice 文档恢复"对话框挡住(guest_check 结束应用时触发)。得分不受影响：各题产物路径不同，往返用独立的 LibreOffice 配置目录；但"setup 后应用可见"的截图证据被污染。修复 `af10fad`：每题前把环境标为已用以强制还原，并断言上一题的上传目录已消失；以 `vm-20260922d` 重跑：**12/12 通过**，每题前还原与断言均生效，四态与往返得分与 c 轮逐项相同；抽看 Impress/Calc/Writer 截图，应用正常打开题目文件、无上题残留。09-18 的 P0 检查调用过 `step()`，其 reset 是真实还原。

**P1 部署(workstation，未采样)**：`stage_panel.py` 在共享 harness 上建独立 worktree `p1-panel-20260922/harness`(d552441，与 P2 相同方式)，为 12 题生成 bundle 与适配器；适配器模板由 P2 适配器抽出，代入 P2 Calc 题参数时与 09-18 实际文件逐字节相同。`make_registry.py` 由已验证的 P2 registry 派生 `cua-eval/registry.cuagym-p1-r5.json`，模型为 π0，协议与 P2 逐项相同。采样在 R3 结束、workstation VM 空出后启动。

**按"可复用、不写死"重构(用户 09-22 要求，已记入 memory)**：screen 读排除清单；夹具按完整任务 ID 登记；check_local/check_vm 从 selection.json 取题；summarize/export/probe 不再写死 4 轮/16 回合/{1,2,3,4}；`publish_pi1.py` 改为通用 `publish_policy.py`。回归：screen 2030 题逐条记录与重构前相同；summarize 对 09-18 P2 数据 `summary.json` 逐字节相同；export 对 09-18 数据重导 `batch.jsonl` SHA 仍为 `7b7cd304…`；check_local 对沿用的 10 题四态得分与重构前逐项相同。

## 2026-09-22：第二轮(iter2)执行记录

用户 09-22 批准 R1–R6 与代码改动 `547c09b`，并要求 RL 文档迁入 CUA(本文件即迁移后的位置，原顶层文件留指路桩)。

- **R1 π1 发布完成(15:4x PT)**：`/gscratch/cse/jy050706/sft/serving/9b-full-r5-grpoprobe--train20260918--s1/model`，17 个文件经 `checkpoint_files()` 校验。与 π0 服务目录逐文件对比：4 个权重分片与 trainer_state/INIT_MANIFEST 不同，其余 11 个推理文件完全相同；生成的 serve-r0.sh 与 π0 的只差模型 ID 与端口。
- **R2 π1 服务就绪(15:52 启动，约 3 分钟加载)**：step `40253896.50`，g3108 GPU3(`GPU-f9a6682f…`，启动闸门时占用 1MiB)，端口 8083；`prepare_model.probe_service` 标准检查 ready：服务名、root、上下文 65536、attention 采集路由均通过。启动记录 `allocation-40253896/launch-explicit-gpu.json`。workstation 已按 registry 的 connect_once 建立 8183→g3108:8083 转发。
- **R3 四轮采样已启动(15:56 PT)**：`run_rounds.sh`，产物 `cua-rl-local/artifacts/iter2-pi1-20260922/`。
  - **驱动 bug(已修)**：状态判断表达式含生成器表达式，而 `field()` 用 `eval(expr, {}, {"d": d})`，生成器看不到 eval 的 locals，16:01 第一次查状态即 `NameError` 退出；后台通知显示退出码 0，是管道末端 `tee` 的退出码掩盖了失败。第 1 轮 controller 在 workstation 独立运行、不受影响；第 2–4 轮未启动。修复 `4d889a0`：`d` 放入 globals，并支持续跑(沿用已冻结的 plans.json；已有 start-N.json 的轮次只等待、不重复启动)；在真实 plans/status 文件上实测表达式后，以 `pipefail` 重启(16:1x)。
  - **驱动第二个 bug(已修，`75e4018`)**：第 2 轮 4 题 16:32 全部评分时，其 controller 仍在做轨迹页面后处理并持有主机 worker 锁；驱动只看题目计数即启动第 3 轮，第 3 轮 worker 取锁失败(`BlockingIOError`)，run 状态 `blocked`、4 题 pending；旧判断只看计数而一直等待(约 35 分钟无进展，17:05 查出)。修复：一轮完成须"全部评分且 controller 已退出"；`blocked` 且 controller 已退出即判失败；进入每轮统一用幂等的 `run_eval resume`(不重复启动活着的 controller、跳过已完成、重启未开工的 run)；先查状态再 sleep。以 16:32 等真实快照在 bash 下验证后重启(17:07)：第 1、2 轮即刻判完成，第 3 轮经 resume 以新 controller 运行。
  - 第 1 轮 Calc(16:01 完成，0 分)的采集按 export_batch 的断言逐项检查：初始分 0、评分进程 rc 0、11 次决策无采集错误、token 与 logprob 数量一致、图像 SHA 全对、策略版本为 π1 服务路径、thinking/preserve_thinking 开。
- Klone 训练目录 `/gscratch/cse/jy050706/sft/experiments/cua-rl-probe-20260922/` 已放入 iter2 的 probe/verify/run/verify.sh 与上游 ppo_utils，文件 SHA 与本地一致。
- **R3 完成(17:42 PT)**：4 轮 × 4 题 = 16/16 回合全部评分，failed/blocked/interrupted 均为 0。π1 得分(轮 1–4)与 09-18 π0 同协议对比：

  | 题 | π0(09-18) | π1(09-22) |
  |---|---|---|
  | Calc `693b3046` | 0,0,0,0 | 0,0,0,0 |
  | Writer `f02c7f7f` | 0,1,1,1 | 0,0,0,1 |
  | Impress `2ecc76ab` | 1,1,1,0 | 0,1,0,1 |
  | VS Code `d46f3728` | 1,0.4,1,0.4 | 1,1,1,1 |
  | 完全做对 | 8/16 | 7/16 |
  | 平均分 | 0.55 | 0.44 |

  **纠错(09-22 23:59)**：此表最初把 π0 的 VS Code 写成 1,1,1,1，合计写成 10/16，是凭记忆写的，没有查 `p2-grouped-20260918/summary.json`；按原始文件更正如上。每题只有 4 个样本，8/16 与 7/16 没有差别(双侧 Fisher 精确检验 p=1.0)，**不能据此判断 update1 让模型变差或变好**；这一步验证的是链路。另外，这 4 题中有 3 题后来被重叠审计排除(见上方审计一节)。
- **R4 完成(17:43)**：`stage_batch.sh` 汇总 → workstation 导出 → 传 Klone。有奖励差异的组 2 个(Writer、Impress)，8 条轨迹、85 次决策、82 张不重复截图、最长序列 26386 token；采集的策略版本全部是 π1 服务路径。`batch.jsonl` SHA256 `185fb0ee…`，Klone 端 SHA 与图片数(82)核对一致。
- **R5 完成(17:44–18:13，退出码 0)**：`klone_step.sh` 起 step，GPU7(启动前占用 1MiB、无进程)，`--mem=320G`；日志 `$B/update2.log`，启动记录 `$B/update2-launch.json`。
  - 恢复断言全部通过：step1 checkpoint 的 global_steps=1、Adam 步数 [1]、二阶矩非零、模块权重与 π1 服务权重一致；保存后 global_steps=2，resume checkpoint 在 g3108 `/tmp/jy050706-cua-rl-probe-20260918/update2-resume`(节点本地盘)。
  - batch SHA `185fb0ee…` 与导出一致，85 次决策全部参与，采样策略为 π1(on-policy 断言通过)。85 个 turn 上，不带梯度的旧策略重算与带梯度前向逐 token 差值全部为 0(同一权重上两次前向一致，重要性比值恰为 1)。
  - 梯度范数 3.09(update1 为 4.55)；被监控参数的前 16384 个值中有 127 个改变(update1 为 146)，最大改变量 1.9e-6；耗时 1247 秒(update1 为 33 次决策、595 秒)。
  - `logprob_alignment_passed=false` 与 update1 相同：vLLM 采样记下的 logprob 与 HF 训练侧重算的有差异，这正是旧策略改由训练侧重算的原因。本次差异比 update1 小：两次抽查决策的平均绝对差约 0.019，最大 0.55(update1 为 0.82)，超出裁剪范围的比例 0.49%(update1 为 1.8%)。
  - **风险**：显存峰值 45.9GB(L40S 47.7GB，与 update1 相同)；最后一个 turn 出现一次 expandable_segments 映射 OOM 警告，分配器自动恢复。batch 最长序列 26386 token；序列更长的 batch 可能真正 OOM。
- **R6 校验通过(18:14–18:2x，退出码 0，GPU7)**：`verify.sh update2` 以 π1 为基准比较新保存的权重：global_step=2；760 个张量中抽查的 3 个语言张量均有改变(34/4096、228/16384、238/16384，最大改变量 1.9e-6)；333 个视觉张量与 π1 完全相同(视觉冻结生效)；重新加载后的多模态前向生成 308 个 token，logprob 全部有限。**π2 = `$B/update2/model`**(推理权重 18.8GB，4 个分片 SHA 记于 `cua-rl-local/artifacts/iter2-update2-20260922/pi2-weights.sha256`)；续训用的 DeepSpeed checkpoint 在 g3108 本地盘 `/tmp/jy050706-cua-rl-probe-20260918/update2-resume`，随 allocation 于 09-25 06:02 消失。R5/R6 的报告、启动记录与过滤后的日志已拉回本地仓库。**P0(发布 π1 → π1 采样 → 从 step1 续训 → π2 → 校验)全部完成。**
- **P1 π0 第一次启动失败(17:44–17:49，已修，数据未污染)**：第 1 轮 12 题各试 2 次，全部在 VM 启动前以 `FileNotFoundError` 退出，找不到镜像 `<harness>/docker_vm_data/osworld-v2-ubuntu-x86-official-fonts.qcow2`；驱动按设计判为基础设施失败，停在第 1 轮(证据 `artifacts/p1-pi0-20260922/`，`fd601a1`)。
  - **根因**：harness 按 `.env` 里的 `OSWORLD_DOCKER_UBUNTU_VM_PATH` 找镜像，没有这个变量就去读 cwd 下的 `./docker_vm_data`。共享仓库把 `.env`(镜像路径、文件服务地址、VM 口令、API key 等)和 `.venv` 作为未跟踪文件保存。09-18 部署 P2 时在 worktree 里**手工**建了这两个指向 `OSWorld-V2-shared` 的符号链接(13:36)；今天的 `stage_panel.py` 只复现了 worktree 和适配器，没有建这两个链接。`run_eval doctor` 不检查这一项，所以报了 ready。
  - **处理**：在 P1 harness 建与 P2 相同的两个链接(运维配置，未改代码)。harness 自带的 `local_eval/check_environment.py` 检查通过：Python 3.12.3、依赖无差异、docker 镜像一致；镜像路径解析到与 P2 同一个文件(v2026.06.24 official-fonts，27471970304 字节)。失败 run 的 2 次尝试已用满，`resume` 不会重跑，故在新目录 `artifacts/p1-pi0-20260922b/` 重新冻结 4 份 plan，17:51 重启。17:52 VM 启动，17:53 π0 返回第 1 步动作。
  - **代码修复(用户批准，`1ed2d1f`)**：`stage_panel.py` 建完 worktree 后链接 `.env`/`.venv`，并运行 harness 自带检查(`--hash-vm` 核对镜像 SHA)，报告写入 `<run>/environment-check.json`，让以后的面板在部署时就发现这类问题。实测(workstation，与 P1 部署同参数，写入临时目录，测后删除)：两个链接建好，环境检查通过，镜像 SHA `57c4cef4…` 与 runtime lock 一致；bundle、panel.json 与 P1 面板逐字节相同，适配器相同(运行中的面板只多出 `__pycache__`)，deployment/registry 替换目录路径后相同；耗时 71 秒。反向对照：去掉 `.env` 后检查以 rc=1 退出(`KeyError`)。证据在 `artifacts/stage-panel-test-20260922/`。`run_eval doctor` 不改：它是所有 eval 共用的工具，并非每个 harness 都用 `.env`。
- **汇总脚本回归测试**：改过的 `iter2-20260922/summarize.py` 对 09-18 的 5 份 P2 plan 重新汇总，`summary.json` 与当时证据逐字节相同，`episodes.json` 16 条记录完全一致(09-18 生成 episodes 的那一步当时没有留下脚本，现已由 summarize 复现)。

### R3 之后的命令(已准备并验证，按序执行；`cua-rl-local` 为工作目录)

脚本均在 `iter2-20260922/`(提交 `f929530`)：`stage_batch.sh` 已用 09-18 数据端到端回归(batch SHA `7b7cd304…`)；`klone_step.sh` 已实测起 step；`run_rounds.sh` 已参数化。R5 预检：GPU7 空闲无进程、step1 checkpoint(119G)在、g3108 `/tmp` 余 2.7T、`/mmfs1` 余 242G。

1. R4 导出并传到 Klone：`bash iter2-20260922/stage_batch.sh ../cua-eval/registry.cuagym-p2-grpoprobe-s1.json workstation artifacts/iter2-pi1-20260922 artifacts/p2-grouped-20260918/deployment.json /home/yanji/research/cua-rl-local/iter2-export-20260922 hyak /gscratch/cse/jy050706/sft/experiments/cua-rl-probe-20260922`
2. R5(在 Klone 登录节点)：`bash $B/klone_step.sh 40253896 $B/update2-launch.json $B/update2.log 320G 01:45:00 -- bash $B/run.sh update2 GPU-6ac74522-c2af-8176-0831-8ef8970817e2 $P1 --update --recompute-old-policy --loss-source $B/ppo_utils.py --policy-version $P1 --resume-from /tmp/jy050706-cua-rl-probe-20260918/update1-resume --resume-tag step1 --save-tag step2 --resume-output /tmp/jy050706-cua-rl-probe-20260918/update2-resume`，其中 `B=/gscratch/cse/jy050706/sft/experiments/cua-rl-probe-20260922`、`P1=/gscratch/cse/jy050706/sft/serving/9b-full-r5-grpoprobe--train20260918--s1/model`。
3. R6：`bash $B/klone_step.sh 40253896 $B/verify-update2-launch.json $B/verify-update2.log 64G 00:20:00 -- bash $B/verify.sh update2 GPU-6ac74522-c2af-8176-0831-8ef8970817e2`
4. P1 π0 采样(与 R5 并行，workstation 单 VM：π0 服务并发容量 1，`run_eval` 要求 VM 数 ≤ 容量，约 3 小时)：`bash iter2-20260922/run_rounds.sh ../cua-eval/registry.cuagym-p1-r5.json 9b-full-r5--train20260822--s306 cuagym-p1 workstation cuagym-p1-12task-pi0 artifacts/p1-pi0-20260922 4`(实际运行目录为 `artifacts/p1-pi0-20260922b`，见上方"P1 π0 第一次启动失败")

### 准备与核查(批准前)

以下为批准前的准备记录。当时远端写操作(Klone 共享盘写入、起服务、VM 采样)被 Claude Code 权限分类器按"修改共享资源"拦下，停下等用户批准，没有绕过。

**现场核查(15:20–15:45 PT)**：9/18 15:42 之后 workstation、Klone、Mac 均无新 RL 产物。allocation 40253896(g3108，8×L40S)有效期 2026-09-18 06:02 → **2026-09-25 06:02 PT**；node-local 的 step1 DeepSpeed checkpoint(119G，含 optimizer 状态)随之消失，g3108 `/tmp` 仍有 2.7T 空闲。π0 服务(step .6，GPU6，端口 8082)仍在，4 天无请求。g3108 各卡：0/1/2/4 为用户的 molmospaces 数据生成(step .47，overlap 持有全部 8 卡与 16 CPU)，5 状态异常(nvidia-smi 显示 [N/A])，6 为 π0，**3 与 7 空闲**。本作业内存上限 512GiB、当前 29.6GiB；节点 `free` 显示的 374G 已用主要属于他人作业 40434900(660G)，不占本作业额度。workstation 空闲(无 VM、无评测进程)，到 Klone 的 SSH master 在线。

**主 benchmark**：用户 09-22 确认 **OSWorld-Verified**(官方 361 题)；设计文档已同步。

**版本管理(09-22 起)**：
- `cua-rl-local/` 建为本地 git 仓库(无远端)。基线 `bb11eca` = 09-18 探针代码与证据；probe.py/verify.py/run.sh 与 Klone 实际运行副本 SHA256 一致(probe `16df8722…`)。上游 checkout 的 commit 与所用损失函数文件(OpenWebRL `9da6dc1` `slime/utils/ppo_utils.py`，`42a60d08…`)记在 `SOURCES.json`。凭据、虚拟环境、wheel、上游源码、下载数据不入库。
- 今天的代码在 `iter2` 分支：`eedb206` 发布与服务包装 → `6483aff` 原样复制 09-18 脚本 → `547c09b` 改动提案(**未运行**)。验证通过再合回 main。
- CUA 仓库此前自 09-14 目录整理起累积 500+ 文件未提交，已作快照提交 `04ea21395f`(分支 `reorg-20260909`，未推送)。

**π1 发布方案(脚本已写好，未执行)**：模型 ID `9b-full-r5-grpoprobe--train20260918--s1`，arm `9b-full-r5-grpoprobe`(临时登记见 `CUA/docs/NAMING.md`)。逐文件比对 update1/model 与 π0 服务目录：
- 权重索引、tokenizer.json、chat_template.jinja、generation_config 逐字节一致；
- config.json 只差 π0 多一行 `use_cache:false`；tokenizer_config 只差加载开关 `local_files_only`；
- processor_config 的图像尺寸上下限被 probe 在保存前改写(推理时由 `--mm-processor-kwargs` 覆盖)；
- update1 缺 preprocessor_config、video_preprocessor_config、vocab、merges 四个文件。

因此 **π1 只换权重**：4 个分片与索引硬链接自 update1(共享盘 /mmfs1 已用 99%、余 260G，硬链接不占新空间)，其余 12 个推理文件逐字节复制自 π0 服务目录，用现有 `prepare_model.checkpoint_files()` 校验。采集代码三文件 SHA 与 π0 部署时一致。registry：`cua-eval/registry.cuagym-p2-grpoprobe-s1.json`，与 09-18 P2 版本只差模型条目和端口(8183→g3108:8083)。

**Slurm GPU 分配(实测，debug)**：在 40253896 中申请 1 卡的 overlap step，两次测试都被分到正在服务的 GPU6，现成的 `prepare_model serve-held` 会因"GPU 忙"断言拒绝启动(安全失败，但起不来)。办法沿用 09-18 训练：step 申请 8 卡可见，由 `serve_on_gpu.sh` 显式绑定已验证空闲的 UUID；vLLM 命令仍由 `prepare_model.serving_script()` 生成，参数与 π0 完全一致。同时发现 09-18 `run.sh` 的空闲闸门(<1024MiB)会放行 molmospaces 占 719MiB 的 GPU0，新版收紧为 <512MiB 且无计算进程。

**恢复训练的内存核算**：update1 是从零建 optimizer；resume 时 `torch.load` 约 107GB optimizer 状态，叠加已分配的 CPU Adam 状态(约 143GB)，峰值估计约 250GB，故训练 step 申请 `--mem=320G`(update1 为 192G)。超限只会杀掉训练 step 本身。

**待批准的远端操作(按顺序)**，均使用已持有的 allocation 和 workstation，不申请新 GPU：
1. R1 在 Klone 发布 π1(`iter2-20260922/publish_pi1.py`)。
2. R2 在 g3108 GPU3 启动 π1 服务(8083；workstation 本地 8183)。
3. R3 四轮采样(`run_rounds.sh`；与 09-18 P2 同协议：同 4 题、30 步、T0.8、单 VM 串行、collection=test、原始记录保留；约 70 分钟)。
4. R4 汇总并导出有差异的组，传到 Klone。
5. R5 在 GPU7 上从 step1 恢复并更新一步(global_step 1→2)。
6. R6 校验(权重变化、视觉冻结、重新加载 forward)。

训练参数表与代码 diff 见 `cua-rl-local` 的 `547c09b`。

## 2026-09-18：GRPO单步更新、落盘及独立重载已验证

本次完成的是**一次真实optimizer update的资格测试**，不是持续online RL或效果实验。使用原普通r5-9B SFT初始化，独立HF/DeepSpeed后端，复用未修改的OpenWebRL clipped policy loss；未声称跑通原生OpenWebRL/Megatron整套调度。

| 检查 | 最终结果 |
|---|---|
| 导出并核对输入 | 3个完整group、12条轨迹、127次决策；全部prompt token及图像网格匹配 |
| 实际训练batch | Writer一个完整group，reward为0/1/1/1，4条轨迹、33次决策，每轨迹等权 |
| 更新设置 | 语言全参、视觉冻结；lr5e-7，clip0.2，temperature0.8，ZeRO2 CPU optimizer offload，单L40S |
| old-policy路径 | 训练侧重算，上游use_rollout_logprobs=False语义；33次更新前old/new logprob最大差0 |
| backward / update | 33/33通过；global_step=1，梯度范数4.551735，进程exit0 |
| 训练部分耗时 / 显存 | 595.1秒，不含初始化与保存；peak reserved42.789GiB |
| 落盘模型 | 4个safetensors分片，760个tensor，18,839,793,446 bytes含配置/验证元数据 |
| 独立语言权重核对 | 抽查36,864值，593值改变；最大差9.536743e-7 |
| 冻结视觉核对 | 333个visual tensor全部与原SFT逐元素完全相同 |
| 独立重新加载 | 新进程加载新checkpoint，真实截图forward通过，382个输出token logprob全部有限；exit0 |

- 推理权重：Klone `/gscratch/cse/jy050706/sft/experiments/cua-rl-probe-20260918/update1/model`。原始SFT权重及其GPU6服务保留。
- 完整DeepSpeed checkpoint：g3108 `/tmp/jy050706-cua-rl-probe-20260918/update1-resume/step1`。这是节点临时盘；只验证了文件和optimizer分片存在，**尚未执行resume，也未持久化到长期存储**。
- 同一份采样记录可供资格测试，但跨vLLM/HF数值差异和sampling/importance-weight口径仍未完全验收。训练侧重算使本次update的分母自洽，不代表它消除了跨后端误差。不能据单步结果宣称RL效果提升。
- 本轮没有运行新权重的VM rollout、自动权重同步或第二轮更新。下一步先把独立新checkpoint接入已有serving/eval入口并跑小组VM验证，再测试checkpoint恢复与第二轮采样/更新；正式任务池、holdout及长期存储仍待落实。

证据：[单步训练报告](../../cua-rl-local/train-probe-20260918/results/update1-report.json)、[独立权重与重载验证](../../cua-rl-local/train-probe-20260918/results/update1-verification.json)、[概率口径核对](../../cua-rl-local/train-probe-20260918/probability-contract.json)、[最终资源状态](../../cua-rl-local/train-probe-20260918/results/final-resources.json)。

### 本轮接入与排错记录

- 用户授权继续最小训练闭环。原OpenWebRL Qwen3.5 bridge及其链接launcher存在语言模型路径，不能未经验证直接当作截图多模态训练。先复用已有 `sft-train.sif` 的HF Qwen3.5完整多模态实现和DeepSpeed，以未改的OpenWebRL clipped policy loss做隔离资格检查；不是宣称OpenWebRL在线训练已集成。
- 已实时确认A100四卡正在其他训练，不使用；L40S占位40253896有空闲卡，原SFT服务step6保留。容器版本实查：torch2.13.0+cu130、transformers5.15.0、deepspeed0.19.5、trl0.29.1，sglang未安装。
- 已导出3个有奖励方差的完整group：12条轨迹、127次决策、125张唯一图片，最大总长度27,609。使用精确capture请求、图像SHA、输入输出token IDs、rollout logprob、loss mask、trajectory turn count和原奖励。没有把缺失记录补成0或丢弃同组失败轨迹。
- 本地独立脚本：`cua-rl-local/train-probe-20260918/`。远端独立目录：`/gscratch/cse/jy050706/sft/experiments/cua-rl-probe-20260918/`。先运行preflight1：全部输入重建匹配，再做同checkpoint logprob检查；不满足门槛则不允许optimizer step。该阶段后来通过训练侧old-policy重算完成一次更新，最终结果见本节顶部。
- preflight实际结果：127次prompt token与图像网格全部匹配；修复了本地拼接response后mm_token_type_ids未补齐的错误。原始vLLM与HF整段forward的两条logprob检查平均绝对差0.02709/0.01159、最大0.81962/0.22776；原始rollout-logprob直接使用路径未通过预设门槛，未放宽阈值。
- 全部183次决策、39,083个API logprob与采集器的temperature前raw logprob逐项相同（最大差0）；采样temperature0.8、top_p0.95。上游 `slime/backends/megatron_utils/loss.py` 的get_responses会除temperature，因此不能将这些raw值直接作为该路径的old logprob。
- 最小替代路径采用上游已支持的 `use_rollout_logprobs=False` 语义：在同一训练后端、同一temperature0.8下重算old policy，并在每次backward前验证未更新策略的比值约为1。保留原rollout logprob用于差异诊断，不宣称已经解决跨后端或采样分布差异。独立update1只使用Writer的完整四轨迹group、33次决策；语言全参、视觉冻结、lr5e-7、clip0.2、每轨迹等权，一次optimizer step。
- GPU使用：Slurm单卡overlap首次选中了正在serve的GPU6，被内存门槛拒绝；后续在同一个已有八卡allocation内显式只绑定空闲GPU0 UUID `GPU-4a7aa295-575f-7902-743b-1d6d2db6b8c1`，未停原GPU6服务。共享盘实查仅余约183GiB，完整optimizer checkpoint写入节点本地 `/tmp/jy050706-cua-rl-probe-20260918/`（非长期持久存储）；独立HF权重才写共享盘。训练入口限制40分钟。


## 2026-09-18：四任务 × 四轮真实采样已完成（未做训练）

最终完成 **16/16条有效模型轨迹**，冻结普通r5-9B checkpoint-306。完整成功8条、部分完成2条、0分6条；这是四个工程测试任务的重复采样，不是OSWorld benchmark成绩。

| 应用 | 第1轮 | 第2轮 | 第3轮 | 第4轮 | 组内奖励差异 |
|---|---:|---:|---:|---:|---|
| Calc | 0 | 0 | 0 | 0 | 无，advantage全0 |
| Writer | 0 | 1 | 1 | 1 | 有 |
| Impress | 1 | 1 | 1 | 0 | 有 |
| VS Code | 1 | 0.4 | 1 | 0.4 | 有 |

- 3/4组、12条轨迹具有非零组内奖励方差，可用于训练链路验收。Binary与Partial都只有这三组有效：Writer/Impress的advantage完全相同；VS Code两档分数经标准化后最大差约1e-6，仅来自epsilon。这批数据不能检验部分分是否优于二值奖励。
- 16次初始评分均为0；16次原grader均正常退出，未把初始化/服务异常算成模型0分。VS Code两条0.4均为删除了第14行的内容、保留空行，文件仍20行；未完整删除该行。Calc四条的磁盘文件缩放仍100/100；Impress最后一条磁盘顺序仍为初始顺序，未事后补操作或修分。
- 共183次模型决策、202条动作记录（一次回复可以包含多个动作）、39,083个输出token，其中24,243个reasoning token。每次token IDs与logprob数量一致，capture_errors为空；16页全部验证passed，183次信号决策已验证，388张图像解码通过。这不等于训练prompt/mask已经验收。
- 第四轮中本地轮询出现一次STATUS_FAILED并退出；重新查询确认远端controller独立完成该轮，未重复启动或重跑。最终全部controller结束、运行Docker容器数0。释放可回收文件缓存后WSL available为54,606 MiB；未重启WSL或停止其他服务。 随后Windows vmmemWSL working set为4,193,746,944 bytes（约3.91 GiB）；原单L40S模型服务8182健康检查HTTP200，保留供下一步使用，未做新GPU申请。
- 五个原始源码checkout、workstation共享harness及本轮独立worktree均git status clean。私有任务适配文件被harness任务数据规则忽略；未修改原task/setup/grader、共享VM镜像或模型权重。
- **下一步只验收一次GRPO更新**：从这三组构造逐决策训练样本，核对原prompt/image/token映射、生成token的loss mask与old logprob；接入现有训练后端，先做forward/loss/gradient检查，再做一次optimizer step并保存独立checkpoint，验证权重同步后用同协议小规模回测。当前未构建训练batch、未backward、未更新权重，SFT基线保留。Binary/Partial比较需另收更多reward档位或binary全失败但partial有差异的组。

证据：[奖励与优势](../../cua-rl-local/artifacts/p2-grouped-20260918/summary.json)、[原始评分与采集验收](../../cua-rl-local/artifacts/p2-grouped-20260918/final-audit.json)、[运行状态](../../cua-rl-local/artifacts/p2-grouped-20260918/final-statuses.json)、[16页索引](../../cua-rl-local/artifacts/p2-grouped-20260918/viewer-entries.json)、[内存清理](../../cua-rl-local/artifacts/p2-grouped-20260918/memory-cleanup.json)。页面已进入[统一查看器test集合](http://127.0.0.1:8793/index.html?collection=test)。

### 本次执行与依赖修复记录

用户再次要求推进下一步，现已执行，不只停留在计划。对公开数据做只读 grader 初筛，排除发现的自动保存副作用，再选出以下四题；保留原始 instruction/setup/reward，不改分、不自动补保存。

| 应用 / task id | 任务 | 有限 fixture 检查：初始 / 错误 / 部分 / 完成 |
|---|---|---|
| Calc `693b3046…` | Sheet1缩放85%、Sheet2缩放110% | 0 / 0 / 0.5 / 1 |
| Writer `f02c7f7f…` | 只将第二段设为双倍行距 | 0 / 0 / 0.6 / 1 |
| Impress `2ecc76ab…` | 将第5张幻灯片移到第2位 | 0 / 0 / 0.4 / 1 |
| VS Code `d46f3728…` | 删除 script.sh 的第14行 | 0 / 0.4 / 0.4 / 1 |

这是有限的典型正负例验收，不保证对所有投机解免疫。VS Code 的错误删除可能获得部分分，不能把非零分数当完整成功。每条真实 rollout 初始化时仍检查原 grader 的分数必须为0。

- 当前模型仍为同一普通 r5-9B checkpoint-306，固定BF16服务；未更新模型权重、未增加GPU实例，workstation单VM串行采样。
- 四轮各包含这四题，共16条；使用统一 `run_eval.py plan/doctor/run/status`，collection=test、原始记录保留。自动顺序推进已冻结的四份plan，出现环境/服务错误则停止后续轮次；正常0分不会触发补救重跑。
- 每条最多30步，temperature0.8、top_p0.95、输出4096、context65536、10图/fold1，与上一轮一致。没有显式API seed，不称作四个预先指定随机种子的复现实验。
- 独立 worktree/bundles：`/home/yanji/research/cua-rl-local/p2-grouped-20260918/`；原始脚本哈希及上传一致性已记录。
- VM guest Python3.10缺 openpyxl/docx/pptx，通过任务进程专用的纯Python wheels路径补齐（另含et_xmlfile、typing_extensions、xlsxwriter）；复用guest已有lxml/Pillow。共享VM镜像、上游harness和主机Python环境未改。
- 首次执行：Calc第一条完成、score=0；Writer在模型调用前因python-docx默认模板不能从wheel zip路径打开而初始化失败；已停止该次controller及其拥有的进程/VM，保留失败证据，不计为模型0分。Impress未形成有效模型样本。
- 修复只涉及私有依赖目录：在一次性VM中解压同样的六个wheel，再通过进程级PYTHONPATH加载。原任务、grader、模型和共享镜像未改。Writer/Impress均已在真实VM上重新验证setup成功、初始reward=0；初始桌面渲染需要短暂等待，5秒后截图正常，沿用native runner现有的就绪等待。
- 修复后的独立worktree为 `p2-grouped-fixeddeps-20260918`。第一轮只补Writer/Impress/VSCode三题，保留已完成的Calc0分；其余三轮仍各四题，共计划16条有效模型轨迹。新的冻结plan及原失败plan都保留；未启动的旧plan不再使用。
- 修复后16条有效采样已全部完成，原失败记录保留。
- 按原始task id跨轮分组，未将不同题混作一个GRPO组，最终结果见本节顶部。

证据：[冻结plan及重复轮次映射](../../cua-rl-local/artifacts/p2-grouped-20260918/plans.json)、[reward检查](../../cua-rl-local/artifacts/p2-grouped-20260918/reward-checks.json)、[原部署哈希](../../cua-rl-local/artifacts/p2-grouped-20260918/deployment.json)、[依赖修复后的哈希](../../cua-rl-local/artifacts/p2-grouped-20260918/fixed-deployment.json)、[VM初始化复核](../../cua-rl-local/artifacts/p2-grouped-20260918/fixed-dependency-qualification.txt)。

## 下一阶段前的 reward 审查：发现一个已复现的假阳性

对已准备的四个任务只做源码审查和本地负例测试，没有启动新 VM、模型采样或训练，也没有修改原 evaluator。

| 任务 | 本次发现 | 证据等级 / 处理 |
|---|---|---|
| Calc / E2 自定义验证 | evaluator 用 `'E2' in sqref_str`；只给 E20 添加验证、E2 无任何验证，也会返回 1.0。另有未明确写入 instruction 的错误提示文字要求 | **负例已复现**，先隔离出首轮训练候选；原 rollout 的0分保持不变 |
| Writer / 四边页边框 | 只检查 `doc.sections[0]`；距离检查只看 `space`，未检查相对页面/正文的 `offsetFrom` | 静态风险，需多 section / 不同偏移基准的负例测试，暂不判验收通过 |
| Impress / 矩形 callout | 原 reward 执行入口会自行 `Ctrl+S`；形状检查仅要求 `AUTO_SHAPE`，没有核实矩形具体类型 | 已确认评分有保存副作用，形状边界为静态风险；不与无自动保存的任务混成同一个未说明的协议 |
| VS Code / Python 项目设置 | 解释器只接受 `${workspaceFolder}/.venv/bin/python` 字面值，另强制 unittest=false；JSONC 正则剥注释可能误处理字符串里的 `//` | 静态风险，先检查有效等价配置与初始化提供的信息，不当作已完全合格 |

Calc 负例证据：[calc-negative-control.json](../../cua-rl-local/artifacts/reward-audit-20260918/calc-negative-control.json)。正确 E2 和错误 E20 两个 fixture 都被原函数打成1.0；使用 openpyxl 的真实区域包含判断确认 E20 不覆盖 E2。

此前 P0 的 0/0.7/1 验证证明了评分链路能运作，**没有证明 reward 对错误解不会给高分**。这个新发现使 Calc 暂不具备训练准入资格，但不否定已完成的真实模型/VM接口验收。

下一步保持小预算：先换筛并验收4个评分边界明确的任务，每个4条独立 rollout，共16条；只有采样组有有效奖励差异，才进行一次 GRPO update。每条从干净状态开始，固定同一9B checkpoint；不人工补操作、不事后修分。候选任务应通过初始态、正确态、典型错误态三类检查，且明确 grader 是否会自动保存/修改状态。此处是下一步计划，尚未启动16条采样。

## 2026-09-18：普通 r5-9B 的真实 Calc rollout 已完成，原始得分 0

- 用户要求“下一步”。已通过现有 `tillicum2` SSH master 找到原始普通 r5 checkpoint：`/gpfs/scrubbed/jy050706/sft/out/img10-9b/v0-20260822-024940/checkpoint-306`，`global_step=306`、epoch=3、full SFT，源模型 Qwen3.5-9B，数据为两份 r5nocapimg10 语料，视觉塔/aligner 冻结。不是 histcomp、TMAX 或其他 mixB 版本。
- 使用现有 `prepare_model.py plan` 验证分片/index/完整视觉权重，传输并逐文件校验 17 个推理文件，共 18,849,985,312 bytes；不传 optimizer/RNG。发布到 Klone `/gscratch/cse/jy050706/sft/serving/9b-full-r5--train20260822--s306/model`。
- 用原有 `prepare_model.py serve-held` 在已拥有且空闲的 `40253896` allocation 中启动 **1 张 L40S**，节点 g3108、step `40253896.6`、GPU `GPU-f0492b40-1501-0682-cb93-02957e80e98f`、端口8082；没有新建长期 GPU allocation，也没有停止其他服务。workstation 本地新转发8182。
- 服务 BF16、context65,536、单并发、image limit10；按已有采集工具保存输出与视觉信号。SFT 工具名 `computer_use` 和相对坐标约定已核对。
- 独立 worktree：`/home/yanji/research/cua-rl-local/p1-calc-20260918/harness`，commit d552441。新增一个被任务数据规则忽略的 BaseTask adapter；原始任务、setup、reward 与共享 harness 均未修改。task adapter 仅初始化和评分，无脚本解法。
- 统一入口已执行 `run_eval.py plan → doctor → run`，collection=`test`、raw_retention=`keep`，workstation1 slot；doctor 全部通过，包括精确 checkpoint/model ID 与大响应连接检查。
- Run：`9b-full-r5--train20260822--s306--cuagym-p1--cuagym-calc-p1-n1--20260918T194352Z-97a467585548`。最多30步，temperature0.8/top_p0.95，max output4096，image10/fold1，thinking/preserve_thinking 开启。
- **最终结果：1/1 任务完成，native exit=0，原始 reward=0.0；模型9次决策（8次GUI操作＋DONE），没有超时或执行异常。controller 已完成、该任务VM已清理，未做 RL 参数更新。**
- 截图确认第7步在 E2 的 Custom 验证框输入 `=E2>D2`，第8步点 OK，第9步模型宣称成功并 terminate。轨迹没有保存动作；原 evaluator 读取磁盘文件后，三个组件均报告未发现验证规则。证据最支持漏保存，但没有事后补保存来重打分，不能把这一推断写成已做反事实验证。
- 采集9/9决策，输出 token IDs/logprob 共1,059项、每轮数量相等，其中 reasoning342 tokens；capture_errors 为空。页面验证 passed：9 decisions、9 actions、18 decoded images、9 verified signal decisions，无 errors/warnings。
- 页面已进入现有统一 viewer 的 **test** 集合：[真实轨迹](http://127.0.0.1:8793/sources/workstation-eval/task-fb53c63253de4eac9c958a95688ed944.html#episode=0)。
- **reward 数据审计待办**：原评分第三项额外检查非空错误提示文字，而 instruction 未明确要求该文字；先作为一致性疑点，不改本轮原始成绩、不直接把该任务标为训练资格全部通过。
- 已验证的是固定9B SFT的真实 rollout与记录链路。仍缺一组同任务多轨迹的奖励差异、OpenWebRL训练样本/mask构建、backward与权重同步；不是GRPO训练已跑通。
- 收尾：workstation 已无运行 Docker VM；清理本次文件缓存后 WSL 可用约53.2 GiB。只保留 `40253896.6` 的1张L40S独立模型服务供后续继续，其他服务和allocation未改。

本地证据：[最终报告](../../cua-rl-local/artifacts/p1-calc-20260918/rollout-report.json)、[第7步公式截图](../../cua-rl-local/artifacts/p1-calc-20260918/step07-formula.png)、[冻结 plan](../../cua-eval/runs/9b-full-r5--train20260822--s306--cuagym-p1--cuagym-calc-p1-n1--20260918T194352Z-97a467585548/plan.json)、[模型发布清单](../../cua-rl-local/artifacts/p1-calc-20260918/model-publication-plan.json)、[任务部署哈希](../../cua-rl-local/artifacts/p1-calc-20260918/task-deployment.txt)。

**实验设计入口**：[RL_EXPERIMENT_DESIGN.md](RL_EXPERIMENT_DESIGN.md)。用户已确认初始模型为现有 Qwen3.5-9B CUA SFT；设计包含冻结 SFT、Binary-GRPO、Partial-GRPO 三个对照。主 benchmark 仍待选择，默认提案为 Verified 361(09-22 更正：用户已确认 OSWorld-Verified)。这里只记录环境事实和准备历史，实验参数与预算以设计文件为准。正式 RL 实验未启动，上游代码未修改；最新 P0 执行结果见下方。

## 2026-09-18：workstation 上的 Calc P0 环境测试已通过

用户授权“试一试”，随后明确使用 workstation，并要求顺便清理其运存。Windows 的既有评测未改动。

- 实际运行主机：workstation / `jyworkstation`，SSH 路由复用现有 registry；启动前 0 个 Docker VM、约 54 GiB 可用内存。仅使用一个并发 VM；重置前后顺序创建两个实例。
- 复用 `/home/yanji/research/OSWorld-V2-shared`，commit `d552441917f302fab410a1991cc705d7bf585d14`、原 `.venv` Python 3.12.3；上游 checkout 前后保持 clean。
- VM 文件使用现有 `.env` 指定的 `.../releases/v2026.06.24/osworld-v2-ubuntu-x86-v2026.06.24-official-fonts.qcow2`。本次未重算整盘哈希，不据文件名推断完整 benchmark release 匹配；这是 CUA-Gym 环境资格测试，不是正式 OSWorld benchmark 成绩。
- 任务：Calc `0029e9c3-6038-55fd-aee3-9eb4186d4d63`，E2 自定义验证 `=E2>D2`。
- 首次尝试 `p0-calc-20260918T090555Z` 暴露 **guest `python3` 缺 openpyxl**。这与 WSL 客户端已安装 openpyxl 是两回事；该实例失败后已停止，失败报告保留。
- 第二次 `p0-calc-20260918T090935Z` 携带固定 `openpyxl 3.1.5` / `et_xmlfile 2.0.0` 纯 Python wheels，通过仅测试命令的 `PYTHONPATH` 使用；没有改 VM 基础镜像、共享 Python 环境或原始任务代码。
- 新增代码仅为独立 `cua-rl-local/p0_calc_vm.py` 和 `p0_calc_guest.py`，远端部署在独立 run 目录；全部上传文件 SHA256 已对照一致。

| 实际检查 | 结果 |
|---|---:|
| 原始 initial_setup 在真实 VM 执行 | 成功 |
| 初始 reward | 0.0 |
| 经 OSWorld 执行真实 GUI 键盘动作 | 成功，截图确认选中 E2 |
| 脚本构造部分完成状态，运行原 reward.py | 0.7 |
| 脚本构造完整完成状态，运行原 reward.py | 1.0 |
| 环境重置、重新运行原 setup 后评分 | 0.0 |
| 本轮两个 VM 实例清理 | 全部停止，最终运行容器数 0 |
| 总运行时间 | 约 67.3 秒，含两次 VM 启动/初始化与清理 |

**范围：P0 的环境/评分/重置部分通过，1/4 个已准备应用完成实机检查。未调用 9B 模型，未进行 agent 自主解题，也未做 backward、权重同步或 GRPO 更新。** 满分来自明确标记的 scripted fixture，不是模型成功率；这次 67 秒也不能用来估计真实长轨迹的训练吞吐。

证据：[完整报告](../../cua-rl-local/artifacts/p0-calc-20260918T090935Z/report.json)、[GUI 动作后截图](../../cua-rl-local/artifacts/p0-calc-20260918T090935Z/02-after-gui-action.png)、[运行日志](../../cua-rl-local/artifacts/p0-calc-20260918T090935Z/run.log)、[首次缺包失败](../../cua-rl-local/artifacts/p0-calc-20260918T090555Z/report.json)。

### 同次 workstation 运存清理

初始 Windows `vmmemWSL` working set 为 44,274,368,512 bytes（约 41.23 GiB）。WSL 内约 39.4 GiB 是文件缓存，进程/内核实际使用约 1.9 GiB。经用户授权执行 `sync` 后释放可回收缓存，没有重启 WSL、没有杀服务或改内存上限；首次核对 Windows working set 降至约 2.73 GiB。P0 结束后再次释放测试产生的缓存，最终数值记录于[清理回执](../../cua-rl-local/artifacts/workstation-memory-cleanup-20260918.json)。Windows working set 的回落可能滞后于 WSL free-memory 统计。

下一步是冻结普通 Qwen3.5-9B CUA SFT 的精确 checkpoint，并接一条真实模型 rollout。目前 registry 中的 9B 服务是 histcomp / TMAX 版本，本轮未默默替换初始化模型。

## 最新纠正：复用现有 Windows / WSL OSWorld，适配 RL rollout

### 数据规模核对（2026-09-18）

本地 `datasets/tasks.parquet` 共 10,910 行、10,910 个唯一 task id，与当前 Hugging Face dataset card 的公开规模一致。按原始 platform 标签：desktop 8,029；web 1,075；cross_app 430；缺失标签 1,376。缺失标签的任务不擅自归入 desktop 或 cross_app。

明确标为 desktop 的分布：Calc 2,576、Writer 2,093、Impress 1,402、VS Code 1,178、PDF 679、VLC 71、GIMP 30。前四类合计 7,249。公开表的 327 个原始 `app_type` 值包含跨应用组合、泛化标签和命名变体，不能称作 327 个独立软件。

项目官网描述整体覆盖 110 environments（16 desktop + 94 web）和约 3.2 万任务，与本地公开任务表的统计口径不同。当前训练准备按已下载文件计数，不按整体宣传规模假定数据已齐。

算法关系：CUA-Gym 提供 task/setup/reward；Arijit 使用 verl/GiGPO；OpenWebRL 使用 slime 的训练/rollout 栈。桌面 RL 的共同闭环是相同 task 初始状态下采样多条轨迹 → 原 evaluator 给分 → 计算相对优势 → 用模型输出 token 的 logprob 和 mask 反向传播 → 同步新 policy 权重。GiGPO 另用 anchor observation 组织步骤级比较；这不意味着数据集提供逐步正确动作。

**Zixian fork 的进一步核对**：远端 HEAD 与本地 `9da6dc1` 一致。主 4B 脚本是 GRPO，默认从 OpenWebRL-4B-SFT 开始，读 2,102 个 WebGym prompts，每 task 5 条 rollout，按 turn 拆训练样本；终局 judge 分数传播至各 turn，并过滤组内 reward 无差异的组。实际 reward 分支为成功 1 / 失败 0 / 特定格式失败 -1，不能按函数旧注释理解成任意 format/judge 加权和。

该 fork 另有 `openwebrl/docs/ARM_SUMMARY.md`，记录 Zixian 的 ARM 候选选择、离线 SFT/DPO、在线 turn-level advantage bonus 实验。在线 ARM 部分在 outcome advantage 上为有有效标签的 turn 加 `0.5 * (selected_executed_action - 0.2)`；与推理时选择最好 action 执行是两种用法。文档报告推理时选择收益最明显，在线 RL 尚未显示可靠增益。本 checkout 只找到这份总结，未找到对应 ARM Python/launcher 实现或它引用的详细结果文件，因此此部分属于作者文档证据，未独立复现实验。桌面适配计划仍先复用 outcome-only GRPO，不自动加入 ARM 研究分支。

来源：[CUA-Gym 项目](https://github.com/xlang-ai/CUA-Gym)、[公开数据说明](https://huggingface.co/datasets/xlangai/CUA-Gym/blob/main/README.md)、本地 parquet 实际计数与两个训练仓库源码。

用户指出已经在 Windows 主机上跑 OSWorld。本次经 SSH **只读实时核对**：

- Windows SSH 别名 `osworld-windows`，WSL 发行版 `Ubuntu-24.04`（另有 docker-desktop）。
- WSL 架构 `x86_64`，存在 `/dev/kvm`。
- `/home/daniel_yan/research/OSWorld-V2-shared` HEAD 为 `d552441917f302fab410a1991cc705d7bf585d14`，Git 状态干净。
- 检查瞬间有 3 个 `happysixd/osworld-docker` 容器运行；这只证明容器存在，不等于某条 rollout 成功或训练已经可用。
- 本地同 commit 的 `OSWorld-V2-personal/local_eval/README.md` 说明该共享环境基于官方 `v2026.08.08`，保留部分 Qwen/VM/runner 适配。未重新校验完整 VM 哈希、全部 gated assets 或模型服务。
- 未启动、停止、重置或修改任何远端容器/实验。另一个 agent 的现有运行不属于本轮 RL worker。

**因此此前“先选一个 VM 主机”对已有项目不准确，应改为：复用既有 Windows/WSL 桌面基础设施，在独立 RL checkout 和结果目录中增加环境服务接口。Mac 上新建的 Python 环境只是准备工具，不替代 WSL 的已验证运行环境。**

刚下载的 `c261cb5` 仅用于对照 Arijit 的代码。后续 RL 环境优先沿用已有 WSL 的 `d552441` / v2026.08.08 基线，不把旧 pin 覆盖到正在运行的共享 checkout。

### 建议适配方案（本轮只设计，未实施）

```text
GPU 训练主机：OpenWebRL / slime + 可训练 policy 的 rollout engine
        │ 截图、动作、任务分数；每组 rollout 固定 policy 权重版本
        ▼
Windows → WSL Ubuntu：独立 OSWorld RL worker / 环境服务
        ▼
既有 Docker/KVM 桌面 VM：reset → screenshot → PyAutoGUI action → evaluate
```

新增的薄层职责：

1. **WSL 环境服务**：封装已有 `DesktopEnv` 的 reset / step / evaluate / close；复用原任务 loader、镜像和环境依赖。为 RL 单独分配 VM、端口、锁和输出目录，不接管正在运行的评测容器。
2. **OpenWebRL rollout adapter**：复用自定义 generate hook；截图进入多模态 prompt，policy 输出转换成既有 PyAutoGUI action，反馈写回下一轮；输出 trainer 所需的 tokens、图像输入、response length、loss mask、rollout logprobs、reward、policy version。
3. **配置**：task pool、endpoint、history / screenshot / coordinate conventions、max steps、同 task 的样本数。原有 browser adapter 和正式 evaluator 不改。

预计最小新增面是独立环境服务、一个 desktop generate/reward 模块和一份配置；先跑 1 个 VM，不先部署另一套 Orchard cluster。

### 任务与 reward

- CUA 是能力/动作范式；OSWorld DesktopEnv 是执行环境；OSWorld benchmark 与 CUA-Gym desktop 是不同任务来源。CUA-Gym desktop 可以在 OSWorld 桌面 VM 中跑，并非 web-only。
- 若目标是提升 OSWorld 泛化，建议用 CUA-Gym desktop / 自有桌面任务训练，OSWorld 留作 held-out 评测。若明确研究 benchmark 内 RL，则单独划分训练和评测任务，不能用训练过的任务声称泛化提升。
- OSWorld 自带 `step()` 在此版本通常返回 `reward=0`；任务得分来自最终 `evaluate()`，不能直接把 step 的占位 0 当训练 reward。
- CUA-Gym tuple 则由原 `reward.py` 返回任务分数；保留 raw score / evaluator error，不直接复用作者 `won >= 0.5` 的成功标签替代官方成功标准。
- 先采用终局 reward；不默认每一步调用可能有 postconfig 或状态修改的 evaluator。
- VM / 网络 / 初始化故障单独标记基础设施错误；不能都混成“任务失败得 0”。

### 从评测走到 RL 的验收顺序

1. 用独立 RL VM 跑一个桌面任务，验证 reset、截图、动作、原 evaluator、清理和重新初始化。
2. 同一 task 从相同初始状态采样 4 条轨迹（起步配置），可用单 VM 串行完成；同组期间不更新 policy，不能让下一条继承前一条的桌面状态。
3. 检查每条轨迹的图像/坐标、实际输入 token、生成 token logprob、mask、终止状态与终局 reward。固定 teacher/API 轨迹不能直接冒充当前 trainable policy 的 on-policy rollout。
4. 接 OpenWebRL 做 1 次小规模参数更新；验证有限 loss/梯度、有效样本数与 rollout engine 同步了新权重，再扩到小任务集。
5. 如果同组 reward 全 0，先排查任务难度、初始化、解析和 evaluator，保证有组内任务奖励差异，再加并发。

Orchard 放在扩容阶段：保持上述环境协议，由 Orchard 管理 worker 生命周期。OSWorld 的完整桌面 VM 还需要考虑 Linux/x86、KVM/device 权限、磁盘/快照与节点资源，不能把已有 browser pod 镜像当成完整桌面 VM。

## 上一轮已完成的本地最小准备（不替代上述 WSL 运行环境）

用户最新要求：只补必要缺项，为 RL 做准备；随后明确自己的重点是 CUA / OSWorld 桌面任务。已停止推进 web mock 路线，本轮只增加独立 Python 环境、OSWorld 固定版本源码、桌面任务资料和外围准备/检查脚本。

五个源码 checkout 的 `git status --short` 均为空；未应用 Arijit 的 OSWorld patch，也没有继续修改 OpenWebRL 或 Orchard。当前没有运行中的本轮 VM / mock / 训练服务。

### 本轮实际补齐

| 项目 | 结果 |
|---|---|
| OSWorld 源码 | `sources/OSWorld-V2/`，固定 `c261cb57a699bd18db128787ca4e71b749141762`，与 Arijit 的 setup pin 一致 |
| Python | 新建 `.venv-osworld/`，Python `3.12.14`，与原先 browser `.venv/` 分离 |
| 必要准备依赖 | numpy、pandas、PyArrow、zstandard、huggingface-hub、requests、websockets、Pillow、PyYAML、openpyxl；完整版本见 `requirements-osworld-prep.lock.txt` |
| 桌面任务 | 从已有 CUA-Gym 下载件提取 Calc / Writer / Impress / VS Code 各一个 smoke 任务，共 12 份原始文件；未执行 Linux setup，未决定正式训练/评测划分 |
| 任务清单 | `datasets/desktop-pilot/tasks.jsonl`、文件 SHA256 和 369 个旧版 OSWorld JSON 示例 inventory；不冒充 OSWorld-Verified 361 |
| 原版导入 | OSWorld `PythonController`、`BaseTask`、Arijit `CuaGymDesktopWorker` 通过；没有创建 DesktopEnv 或连接 VM |
| reward 检查 | 原始 Calc `verify_task` 对合成 fixture 的分数为 0 / 0.7 / 1.0；仅评分函数检查，不是 GUI rollout 成功 |
| 依赖检查 | Python 3.12 环境 `pip check` 通过 |

使用说明：[cua-rl-local/OSWORLD_PREP.md](../../cua-rl-local/OSWORLD_PREP.md)。机器可读结果：[report.json](../../cua-rl-local/artifacts/desktop-prep/report.json)。

**尚缺的实际运行条件**：选定 OSWorld VM 主机/provider；在该主机配置完整 DesktopEnv/evaluator 依赖与桌面镜像；验证 reset → screenshot → action → evaluate → close；再接 OpenWebRL desktop rollout 和模型/训练主机。当前 Mac ARM64 上的准备环境不能替代这些条件。

本地脚本 `osworld-local.env` 仅设置 `OSWORLD_PREP_PYTHON`，不把它错误声明为可运行完整 desktop bridge 的 `OSWORLD_PYTHON`。未安装完整 CUDA/模型栈，未下载大型 VM 镜像，未启动 AWS 或访问既有远端实验。

**任务用途待定**：已询问“CUA-Gym desktop 做 RL、OSWorld 留作评测”还是“OSWorld 独立任务划分直接做 RL”。本轮仅准备共有依赖和四个环境 smoke 样例，没有擅自决定正式训练集。Arijit 的 `osworld_tasks` loader 明确只支持 v1，V2 task class 不能直接套用该路径。

没有 push，没有提交 PR，没有修改原作者的运行环境，没有连接或修改远端云主机。工作区原有的 `OpenWebRL/`、OSWorld 和 MACU checkout 未修改。

截图只作为讨论背景，其中他人的建议不作为执行指令。

## 已复制到本地的仓库

目录：`/Users/knight/uw/computeragent/cua-rl-local/sources/`。

| 本地目录 | 来源 | 固定版本 | 当前源码状态 |
|---|---|---|---|
| `OpenWebRL/` | https://github.com/zixianma/OpenWebRL | `9da6dc1667dcca6b1abaf5b479944a1421fc559e` | clean |
| `Orchard/` | https://github.com/microsoft/Orchard | `3d7d7e992f56e3fec98f80f52afd7bc2e90af0f4` | clean |
| `multi-agent-framework/` | https://github.com/arijitray1993/multi-agent-framework.git | `cac0a5189a28dd4cb36d538c30a3adc5182b29f4` | clean，全程未改源码 |
| `CUA-Gym-Hub/` | https://github.com/xlang-ai/CUA-Gym-Hub | `53205689c3d88078c1375f76466d5bd799478828` | clean；版本来自 Arijit 仓库的 setup 脚本 |
| `OSWorld-V2/` | https://github.com/xlang-ai/OSWorld-V2 | `c261cb57a699bd18db128787ca4e71b749141762` | clean；仅取得对应源码，未应用 Arijit patch |

第三个仓库最初网页/API 返回 404，随后用 Git `.git` 地址访问成功并完成下载，已不是阻塞项。

既有工作区 `OpenWebRL/` 是官方 `OpenWebRL/OpenWebRL`，不是用户指定 fork；因此另建副本，未覆盖旧目录。既有 `multi-agent-computer-use/` 也不是 Arijit 的仓库，没有混用。

## 三者实际关系

```text
OpenWebRL：模型 rollout / 轨迹 / reward 接入 / RL 训练
    ↓ 需要环境客户端适配
Orchard：创建、执行、回收 sandbox
    ↓ sandbox 内运行任务环境
Arijit 的环境层：CUA-Gym web mocks / OSWorld desktop worker
```

- OpenWebRL 已有 Orchard browser sandbox 客户端，不必重新设计整套服务。
- Arijit 仓库本身的训练引擎是 vendored verl/GiGPO。若目标是用 OpenWebRL 训练，应先理解并复用它的环境层，不需要同时部署两套训练引擎。
- Web 分支：Vite/React mock 应用 + Playwright，使用 `sid` 隔离状态，`initial_setup.py` 初始化，`reward.py` 评分。
- Desktop 分支：当前 `worker_bridge.py` 的 `DesktopSession._boot()` 显式写了 `provider_name="aws"`。它不是现成的纯本地桌面环境；直接运行会涉及 AWS。尚未执行该分支。
- 当前本机是 macOS ARM64；完整 OpenWebRL CUDA 训练需要另一类硬件，浏览器环境可单独在本地运行。

## 上一阶段只读检查结果（历史记录，当前状态以上方桌面准备结果为准）

**结论：独立 CUA-Gym web worker 的基础依赖已基本齐备；缺的是解包一个真实任务、配置本地路径与完成运行验证。将它接到 Orchard / OpenWebRL，以及在 Mac 上运行 desktop，是后续不同层面的工作。不能把这些全部归为“缺 Python 包”。**

### A. 单独运行 Arijit 的 web 环境

已通过的检查：

- `.venv`：Python `3.11.1`，Playwright `1.58.0`，requests `2.34.2`，PyArrow `25.0.1`，zstandard `0.25.0`，Pillow `12.3.0`；`pip check` 未发现已安装包的依赖冲突。
- Playwright ARM64 Chromium / headless shell 已在 `browsers/`，不需要重新下载。
- 当前 shell 的 Node `v24.12.0`、npm `11.6.2` 可用；这是本次 shell 检查值，不代表上轮所有安装过程都用了该 Node 版本。
- Instagram、HubSpot、Google Docs、Google Calendar、Notion 五个 app 的直接 npm 依赖均存在，版本与恢复后的原版 lockfile 一致。此检查没有声称完整依赖树、应用构建或启动已通过。
- 原版 `web_worker.py` 可按文件加载成功，未修改源码、未实例化 worker、未启动浏览器。其顶层依赖无需 torch / verl。
- 已下载索引有 **10,910** 行，其中 **1,075** 行为 web。四个主要 mock 对应 **282** 个任务：Instagram 79、HubSpot 77、Google Docs 76、Google Calendar 50。
- 流式读取压缩包，核实这 282 个任务引用的 **846 / 846** 份 task/setup/reward 文件均存在；仅在内存读取，未解包或执行。
- 这批 Python setup/reward 文件均能由 Python AST 解析；静态非标准库 import 只有 `requests` 和 `urllib3`，当前环境均已安装。静态 import 检查不覆盖动态 import、外部程序或脚本运行语义。

还缺 / 尚未做：

1. **任务落盘与 task dict**：压缩包尚未解包；worker 所需的 `setup_files`、`reward_local`、`instruction`、`app_type` 等字段尚未组成可运行的本地任务。
2. **本地路径与配置**：Hub 在并列的 `sources/CUA-Gym-Hub`，而 Arijit launcher 默认寻找仓库内 `datasets/third_party/CUA-Gym-Hub`；需用本地配置明确 Hub 路径、Python、浏览器目录和 mock URL。路径不同不等于需再 clone 一次。
3. **实际运行验证**：原版 worker 的 reset → screenshot → action → reward → close 未执行；sid 隔离和 reward 是否正常也未验证。上一轮 OpenWebRL 的简单按钮测试不能替代它。
4. **若坚持用原数据 loader**：`datasets/loaders/cua_gym.py` 需要 `pandas`、`huggingface_hub`，本 venv 未安装；它调用的 `zstd` CLI 当前可用。若只是验证一个已下载的任务，已有 PyArrow / zstandard 可读取资料，不必为此先装完整训练栈。
5. **若使用 vector manager**：`manager.py` 需要 numpy，目前未安装；完整训练入口还会引入更多依赖。这不阻塞独立 web worker 的基础导入。

所选本地 mock + 脚本动作 + programmatic reward 的初始验证，不需要模型 API key、CUDA GPU 或 Browserbase 账号。若使用真实模型自主操作，再配置 policy endpoint；若使用 live-web judge 分支，再配置 judge。

### B. Orchard 本地 sandbox

已具备 SDK、Docker/Colima/kubectl 工具和一个已停止的独立本地 cluster；SDK 导入成功。尚缺可用的 orchestrator 服务和完整 sandbox 验收，本轮没有重新启动 cluster 查询实时对象。

- **部署配置尚未定案**：上游 orchestrator YAML 默认 3 replicas，每个请求 4 CPU / 16 GiB，Redis 另请求 4 CPU / 16 GiB；合计请求 16 CPU / 64 GiB，超过现有本地 VM 的 4 CPU / 6 GiB。需要本地配置覆盖 replicas / resources，不需要因此修改 Python 业务源码。
- **Redis 有两条原生路径**：多副本部署 Redis；单副本可使用源码已有的 `USE_REDIS=false` 内存存储选项。该选择尚未运行验证。
- **镜像分发缺方案**：原版 injector 使用 `Always` 拉取策略，需要可达 registry。此前改成 `IfNotPresent` 只是我选择“本地预载镜像”方案的适配，并不是运行 Orchard 必须修改的源码；保留原版、配置 registry 也是可选路径。两者都未继续执行。
- **环境镜像未完成**：已有本地旧镜像含过临时改动，不能视为 clean checkout 的正式构建产物；目标 CUA-Gym worker + mock 如何放入 sandbox 尚未打包。
- **网络与生命周期未验证**：未来需检查 pod 到 mock 的实际地址、创建/执行/删除、状态隔离。Mac 上的 `127.0.0.1` 不能直接当作 pod 内同一个服务地址。

### C. OpenWebRL 接入：重新核对之前的改动是否必要

1. **SDK import 可以先不改源码**。本次用当前 `.venv` 加临时 `PYTHONPATH=<Orchard>/orchard_env/orchard_env`，成功执行原有的 `from client.sandbox_client import AsyncSandboxClient, AsyncSandboxInstance`。因此“必须改 import”不成立；先用启动配置即可解决这一层路径问题。只验证了导入，尚未证明整个 sandbox 调用链兼容。
2. **browser Dockerfile 确有漏文件的静态证据**：`web_env.py:11` 导入 `openwebrl.feedback_utils`，Dockerfile 的 COPY 列表未包含它。在按该清单生成的独立镜像中会缺此模块。尚未构建原版镜像来复现；以后真正采用该镜像路线时，再讨论最小补文件方案。
3. **原版包入口的依赖未齐**：本次直接 import 原版 `openwebrl.docker.env_server`，首先报缺 `transformers`。包 `__init__.py` 会引入训练/rollout 模块；当前 venv 还缺 torch、Ray、SGLang、OmegaConf、loguru 等。不能认为只装 transformers 就一定能启动，也不建议为检查 web worker 一次装完 CUDA 训练依赖。
4. **CUA-Gym 接入尚未实现**：在 OpenWebRL 环境目录和 Orchard Python 代码中未找到 CUA-Gym adapter；在 Arijit 的 CUA-Gym env package 中未找到 Orchard 客户端接入。当前需要明确 task 初始化、action 格式、观测、programmatic reward 和 close 如何连接；这是集成工作，不是 pip 安装能补齐的部分。

### D. Desktop 与完整训练

- 当前新目录未下载 Arijit 所固定的 `OSWorld-V2` / `CUA-Gym` 源码，也没有可运行的本地 desktop VM。工作区其他 OSWorld checkout 不能未经版本核对直接代入。
- 原版 desktop bridge 的 `provider_name="aws"` 写在源码里，纯本地部署还缺本地 provider 方案及 VM 架构兼容检查。没有连接 AWS，也未检查或索取云凭据。
- 本地 `.venv` 未安装完整 RL 栈，未配置训练模型权重或 Megatron-LM；Arijit 示例配置中的 `hf_id` 仍指向作者的 `/projectnb/...` 路径，不能在本机直接使用。
- Mac ARM64 不提供 NVIDIA CUDA 训练环境。以后要训练，需要选定 Linux/NVIDIA GPU 机器并独立配置；当前不操作远端主机。

### 最小建议顺序（本次未执行）

先只选 **一个 CUA-Gym web task**：从现有压缩包取出三份文件，给原版 worker 配好 mock URL / 浏览器路径，使用脚本动作验证 reset、截图、reward 和清理。基础依赖已具备，预期无需先改三个仓库源码。通过后再决定 Orchard 打包与 OpenWebRL 接口适配。

本次检查结束：四个源码 checkout 仍 clean；`18100`、`8092`、`8123–8126` 端口均关闭；只更新本 MD，没有安装或启动服务。

数据文件 SHA256（用于识别本次检查的下载件，不代表与发布方校验清单比对）：

- `tasks.parquet`：`334393102f2fd5013c94014999c7db523c65a8bc534827c7bb3f6c3ab82498af`
- `cua_gym_tasks_v1.tar.zst`：`2198e335a8670297cad10405e58b06f3ee7acd8cceaf2d572a5c005e3736f79e`

## 上一轮部署前的初步清单（历史记录，以本次检查结果为准）

以下是检查清单，均不代表已经批准继续修改或部署。

| 部分 | 已确认要求 / 问题 | 最小下一步 | 当前状态 |
|---|---|---|---|
| OpenWebRL browser | Python、Playwright Chromium、FastAPI 等 | 看能否用原版独立入口启动，避免加载训练依赖 | 只在派生精简 runtime 验证通过；原版完整包入口会导入 transformers |
| OpenWebRL sandbox client | 当前导入 `client.sandbox_client`，但引用的 `openwebrl/sandbox/` 不在该版本中 | 确认作者对应 SDK 来源和版本；再决定是否需 import 适配 | 尚未连接验证；临时修改已恢复 |
| OpenWebRL browser Dockerfile | `web_env.py` 需要 `openwebrl.feedback_utils`，COPY 列表未包含该模块 | 原版构建时先确认实际错误；若需补文件只做这一项 | 临时 COPY / Playwright 固定已恢复；构建已停止 |
| Orchard | Python >=3.11、Kubernetes、sandbox agent image；多副本默认 Redis | 先决定是否需要本轮部署 K8s，或只检查 SDK | SDK 已安装，集群已暂停；未部署 orchestrator 服务 |
| Orchard 本地镜像 | init container 使用 `image_pull_policy="Always"` | 先比较原版 registry 路径与本地载入镜像方案 | 本地 IfNotPresent 修改已恢复 |
| CUA-Gym web | Node/npm、指定 mock 应用、Playwright、task tuple | 先选一个 app / 一个 task 验证原版 worker 和 reward | 依赖下载完成，服务已停；真实任务 worker/reward 未验证 |
| CUA-Gym desktop | OSWorld 环境与 VM；当前 worker 固定 AWS | 明确是否要本地 desktop，再检查 provider 与 VM 架构 | 未安装桌面 VM，未调用 AWS |
| 完整 RL | Linux/NVIDIA CUDA、模型权重、Megatron/SGLang 或 verl/vLLM | 后续另列训练环境计划 | 未安装、未启动训练 |

不直接执行上游 `set_up.sh` 或整个 Conda 环境导出：前者包含 Linux CUDA 安装和系统路径链接；Arijit 的环境导出也包含 Linux/CUDA 包。需要先按本轮要运行的组件辨别依赖。

## 本轮已经做过的操作（保留审计）

用户曾授权本地部署后，助手推进到以下步骤；用户指出修改过多后已暂停。这里如实记录，不能理解为“只是 clone，什么都没装”。

### 已安装 / 下载，暂未卸载

- Homebrew 安装：Colima `0.10.3`、Lima `2.2.0`、Docker CLI `29.8.0`、kubectl `1.37.0`。这些工具位于 `/opt/homebrew/`。
- 创建本地 Colima profile `cua-rl`：4 CPU、6 GiB 内存、40 GiB 虚拟数据盘，K3s `v1.35.0+k3s1`。运行数据位于 `~/.colima/`，目前已停止。
- 本地 cluster 中创建过 `orchestrator` namespace、service account、RBAC、API-key secret，并给该本地节点加了 sandbox label。没有部署 orchestrator Deployment，也没有创建云资源。
- 独立 Python venv：`cua-rl-local/.venv/`，安装了 browser runtime、Orchard SDK 和数据读取依赖。
- 独立 Playwright 浏览器目录：`cua-rl-local/browsers/`。
- 安装了五个 mock 的 npm 依赖：Instagram、HubSpot、Google Docs、Google Calendar（上游 hybrid launcher 的四个 app），以及供上游 probe 使用的 Notion。`node_modules` 保留；npm 改写的五份 tracked `package-lock.json` 已恢复原版。
- 下载了 CUA-Gym `tasks.parquet` 和约 49 MiB 的 `cua_gym_tasks_v1.tar.zst`，位于 `cua-rl-local/datasets/`。未执行任务 setup 或 reward。
- 本地 Docker 中构建过 orchestrator 和 agent-injector 镜像；browser 镜像构建被停止。旧镜像可能包含已恢复的临时补丁，不能当作当前 clean 源码的构建结果继续使用。

### 已验证，但范围有限

精简 browser runtime 的本地测试通过：

- `/health` 可用。
- `/reset` 返回 1280 × 1000 PNG。
- `/step` 执行真实鼠标点击，测试页按钮从 `Click me` 变成 `CLICKED`。
- `done` 返回 terminated。
- `/exit` 释放浏览器环境。
- 再次 reset 得到干净的初始按钮状态。

证据：`cua-rl-local/artifacts/browser-smoke.json`、`browser-before.png`、`browser-after.png`。

该测试使用了本地 `browser-runtime/`，按上游 Dockerfile 的文件布局复制必要模块并补入 feedback_utils；它不是原版完整 OpenWebRL 包或 Orchard 集成测试，更不是 CUA-Gym 真实任务成功率。

### 已停止 / 已恢复

- 浏览器 server（原地址 `127.0.0.1:18100`）已停止。
- 五个 mock 服务（原端口 `8123–8126`、`8092`）已停止。
- 本轮 browser Docker build 已停止。
- `cua-rl` 虚拟机 / Kubernetes 已停止。
- OpenWebRL 的两个改动文件、Orchard 的一个改动文件已恢复 HEAD。
- CUA-Gym-Hub 的五份 npm lockfile 已恢复 HEAD。
- 四个 checkout 均再次检查为 clean；Arijit 源码从未修改。

撤回前的 diff 留在 `cua-rl-local/artifacts/*-reverted-changes.patch`，仅用于知道改过什么，未重新应用。

## 后续顺序

1. **已完成**：三个指定仓库下载到独立本地目录，固定版本，恢复原样。
2. **下一步仅检查**：确定先跑 web 还是 desktop；逐项列出缺少的依赖、配置、资产和入口。
3. **待讨论**：如果原版无法运行，解释具体报错、最小修改和替代方案；一次只处理一个问题。
4. **待继续授权**：按选定范围恢复部署并验证一个环境的 reset → action → reward → close。
5. **尚未开始**：OpenWebRL 环境适配、模型 rollout、CUDA 训练。

`cua-rl-local/` 中已有启动脚本、`k8s-local.yaml` 和精简 runtime 都是本轮留下的本地草稿；当前不自动执行，不代表方案已经定下。

## 主要源码依据

- `sources/OpenWebRL/openwebrl/env/sandbox_env.py`：SDK 导入与 sandbox 生命周期。
- `sources/OpenWebRL/openwebrl/docker/Dockerfile.browser`：浏览器环境独立打包方式。
- `sources/OpenWebRL/openwebrl/docker/env_server.py`：reset / step / exit / health。
- `sources/Orchard/orchard_env/pyproject.toml`、`docs/deployment.md`：Python 与部署依赖。
- `sources/Orchard/orchard_env/orchard_env/orchestrator/k8s_client.py`：镜像 pull policy。
- `sources/multi-agent-framework/scripts/setup_third_party.sh`：第三方仓库 pins。
- `sources/multi-agent-framework/third_party/molmoweb-rl/agent_system/environments/env_package/cuagym/web_worker.py`：web reset、action、reward。
- 同目录 `worker_bridge.py`：AWS DesktopEnv。
- `sources/multi-agent-framework/launchers/cuagym_gigpo_hybrid.sh`：四个 mock app。
- `sources/CUA-Gym-Hub/README.md`：mock API 与 sid 隔离。

以上路径均相对于 `/Users/knight/uw/computeragent/cua-rl-local/`。
