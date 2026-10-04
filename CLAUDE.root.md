# computeragent — 环境事实、规矩与文档路由

> 顶层 CLAUDE.md 的实际内容(经 `@CUA/CLAUDE.root.md` import，在 CUA 仓库里受版本管理)。
> 只放每个会话都需要的东西：机器与访问、哪份代码是真的、铁律、用户约定、去哪查什么。
> 深度内容在域文档里按需 Read；变化频繁的状态在 `CUA/docs/EXPERIMENTS.md` 顶部"现状"块；可复用的操作流程是 Skills(§6)。

## 1 机器与访问

```
Mac(当前会话：代码分析、CUA 仓库读写)
  ├─ Tailscale ─> Windows desktop-7eajpgq ─ WSL(daniel_yan) ─ Docker ─ Ubuntu VM   ← eval 与 RL 的 VM
  │                    └─ ssh ─> 工作站 yanji@100.72.191.125 ─ Docker ─ Ubuntu VM  ← RL 的 VM(经 WSL 跳)
  └─ ssh tillicum1 / tillicum2(密码 + Duo，ControlMaster 复用)                      ← RL 训练(GPU)、SFT 数据与权重
```

- **Mac 上的 OSWorld 代码只读；影响实验的改动都在 WSL 上做。**
- WSL 上执行：`ssh osworld-windows 'wsl -e bash -lc "cd /mnt/d/research/OSWorld && <命令>"'`。
  - **引号：外层单引号，内层双引号，不要嵌第三层**。命令里的 `|`、`>`、`&&` 在外层会被 Windows cmd 截走，表现为 GBK 乱码的"找不到路径"。
  - 多行或复杂的脚本走 heredoc：`ssh osworld-windows 'wsl -e bash -s' <<'EOF' … EOF`。
  - **heredoc 里的内层 ssh 必须加 `-n`**，否则它会把外层脚本剩下的行当 stdin 吃掉，后面的命令静默不执行。
- **推单个文件**：`ssh osworld-windows 'wsl -e bash -lc "cat > /绝对/路径"' < 本地文件`，**推完必对 md5**(`md5 -q` 对 `md5sum`)，对不上就当没推。`/mnt/d` 上推完 .py 要删 `__pycache__`。
- **WSL 后台进程**：`setsid … < /dev/null &`，之后 `sleep` 几秒并确认日志已生成；ssh 会话一结束，没有 setsid 的进程会被静默杀掉。
- **停进程按 PID**，先核对命令行；不要用 `pkill -f`(会匹配到自己)。本地停掉 task 不会停掉远程进程。
- 每次 ssh 只查一件事。等待某个条件用 `Bash(run_in_background)` 加 until 循环或 Monitor，过滤条件要覆盖失败状态。
- Mac 的 Bash 工具是 zsh：变量不会按空格拆开，拼多段命令的脚本放进 `/bin/bash -e <<'EOF'`；也没有 `timeout` 命令。
- 连通自检：`ssh -o BatchMode=yes osworld-windows 'wsl -e bash -lc "echo OK && whoami"'`。
- **全链路断了**(`*.ts.net` 解析不了、Tailscale 说连不上本地服务)：先查 Mac 的临时端口，`netstat -an -p tcp | grep -c TIME_WAIT` 接近 16384 就是端口耗尽，`sudo sysctl -w net.inet.ip.portrange.first=16384` 恢复。别去修 Tailscale。换网络后 ssh 卡住，`ssh -O exit <host>` 清掉僵死的 master 连接。判别流程见 `CUA/docs/OPS.md` 末节。

## 2 仓库地图(哪份代码是真的)

