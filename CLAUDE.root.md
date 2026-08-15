# computeragent — 环境事实与文档路由

> 本文件是顶层 CLAUDE.md 的实际内容(经 `@CUA/CLAUDE.root.md` import,在 CUA 仓库里受版本管理)。
> 只放两类东西:**每 session 都需要的环境事实**,和**"去哪查什么"的路由**。
> 深度内容全在域文档里,按需 Read;变化频繁的状态在 `CUA/EXPERIMENTS.md` 顶部"现状"块,不在这里。

## 1 机器拓扑与访问

```
Mac(当前会话,代码分析 + CUA 仓库读写)
  └─ Tailscale ─> Windows: desktop-7eajpgq
       └─ WSL(daniel_yan)          ← 实验实际运行在这里
             └─ Docker └─ Ubuntu VM ← OSWorld 任务执行
```

**Mac 上的 OSWorld 代码只读;任何影响实验的改动都在 WSL 上做。**

```bash
ssh osworld-windows 'wsl -e bash -lc "cd /mnt/d/research/OSWorld && <命令>"'
```

- **引号规则:外层单引号,内层双引号,不嵌第三层**(会以 GBK 乱码报"找不到路径"崩掉)。
  多行/复杂脚本走 heredoc:`ssh osworld-windows 'wsl -e bash -s' <<'EOF' … EOF`。
- **推单个文件**:`ssh osworld-windows 'wsl -e bash -lc "cat > /绝对/路径"' < 本地文件`,
  **推完必对 md5**(`md5 -q` vs `md5sum`),不一致就当没推。for 循环套引号会静默失败。
- **多段 heredoc 会静默吞输出**(三跳下退出码还是 0)——查状态一次 ssh 只查一件事;
  等条件用 Monitor 或 `Bash(run_in_background)` + until 循环,过滤器必须覆盖失败态。
- `timeout` 命令在 Mac zsh 不存在,别用。
- 连通自检:`ssh -o BatchMode=yes osworld-windows 'wsl -e bash -lc "echo OK && whoami"'`

## 2 仓库地图(哪份代码是真的)

| 仓库 | 位置 | 角色 |
|---|---|---|
| OSWorld(魔改) | WSL `/mnt/d/research/OSWorld`,091f5ef1+8 文件魔改 | **实验真正跑的 harness**;报官方分数需披露魔改(明细 `CUA/OPS.md` §1) |
| OSWorld-upstream | WSL + Mac 各一份纯净 worktree(091f5ef1) | 查官方行为/做任务集分析用这份 |
| OSWorld(Mac 旧副本) | `OSWorld/`,落后 5 提交 | **别用它做分析** |
| **ostg**(taskgen) | WSL `/mnt/d/research/ostg-v11.1/ostg`(.git 在 ostg/ 子目录) | 生成流水线代码;**工作分支 v11.1,每次流程级提交后 `git fetch . v11.1:main`** |
| ostg 各时代 worktree | os-simple-taskgen*(v6/v8.4)、ostg-v9/-v10/-v11 | 历史标记,别从它们跑东西;task 产物在 `os-simple-taskgen-v8/out/runs/` |
| **CUA**(本项目文档+dashboard) | Mac `CUA/`,github DengDuangLang111/CUA,push=Vercel 生产 | **所有文档定都于此**;含 ostg 代码副本(canonical 代码在 WSL) |
| OSWorld-V2 | Mac | 另一个 benchmark,与 OSWorld 无关 |

数据与权重不进任何仓库:SFT 数据+checkpoint 在 Tillicum `/gpfs/scrubbed/jy050706/sft/`,
轨迹在 WSL `results_generated/`。

## 3 服务一句话总检

```bash
ssh osworld-windows 'wsl -e bash -lc "cd /mnt/d/research/OSWorld && set -a && . ./.env && set +a && curl -s -w \"\nHTTP %{http_code}\n\" -H \"Authorization: Bearer \$OPENAI_API_KEY\" http://127.0.0.1:18001/v1/models"'
```

学生 3.6=:18001,教师 3.8=:18020。隧道/ControlMaster/Duo/重建 → `CUA/OPS.md` §4。

## 4 三条铁律

1. **并发上限 3 个 VM**(22GB WSL 实测红线;改上限要 `wsl --shutdown`,会杀隧道、重过 Duo
   ——只在两个 campaign 之间做)。明细 `CUA/OPS.md` §5。
2. **别在 Mac 上分析轨迹/进度**:一律 ssh 现查,先 `pgrep -af run_multienv_qwen`
   看 runner 命令行(**result_dir 在哪个 model 目录下以这行为准,数结果别数错目录**)。
   命令模板 `CUA/OPS.md` §3.1。
3. **正在被训练/生成任务读取的数据集不许动**:stage + swap + snapshot(见 memory)。

## 5 文档路由表(先查这张表,再 Read 对应文件)

| 要做的事 | 读 |
|---|---|
| 项目总览 / 目录结构 | `CUA/README.md`(L1 索引) |
| 现在跑到哪了 / 下一步 | `CUA/EXPERIMENTS.md` 顶部"现状"块 |
| 生成任务:gen→ship→cull→merge→control→rollout 全部命令 | `CUA/RUNBOOK.md`(唯一 runbook;WSL 侧同名文件是指路桩) |
| 生成流水线的设计与各层职责 | `CUA/TASKGEN_PIPELINE.md` |
| 实验结果与决策依据(账本) | `CUA/EXPERIMENTS.md` |
| SFT:环境/配方/数据构建/训练/eval 协议 | `CUA/sft/TRAINING.md`(顶部有现状块)· `CUA/SFT_DATA.md` · `CUA/sft/CONTEXT.md` |
| 运维深度:魔改明细/代理/隧道/资源/任务 JSON 语义与坑 | `CUA/OPS.md` |
| Dashboard/Vercel 契约 | `CUA/DASHBOARD.md` |
| 论文与创新点 | `CUA/READING.md` |
| ostg 分支史 / main 是谁 | `CUA/taskgen/GIT_HISTORY.md` |
| 官方 361/V2 任务运行条件(冻结参考) | `CUA/reference/OSWORLD_VERIFIED_RUNTIME_REQUIREMENTS.md` · `..._V2_...` |
| 历史方案(v7 计划/配对组/旧状态页) | `CUA/outdated/` |

## 6 文档管理规矩(2026-08-15 整编后生效)

- **同一事实只活在一个文件里**,其他位置放指针。文档定都 CUA 仓库;
  WSL ostg 仓库只有指路桩;wrapper 仓库(os-simple-taskgen-v8)只有 shell 驱动和化石。
- 变化频繁的状态写 `EXPERIMENTS.md` / `sft/TRAINING.md` 顶部现状块,**不写进本文件**。
- 本文件目标 <200 行:新增内容先问"删掉这行会犯错吗",答案是否就放域文档。
- 提交规矩:不带 Claude 署名;数据生成代码先入 git 再跑,日志记 code hash。

## 7 用户约定(跨会话有效)

- **任何程序修改前先给 diff 和理由征求同意**;测量(只读)随时可做。
- **查到的东西除了更新 md,还要在聊天里完整展示**。
- 中文交流;结论先行,依据跟上;不确定就说不确定,先验证再断言。
