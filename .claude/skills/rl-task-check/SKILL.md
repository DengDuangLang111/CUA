---
name: rl-task-check
description: 在真 VM 上检查 CUA RL 的题能不能正常初始化和打分(初始分 r0、终态分、是否报错)，走和训练完全相同的 bridge 路径，用测试目录，不碰生产目录。改了 bridge 或镜像之后、怀疑某些题坏了、或要抽样验证一类新题时使用。
---

# 真 VM 验题

`task_check.py`(slime-cua `examples/cua_desktop/vm/`)在 Mac 上起一个 hub 和一个 relay，经 ssh 在主机上起 bridge 和 VM，对每道题 reset 一次，然后立刻回答结束：
- **CUA-Gym 题**：回答 DONE，期望初始分和最终分都是 0；
- **OSWorld 题**：不可完成题回答 FAIL，期望得 1；其余回答 DONE，期望得 0。

**限制**：输入里只要有 CUA-Gym 题，OSWorld 题就**整个被忽略**。两类题要分开跑。

## 检查清单

```
- [ ] 1 选题，生成输入文件
- [ ] 2 准备主机上的测试目录
- [ ] 3 算好 VM 名额，确认不会和训练冲突
- [ ] 4 后台运行，盯日志
- [ ] 5 判读结果，记进文档
- [ ] 6 停掉、清理
```

**1 选题**：
```bash
python3 CUA/.claude/skills/rl-task-check/make_rows.py --slime <slime-cua 工作树> --out-dir <暂存目录> <题号或前 8 位> ...
```
- 从 CUA-Gym 题包里取出这些题，生成 `<暂存目录>/rows.jsonl`，格式和训练用的完全一样。
- 要覆盖某个依赖或命令的题，可以从 `guest_census.py scan` 的 `module_tasks` / `command_tasks` 里挑(见 `rl-vm-image`)。
- 一组好的验证题：每个新增依赖一道，加上已知问题题(`6d15f577` 老版打分脚本、`93d4677f` 初始有分、`04a48571` 让 agent 装 pytest)。
- OSWorld 题直接用 eval-50 的行，在 `cua-rl-local-pool/artifacts/eval50/osworld_eval50_tasks.jsonl`。

**2 测试目录**：Windows 是 `/mnt/d/research/cua-rl-bridge-pool`，生产目录是 `cua-rl-bridge`，不要混用。
- 推 `worker_bridge.py`、`bridge_host.sh`、`mock_sites.json`(要测普查时再加 `guest_census.py`)，每个文件校验 md5，删掉 `__pycache__`。
- `host.env` 里的 `VM_PATH` 指向要测的镜像，`EVAL_VM_PATH` 指向原版镜像。

**3 VM 名额**：
- 主机上限(工作站 8、Windows 4)减去正在跑的 VM 数，就是能用的名额。`task_check` 超过上限时会拒绝启动。
- **新代码的 bridge 不要在跑着旧代码训练的主机上测**：新 bridge 开机前会清理没登记的容器，会删掉训练的 VM。
- 4 台 VM 同时连续 reset 会在开机名额上排队(`boot_slot` 显示 80–130 秒)，不是 bug。

**4 运行**：
```bash
python3 -u examples/cua_desktop/vm/task_check.py --host win --tasks <rows.jsonl> --vms <N> --per-vm <M> \
  --workdir /mnt/d/research/cua-rl-bridge-pool --shots <截图目录> > <输出> 2>&1     # 放后台跑
```
- bridge 的日志(reset 各阶段耗时、安装、快照、报错)在 Mac 的 `~/.cua-rl/relay/task-check-<host>.log`。
- 可以用 Monitor 盯 `reset timing|failed|Error|scored 0|TaskSetup` 这几个关键词。

**5 判读**：每道题一行 JSON(`r0`、`reward`、`reset_s`、`environment_null`)，最后一行汇总"N/M scored as expected"。
| 现象 | 含义 |
|---|---|
| `r0 > 0` | 初始状态就有分，打分脚本或初始化有问题。训练时会进跳过名单 |
| `environment_null` + `TaskSetupError` | 题目自己的初始化脚本失败。看错误信息末尾，分清是题目的 bug，还是镜像缺东西 |
| `GraderError` | 打分脚本崩溃，多半是镜像缺东西，转 `rl-vm-image` |
| `reward.py printed no REWARD line, scored 0` | 老版打分脚本提前返回，按 0 分算，正常 |
| reset 几百秒 | 先查主机负载和容器数(`rl-vm-leak-cleanup`) |

把结果和结论记进 `CUA/docs/RL_VM_ENVIRONMENT.md` §8，新发现的坏题记进 §5。

**6 停止与清理**：在本地停掉任务**不会**停掉主机上的 bridge。
- 在主机上找到测试目录的 `worker_bridge.py` 进程，核对命令行后按 PID 发 SIGINT，bridge 会自己关掉它的 VM；
- 再用 `rl-vm-leak-cleanup` 的脚本确认没有残留：SIGINT 落在 provider 开机等待中的话，容器可能留下。