| 仓库 | 位置 | 角色 |
|---|---|---|
| OSWorld(魔改) | WSL `/mnt/d/research/OSWorld`，091f5ef1 + 魔改 + 未跟踪新增 | **eval 真正跑的 harness**，RL 的 bridge 也用它。报官方分数要披露魔改。**`git diff` 不是完整清单**，未跟踪新增要靠 `git status`(明细 `CUA/docs/OPS.md` §1) |
| OSWorld-upstream | WSL + Mac 各一份纯净 worktree(091f5ef1) | 查官方行为、做任务集分析 |
| OSWorld(Mac 旧副本) | `OSWorld/`，落后 5 个提交 | **别用它做分析** |
| **ostg**(taskgen) | WSL `/mnt/d/research/ostg-v11.1/ostg`(.git 在 ostg/ 子目录) | 生成流水线代码。**工作分支 v11.1，每次流程级提交后 `git fetch . v11.1:main`** |
| ostg 各时代 worktree | os-simple-taskgen*(v6/v8.4)、ostg-v9/-v10/-v11 | 历史标记，别从它们跑东西；task 产物在 `os-simple-taskgen-v8/out/runs/` |
| **CUA**(文档 + dashboard) | Mac `CUA/`，GitHub DengDuangLang111/CUA，**push = Vercel 生产** | **所有文档都放这里**；含 ostg 代码副本(canonical 代码在 WSL)；Skills 在 `CUA/.claude/skills/` |
| **slime-cua**(RL 代码) | 私有仓库 DengDuangLang111/slime-cua，分支 `pool-expand`；Mac 工作树 `slime-cua-pool/`；Tillicum `rl/slime-cua-v2b`(用 git bundle 同步) | `examples/cua_desktop/` 是训练端插件，`examples/cua_desktop/vm/` 是 VM 主机和 relay 站的代码(bridge、镜像构建 `vm/image/`) |
| cua-rl-local | Mac `cua-rl-local/`(只有本地 git，没有远端)；题库脚本在 worktree `cua-rl-local-pool/` | RL 题库的审计和筛选脚本、题包 `datasets/cua_gym_tasks_v1.tar.zst`；`cua-rl-gigpo/` 是 Arijit 框架的存档，不再改 |
| OSWorld-V2(0624 + 魔改) | WSL `/mnt/d/research/OSWorld-V2` | 另一个 benchmark，与 OSWorld 无关。**别拿它跑新实验**(999 个"已修改"里 993 个是 CRLF 噪音) |
| OSWorld-V2-0808 | 两台 WSL 的旧诊断目录 | 保留原结果和缓存；不要从这里启动新 V2 run。原始差异见 `reference/OSWORLD_V2_RUNTIME_REQUIREMENTS.md` 与 harness diff 报告 |
| **OSWorld-V2-shared / -personal** | 两台 WSL `~/research/OSWorld-V2-shared`；Mac 同级 `OSWorld-V2-personal/` | **当前 V2 入口**：GitHub `DengDuangLang111/OSWorld-V2` 分支 `qwen38-v2`，两机固定同一 commit；启动、环境检查、monitor 在 `local_eval/`。实时 commit、路径和合并结果见 `docs/EXPERIMENTS.md` 顶部及 `reports/OSWORLD_V2_THINK_SHARED_20260915.md` |

- 数据与权重不进任何仓库：SFT 数据和 checkpoint 在 Tillicum `/gpfs/scrubbed/jy050706/sft/`；RL 的数据、checkpoint、日志在 `/gpfs/scrubbed/jy050706/rl/`；eval 轨迹在 WSL `results_generated/`。
- 2026-09-14 起本地代码按 `sft/`、`taskgen/` 分组(完整树见 `CUA/README.md`)。只是本地路径调整，WSL 和集群上没有迁移，**不要因为本地有文件就认为已经部署**。

## 3 服务总检

```bash
ssh osworld-windows 'wsl -e bash -lc "cd /mnt/d/research/OSWorld && set -a && . ./.env && set +a && curl -s -w \"\nHTTP %{http_code}\n\" -H \"Authorization: Bearer \$OPENAI_API_KEY\" http://127.0.0.1:18001/v1/models"'
```

