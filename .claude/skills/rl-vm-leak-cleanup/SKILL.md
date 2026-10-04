---
name: rl-vm-leak-cleanup
description: 找出并清理 CUA RL 两台 VM 主机(Windows WSL、工作站)上泄漏的 VM 容器和悬空卷，并判断泄漏从哪来。主机上的容器数超过上限(工作站 8、Windows 4)、reset 或打分突然变慢、swap 用满、作业停了 VM 却没关时使用。
---

# 清理泄漏的 VM

**泄漏的后果**：每个孤儿容器占约 1 GB 内存和一份 CPU。主机越忙，docker 越容易超时，超时又会留下更多孤儿。10-03 的 342296 在工作站上漏到 31 台(上限 8)，打分从 0.2 秒变成 50 秒，整轮 rollout 预计超过 10 小时。

**原理和已有的防护**：见 `CUA/docs/RL_VM_ENVIRONMENT.md` §6。新 bridge 每次开机前会自动清理。还会漏，说明出现了新的泄漏路径，清理完要查原因(第 3 步)。

## 1 列出(只读)

`list_orphans.sh` 在主机上逐个容器判断。默认只列出，不删除：

```bash
S=CUA/.claude/skills/rl-vm-leak-cleanup/list_orphans.sh
ssh osworld-windows 'wsl -e bash -s' < $S                                         # Windows
ssh osworld-windows 'wsl -e ssh -o BatchMode=yes -o UserKnownHostsFile=/home/daniel_yan/.ssh/cua_workstation_known_hosts yanji@100.72.191.125 bash -s' < $S   # 工作站
```

判断规则(脚本里实现)：
- 是不是 bridge 的 VM：QEMU 带 bridge 的 QMP 参数。eval 的 VM 用同一个镜像、同一个磁盘文件，但没有这个参数，**永远不碰**。
- 在用：被活着的 bridge 登记在 `/tmp/cuagym-vm-<pid>` 里；或者(旧 bridge 不登记时)创建时间晚于最早一个活着的 bridge。
- 孤儿：已停止；或者没有任何活着的 bridge；或者比所有活着的 bridge 都早、又没被登记。

输出里还有 `eval runners`(eval 链在跑的进程数)和悬空卷的数量。

## 2 删除(先确认)

- 工作站是共享机器，删除不可撤销：**先把列表给用户看，得到同意再删**。用户已经明确授权"解决泄漏"的除外。
- `eval runners` 不为 0，或者有 `keep … not a bridge VM` 的容器在跑：说明有 eval 或别人的 VM，只删脚本标了 ORPHAN 的。
- 确认后执行：
  ```bash
  ssh <路由> 'bash -s -- --remove' < $S        # 连同卷删除孤儿容器，再清掉没有容器引用的匿名卷
  ```
- 验证：脚本最后打印容器数、可用内存、swap；再跑一次 `vmhosts.py check`，`running_vms` 应不超过上限。

## 3 查泄漏从哪来

在 Windows WSL 的 relay 站上读 bridge 日志(`~/.cua-rl/relay/{win,ws}.log`；`task_check` 的日志在 Mac 的 `~/.cua-rl/relay/task-check-<host>.log`)，从泄漏开始的时间往后统计：

```bash
grep -c "reset attempt 1 failed\|reset attempt 2 failed\|Read timed out\|VM failed to become ready\|Error stopping container" <日志>
grep "reset attempt" <日志> | tail
```

10-03 见过的几种：
- 开机时在 DesktopEnv 构造函数里出错，容器没人关。表现是"reset 失败"后，下一次重试换了一个新端口。
- 删容器时 docker 接口超时，容器停了但没删。表现是 `Exited` 状态的容器。
- 删容器没带 `-v`，留下匿名卷。
- 镜像构建容器没带卷删除(`db23658` 已修)。

新路径要在 bridge 里修(先给出 diff 和理由)，并记进 `RL_VM_ENVIRONMENT.md` §6。
