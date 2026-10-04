# CUA RL：现状、设置与运维

> 本文件只写**现在**：在跑什么、怎么设置的、链路、正在用的提速措施、仍然有效的测量、常用操作。
> - VM 镜像里装了什么、bridge 怎么跑题、VM 泄漏与清理：`RL_VM_ENVIRONMENT.md`
> - 题库构成和筛选：`RL_TASK_POOL.md`；实验设计：`RL_EXPERIMENT_DESIGN.md`
> - 09-18 至 10-03 的逐日过程(路线取舍、冒烟、v1、各项提速的证据、快照原型)：`outdated/docs/RL_ENV_LOG_20260918-20261003.md`
>
> 代码全在私有仓库 `DengDuangLang111/slime-cua`，分支 `pool-expand`：`examples/cua_desktop/` 是训练端插件，`examples/cua_desktop/vm/` 是 VM 主机和 relay 站的代码。

## 1 现状(10-03 17:50，随进展更新)

- **作业**：v2 `grpo-r5-cuagym-v2`，接力链 **342297 → … → 342305**(各 24 小时，`afterany`)。
  - 342297 在排队：要 2 个整节点，能开始的作业里排第一，Slurm 估计 10-04 00:16 开始(按别人作业的时长上限算，可能更早)。
  - 342296 已取消，它第 0 轮没跑完，没有 checkpoint，342297 从初始模型开始。
- **代码**：slime-cua `8f796f1`。
  - Tillicum `rl/slime-cua-v2b`(用 git bundle 同步)；两台 VM 主机的生产目录 `cua-rl-bridge` 是同一版。
- **环境**：两台主机共 12 台 VM，跑训练镜像 `Ubuntu-cuagym-v1.qcow2`；跳过名单里已有 8 道全 0 的题。
- **第 0 轮结束后要看**：
  - `perf/turn_*`(准备 / 生成 / 环境)、通过率、被丢弃的原因、有没有 `grader_error`；
  - **双节点第一步训练**有没有卡住：从来没在双节点上完整跑通过，见 §5。
- **eval-50**：用户 10-03 说"先跳过"。链上设的是每 10 轮一次，第一次在第 10 轮。在那之前要验证 OSWorld 题能切回原版镜像(`RL_VM_ENVIRONMENT.md` §8)。
- **待用户决定**：
  - CUA 仓库要不要推送(推送就会上 Vercel 生产)；
  - cua-rl-local 没有远端仓库。

## 2 现行设置(以 342296 的启动参数为准)

| 项 | 值 |
|---|---|
| 模型 | `rl/models/r5-9b-s306-rl`(r5 9B) |
| 训练数据 | `rl/cua-data/train_20261003d.parquet`，6,847 道(`RL_TASK_POOL.md`) |
| 每轮 | 48 组 × 5 条；动态过滤去掉组内分数完全相同的组(全 0、全 1 等)，不够就按 48 组一批补采 |
| 算法 | GRPO，全局批 256 个 turn，PPO 2 遍，lr 1e-6(常数)，clip 0.2 / 0.28，无 KL |
| 采样 | 温度 1.0 / top_p 0.95 / top_k 20；最多 30 步；截图窗口 20 张、每次折叠 10 张；单次回复 ≤32,768 token，上下文 ≤122,880 token |
| 并行 | 2 节点 16 卡，TP2 × DP8；优化器放 CPU(`OPTIMIZER_OFFLOAD=1`，用户 10-03 定，防 OOM)；全部层重算(用户定不改) |
| VM 并发 | 12(`sglang_server_concurrency` 12) |
| checkpoint | 每轮一次，后台异步写 |
| 轮数 | `NUM_ROLLOUT=100` |
| eval | 每 10 轮 eval-50 一次；第 0 步跳过(342167 已测：54%) |
| 记录 | wandb `yanjiayuan/cua-rl`，组 `grpo-r5-cuagym-v2`；save `rl/cua-runs/grpo-r5-cuagym-v2/` |

**和 Zixian 基线的关系**：算法已对齐。保留的有意差异：
- 作废的轨迹不进组统计；
- 没有 −1 奖励；
- 到步数上限按终态打分；
- 只算回复位置的 logits；
- 没有时间上限。

逐项对照见归档。

## 3 链路与 VM

**链路**：
- Tillicum 的 GPU 节点上跑 trainer 和 hub；
- Windows WSL 上的 relay 站(`~/cua-rl-station`)通过 ssh 端口转发连到 hub。Tillicum 主连接已过 Duo，ControlPersist 30 天；
- relay 站上的 `vmhosts.py follow` 跟着作业链切换转发；
- relay 驱动 Windows 本机的 4 台 VM，并 ssh 到工作站驱动 8 台。