学生 3.6 在 :18001，教师 3.8 在 :18020。隧道、ControlMaster、Duo、重建见 `CUA/docs/OPS.md` §4。

## 4 铁律

1. **VM 并发上限**：
   - eval 链 3 台(WSL 22 GB 实测红线；改上限要 `wsl --shutdown`，会杀隧道、重过 Duo，只在两个 campaign 之间做，明细 `CUA/docs/OPS.md` §5)；
   - RL 另算：Windows 4 台、工作站 8 台(用户 10-03 定；工作站受 20 线程 CPU 限制，12 台吞吐反而更低)；KSM 随 WSL 重启失效，要用户重开；
   - 权威值在 slime-cua `examples/cua_desktop/vm/vm_hosts.json`；RL 训练期间不跑 eval 链。
2. **别在 Mac 上分析轨迹和进度**：一律 ssh 现查。eval 先 `pgrep -af run_multienv_qwen` 看 runner 命令行，result_dir 在哪个模型目录下以这一行为准(命令模板 `CUA/docs/OPS.md` §3.1)；RL 用 skill `rl-run-status`。
3. **正在被训练或生成任务读取的数据集不许动**：stage + swap + snapshot(见 memory)。

## 5 用户约定(跨会话有效)

- Keep code clean and simple: prefer the smallest complete implementation, reuse existing functions, and add abstractions or dependencies only when necessary. Preserve supported behavior when removing duplication.
- **任何程序修改前先给 diff 和理由，征求同意**；测量(只读)随时可做。
- **不确定的改动不许落在 main 上**：为一个实验臂加的开关、还没被结果验证的改法、"试试看"性质的东西，一律开分支或 worktree。
  - CUA 侧 `git checkout -b`；WSL ostg 侧 `git worktree add /mnt/d/research/ostg-<名字>/ostg -b <分支> v11.1`。
  - 主干只接已经被结果证明该留下的东西，`build.py` 这类所有语料共用的文件尤其如此。
- 提交说明不带 Claude 署名；生成数据的代码先提交再运行，日志里记 code hash。
- **查到的东西除了更新 md，还要在聊天里完整展示。**
- 中文交流；结论先行，依据跟上；不确定就说不确定，先验证再断言。

## 6 可复用流程(Skills，`CUA/.claude/skills/`)

| Skill | 用途 |
|---|---|
| `rl-run-status` | 查 RL 训练状态：排队、rollout 进度、丢弃原因、跳过名单、VM 主机健康 |
| `rl-deploy` | 部署 slime-cua 新代码：hold → 换作业 → 推 bridge → 更新 Tillicum → 放行 |
| `rl-vm-leak-cleanup` | 找出并清理泄漏的 VM 容器和卷(带只读脚本 `list_orphans.sh`) |
| `rl-vm-image` | 普查题库依赖，构建、比对、切换训练 VM 镜像 |
| `rl-task-check` | 在真 VM 上验题(带取题脚本 `make_rows.py`) |

新增 skill：一个目录一个 `SKILL.md`。开头写 YAML 的 `name` 和 `description`(第三人称，写清"做什么、什么时候用")；正文只写项目特有的事实和步骤，复杂流程用检查清单；容易出错的操作写成脚本，放在同一目录。

## 7 文档路由表(先查这张表，再 Read 对应文件)

