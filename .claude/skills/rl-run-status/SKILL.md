---
name: rl-run-status
description: 查 CUA RL(GRPO)训练的实时状态：作业在不在跑、排队要多久、当前 rollout 进度、轨迹被丢弃的原因、跳过名单、每轮性能指标、两台 VM 主机是否健康。用户问"现在跑到哪了""进度""要排多久""为什么这么慢""v2 怎么样了"时使用。
---

# 查 RL 训练状态

所有数字都要现查，不要凭记忆或文档里的旧值回答。作业号、save 目录先从 `CUA/docs/RL_ENV_PLAN.md` §1 读出来，再用 `squeue` 确认。

## 1 作业和排队

```bash
ssh tillicum1 'squeue -u jy050706 -o "%.8i %.10T %.10M %.25R"'
ssh tillicum1 'squeue --start -j <作业号>'      # Slurm 估计的开始时间(按别人作业的时长上限算，偏保守)
```

排队太久时，查分区里排在前面、真正能动的作业(排除 Dependency / JobHeld):

```bash
ssh tillicum1 'squeue -p gpu-h200 -t PD -o "%.10i %.10u %.10Q %.4D %.11l %.20S %r" --sort=-p | grep -v "Dependency\|JobHeld" | head'
```

用 `sbatch --test-only` 试算的新作业会排在已有作业后面，不能拿来证明"改成 1 个节点更快"。

## 2 rollout 进度

```bash
L=/gpfs/scrubbed/jy050706/rl/cua-runs/train-<作业号>.out
ssh tillicum1 "grep -o '[0-9]*/240 \[[^]]*\]' $L | tail -1"          # 本轮已通过的轨迹数
ssh tillicum1 "grep -o 'broken: [a-z_]*' $L | sort | uniq -c"         # 轨迹被丢弃的原因
ssh tillicum1 "grep -o '\[cuagym-desktop\] [a-z ]*failed[^:]*: .\{0,90\}' $L | sed -E 's/localhost:[0-9]+/localhost:N/' | sort | uniq -c | sort -rn | head"
ssh tillicum1 "grep 'perf [0-9]*:' $L | tail -1"                       # 每轮结束时的指标
```

怎么读：
- 进度条只在**整组**(5 条)通过过滤时才前进，而 48 组的 240 条轨迹是交错在 VM 上跑的，所以组会在一轮快结束时集中完成。进度条长时间不动不等于卡住，要看 VM 主机上有没有 reset 在发生(第 4 节)。
- 组被丢的两类原因：全 0 或全 1(`drop_zero_std_*`)是题目难度问题；`broken` 是环境或题目出错。
- 丢弃原因对照 `CUA/docs/RL_VM_ENVIRONMENT.md` §5：`task_setup_error`、`initial_state_credit`、`skipped_task` 是题目自身的问题；`grader_error` 说明镜像可能还缺东西；`env_reset_error`、`env_step_error` 是 VM 或主机出问题。
- 每轮的 `perf/turn_*`(准备 / 生成 / 环境的中位秒数)和 `rollout/sampling/*`(完成组数、通过组数)在第一轮结束后出现。

## 3 跳过名单

```bash
ssh tillicum1 'f=/gpfs/scrubbed/jy050706/rl/cua-runs/<EXP>/cua_skip_tasks.jsonl; wc -l < $f; python3 -c "import json,collections,sys; print(collections.Counter(json.loads(l)[\"reason\"] for l in open(sys.argv[1])))" $f'
```

## 4 VM 主机

```bash
cd <slime-cua 工作树> && python3 examples/cua_desktop/vm/vmhosts.py check      # 每台：镜像、bridge 能否加载、VM 数、内存、KSM、模拟网站
ssh osworld-windows 'wsl -e bash -lc "tail -20 ~/.cua-rl/relay/ws.log"'           # 工作站 bridge 的日志(在 Windows WSL 的 relay 站上)
ssh osworld-windows 'wsl -e bash -lc "grep -c \"reset timing\" ~/.cua-rl/relay/win.log"'
```

- 正常情况：从快照 reset 19–35 秒；`boot_slot` 偶尔排队几十秒。
- 不正常：reset 几百秒、打分 r0 要几十秒、截图超时、`VM failed to become ready`。先数容器：`running_vms` 超过上限(工作站 8、Windows 4)就是 VM 泄漏，转 `rl-vm-leak-cleanup`。

## 5 汇报

结论先说：在跑 / 排队 / 卡住，以及依据(数字 + 时间)。然后说本轮进度、主要丢弃原因、主机状态。拿不准的地方明确说不确定，并说明怎么验证。