| 主机 | VM 上限 | 开机名额 | 瓶颈 |
|---|---|---|---|
| 工作站 | 8 | 3 | CPU(20 线程)。12 台时比 8 台还慢：20 分钟完成 25 个回合，8 台完成 38 个(10-02 实测) |
| Windows | 4 | 2 | 内存(WSL 限 22 GB) |

- 两台都开着 KSM。**WSL 重启后 KSM 会关，要用户重新打开**。
- 权威配置在 `vm/vm_hosts.json`。relay 站有自己的一份 `~/cua-rl-station/envs/vm_hosts.json`，是旧目录结构，10-03 已同步了镜像路径。
- **reset**：载回内存快照，CUA-Gym 题 19–35 秒；冷启动约 70 秒(训练镜像)。
- 镜像、bridge 的规则、VM 泄漏的清理：见 `RL_VM_ENVIRONMENT.md`。

## 4 正在用的提速措施

原则(用户 10-02)：**修改不影响训练结果**。"仅舍入级"指数学上是同一个计算，只是浮点相加顺序不同。

| 环节 | 做法 | 效果(实测) | 训练结果 |
|---|---|---|---|
| rollout 准备 | 拼提示、跑 processor、PNG 编码放进线程；窗口里已有的截图直接复用 | 每步准备约 0.8 秒 | 不变 |
| 生成路由 | 每条轨迹固定一个 SGLang 引擎，新轨迹分给负载最小的(`--router-policy manual --router-assignment-mode min_load`) | 默认策略把约 85% 的请求压在 1 个引擎上 | 不变 |
| 图片特征传输 | 单节点引擎走共享内存，不再 pickle 后经 ZMQ 发送(`patches/usercustomize.py`) | 首 token 13.8 → 2.55 秒，每次请求 16.9 → 4.6 秒(342296 实测) | 不变(输出逐字相同) |
| 视觉编码缓存 | 开启；权重更新时一起清空 | 每步只有 1 张新图要编码 | 不变 |
| 预填充 | 分块和单批上限都是 32k | 少几轮调度 | 仅舍入级 |
| 训练补齐 | 只补到本微批次最长的样本 | 计算量约减半 | 仅舍入级 |
| 训练内核 | FLA 的 `l2norm`/`causal_conv1d` 按长度分档，不再每个新长度都重新编译调优 | 训练快 15–20 倍 | 仅舍入级 |
| 输出层 | 只算回复位置的 logits | 长样本省约 61 GB 显存，算力约省 10% | 仅舍入级 |
| 截图在内存里 | uint8 只存一份、各轮共享；按微批次搬上 GPU；跨节点时用 zlib 压缩 | 每张 6.3 → 0.8 MB；一轮跨节点数据约 50 → 7 GB | 不变 |
| checkpoint | 后台常驻进程异步写 | 写盘不卡训练 | 不变 |
| 16 卡 | 双节点 | 训练约 ×2 | 仅舍入级 |
| 作业接力 | 24 小时一段，按 afterany 排队，从最新 checkpoint 续跑；relay 站自动切转发 | 不受 24 小时时限影响 | 不变 |
| VM reset | 内存快照载回 + 截图稳定就继续 | 75–228 秒 → 19–35 秒 | 不变 |
| 动作后停顿 | 3 → 0.5 秒(用户定的协议) | 每步省 2.5 秒 | 改变(已定) |
| 跳过名单 | 全 0 题、初始化失败、初始状态就有分的题不再抽 | 每道坏题只付一次 | 改变抽题(用户定) |
| 训练镜像 | 依赖装进镜像，开机不再安装 | 开机省 262 秒，不依赖外网 | 不变 |
| 泄漏清理 | 每次开机前清理没人管的 VM 容器和卷 | 342296 工作站曾漏到 31 台(上限 8)，见 `RL_VM_ENVIRONMENT.md` §6 | 不变 |

**已决定不做**：
- 少重算几层(用户 10-03 定)；
- 把同一窗口的几步合成一个样本训练(用户 10-03："保留现在的")；
- rollout 和训练重叠(异步，会让训练数据比模型旧)；
- 再加 VM(用户："vm 算了")；
- 坏轨迹只返回占位样本(与基线一致)；
- 上下文并行(CP>1 时 Qwen3.5-VL 初始化就断言失败)；
- 打包序列(GatedDeltaNet 不支持 thd)；
- 梯度归约与计算重叠(10-02 导致作业失败，已去掉)。

**每次迭代预计**(10-03 估算，第 0 轮结束后用实测核对)：
- 每步 5–6 秒(准备 0.8 + 生成 3–4 + 环境 1.3)；
- 一条轨迹约 3 分钟，12 台 VM 约 200 条/小时；
- 一轮要 400–600 条(通过率 40–60%)，rollout 2–3 小时；
- 加上训练 10–25 分钟，**每次迭代约 2.5–3.5 小时**。