| 要做的事 | 读 |
|---|---|
| 项目总览 / 目录结构 | `CUA/README.md` |
| **标准术语与禁用黑话** | `CUA/docs/GLOSSARY.md`(新概念先登记再使用) |
| **臂名 / 语料名怎么起(不手打)** | `CUA/docs/NAMING.md` · `python3 CUA/sft/armname.py emit <sbatch>` |
| 现在跑到哪了 / 下一步 | `CUA/docs/EXPERIMENTS.md` 顶部"现状"块 |
| 实验结果与决策依据(账本) | `CUA/docs/EXPERIMENTS.md` |
| 生成任务：gen→ship→cull→merge→control→rollout 全部命令 | `CUA/taskgen/docs/RUNBOOK.md`(唯一 runbook) |
| 生成流水线的设计与各层职责 | `CUA/taskgen/docs/PIPELINE.md` |
| **SFT 数据流水线：每层职责、五道闸、像素审计、排错** | `CUA/sft/docs/DATA_PIPELINE.md` |
| **Klone 上训练：容器、账号、占位卡、双 bind、OOM 机理、速度账** | `CUA/sft/docs/KLONE.md` |
| SFT：环境、配方、数据构建、训练、eval 协议 | `CUA/sft/docs/TRAINING.md`(当前入口，历史训练账已归档) · `SFT_DATA.md` · `CONTEXT.md`(都在 `CUA/sft/docs/`) |
| **eval 汇报：每个臂的结果、设置、两两差异；§12 全臂总表** | `CUA/sft/docs/RESULTS.md` |
| 标准化 eval：模型 ID、benchmark、题数、两机分配、自动启动与 resume | `CUA/sft/docs/EVAL_AUTOMATION.md` |
| 轨迹页面、visual signal、正式和测试目录与恢复 | `CUA/sft/docs/TRAJECTORY_PIPELINE.md` |
| rollout 打分体系：judge 输入、刻度、schema、仲裁、判官对照 | `CUA/sft/docs/JUDGING.md` |
| checkpoint、数据集、轨迹存哪，能删什么 | `CUA/sft/docs/CHECKPOINTS.md` |
| **失败证据与历史解释** | `CUA/reports/SFT_FAILURE_PATTERNS_20260904.md`；旧账 `CUA/outdated/reports/SFT_FAILURE_ANATOMY_20260903.md` |
| 运维深度：魔改明细、代理、隧道、资源、任务 JSON 语义与坑 | `CUA/docs/OPS.md` |
| **RL：现状、现行设置、链路、提速措施、常用操作** | `CUA/docs/RL_ENV_PLAN.md`(§1 现状是入口) |
| **RL：VM 镜像装了什么、bridge 怎么跑题、VM 泄漏** | `CUA/docs/RL_VM_ENVIRONMENT.md` |
| RL：题库构成与筛选 / 实验设计 | `CUA/docs/RL_TASK_POOL.md` · `CUA/docs/RL_EXPERIMENT_DESIGN.md` |
| RL：09-18 至 10-03 的过程记录 | `CUA/outdated/docs/RL_ENV_LOG_20260918-20261003.md` |
| Dashboard / Vercel 契约 | `CUA/dashboard/README.md` |
| 论文与创新点 / 候选实验的评估与排队 | `CUA/docs/READING.md` · `CUA/docs/IDEAS.md` |
| ostg 分支史 / main 是谁 | `CUA/outdated/docs/TASKGEN_GIT_HISTORY_20260815.md` |
| 官方 361 / V2 任务运行条件(冻结参考) | `CUA/reference/OSWORLD_VERIFIED_RUNTIME_REQUIREMENTS.md` · `..._V2_...` |
| 历史方案(v7 计划、配对组、旧状态页；v12–v15 datagen 方案在 `plans/`) | `CUA/outdated/` · `CUA/outdated/plans/` |

## 8 文档管理规矩

- **同一事实只放在一个文件里**，其他地方放指针。文档都放 CUA 仓库；WSL ostg 仓库只有指路桩；os-simple-taskgen-v8 只有 shell 驱动和旧文件。
- 变化频繁的状态写进 `CUA/docs/EXPERIMENTS.md` 带日期的现状块(RL 的写进 `RL_ENV_PLAN.md` §1)，**不写进本文件**。
- 现行文档只写现在；过时的过程记录整份移进 `CUA/outdated/`，开头写明归档日期和取代它的文件。
- 本文件目标 <200 行：新增内容先问"删掉这行会犯错吗"，答案是否就放进域文档；可复用的流程写成 Skill。