剩下最大的浪费是全 0 组。新题库对模型偏难，342296 已完成的 12 组里 7 组全 0。

## 5 已知风险

- **双节点训练从未完整跑通**：
  - v1(341861)第一步训练卡在 `log_rollout_data` 的跨节点 gloo 汇总：第二台节点拉约 50 GB 的 rollout 数据用了 4 分钟，超过了默认的 10 分钟超时；
  - 已改：超时 60 分钟(`--distributed-timeout-minutes 60`)，截图压缩后约 7 GB；
  - 只训练的双节点作业 342173 跑通了 38 步，但带真实 rollout 的还没验证。
- **网页题可能被钻空子**：模拟网站的接口不防作弊，见 `RL_TASK_POOL.md` §7。训练中要留意网页题成功率。
- **D 盘**：Windows 的 D 盘只剩 25 GB，不能再放镜像。

## 6 常用操作

```bash
# 作业
ssh tillicum1 'squeue -u jy050706'
ssh tillicum1 'squeue --start -j <作业号>'          # Slurm 的开始时间估计
# 训练日志：Tillicum rl/cua-runs/train-<作业号>.out；跳过名单：rl/cua-runs/grpo-r5-cuagym-v2/cua_skip_tasks.jsonl
# relay、bridge 日志(Windows WSL)：~/.cua-rl/relay/{win,ws,follow-*}.log
# 两台主机的状态：镜像、bridge 能否加载、VM 数、内存、KSM、模拟网站
python3 examples/cua_desktop/vm/vmhosts.py check
# 推送 bridge 和 host.env(只在换作业时推，见 RL_VM_ENVIRONMENT.md §6 的部署注意)
python3 examples/cua_desktop/vm/vmhosts.py push
```

- **暂停 / 放行作业**：`scontrol hold <作业号>` / `scontrol release <作业号>`。换代码时先 hold 下一个作业，部署完再放行。
- **WSL 的 Tillicum 主连接断了**(断网或 WSL 重启)，分两步恢复：
  1. 用户在 Mac 终端执行 `ssh -t osworld-windows wsl -e ssh tillicum2 true`(密码 + Duo)；
  2. 在 WSL 重新挂 follow：`cd ~/cua-rl-station && CUA_RELAY_STATION=win setsid python3 -B -u scripts/vmhosts.py follow <作业号…> --up >> ~/.cua-rl/relay/follow-<作业号>.log 2>&1 < /dev/null &`。
- **改 relay 槽数**：先按 PID 停掉那台主机的 relay(确认命令行是 `bridge_relay.py`)，再在 WSL 的 `~/cua-rl-station` 里执行 `CUA_RELAY_STATION=win python3 -B -c "import sys; sys.path.insert(0, 'scripts'); import vmhosts; vmhosts.start_relays(['win=4', 'ws=0'])"`。
- **Tillicum 更新代码**：本机执行 `git bundle create <f> <旧提交>..pool-expand`，scp 到 `rl/`，再在 `rl/slime-cua-v2b` 里 `git fetch <f> pool-expand && git checkout --detach FETCH_HEAD`，并删掉 `__pycache__`。

## 7 版本追溯

VM 主机上的 harness(bridge 用 `host.env` 里 `HARNESS` 指向的那份，和这台主机做评测用的是同一份)：

| 主机 | harness 目录 | 提交 | 未提交改动(`git diff HEAD` 的 md5 前 12 位) | VM 镜像 |
|---|---|---|---|---|
| Windows | `/mnt/d/research/OSWorld` | `3df1ef4` = 官方 `091f5ef` + 2 个本地 AWS 提交 | `837d312b6af8`，16 个文件 | 训练：`Ubuntu-cuagym-v1.qcow2`(10-03 构建，`7e0db22`)；eval：`Ubuntu.qcow2`(07-31) |
| 工作站 | `/home/yanji/research/OSWorld` | `3df1ef4` | `01e84f1963c9`，17 个文件 | 训练：`Ubuntu-cuagym-v1.qcow2`(10-03 构建，`d355208`，manifest 与 Windows 逐行一致)；eval：`Ubuntu.qcow2`(09-05) |

两台 harness 的差别：
- 工作站的 docker provider 可以用环境变量设内存和核数，默认同为 4G/4，bridge 不设这两个变量，所以效果相同；
- `controllers/python.py` 校验截图的方式不同：Windows 只看文件头，工作站会完整解码。

其余改动过的文件两台 md5 一致。

每个作业日志的 `code` 行记着训练代码的提交号；bridge 每次启动时打印 `[bridge] code md5 …` 和 `harness … diff …`。
