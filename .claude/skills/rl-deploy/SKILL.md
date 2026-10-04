---
name: rl-deploy
description: 把 slime-cua(分支 pool-expand)的新代码部署到 CUA RL 训练上：两台 VM 主机的 bridge、Tillicum 上训练端的工作树，以及换作业的时机(hold 下一个作业、取消当前作业、放行)。修改了 examples/cua_desktop/ 下的训练端或 vm/ 下的 bridge 代码、要让它在训练中生效时使用。
---

# 部署 RL 新代码(换作业时)

代码在私有仓库 `DengDuangLang111/slime-cua`，分支 `pool-expand`(Mac 工作树 `slime-cua-pool/`)。有两个部署对象：
- **VM 主机的 bridge**：`examples/cua_desktop/vm/` → 每台主机的生产目录 `cua-rl-bridge/`(`vmhosts.py push`)。bridge 进程在每个新连接上用目录里当时的代码启动。
- **训练端**：`examples/cua_desktop/` → Tillicum 上作业链用的工作树。Tillicum 连不上 GitHub，用 git bundle 同步。

**时机**：bridge 新代码要在**所有 bridge 一起重启时**上线，也就是换作业时。新 bridge 开机前会清理"没登记的 bridge 容器"，而旧 bridge 不登记，新旧混跑会把旧 bridge 正在用的 VM 当孤儿删掉。训练端代码在下一个作业启动时生效。

## 检查清单

```
- [ ] 1 提交并推送(提交说明不带 Claude 署名)
- [ ] 2 hold 下一个作业；需要马上切换的话取消当前作业
- [ ] 3 等两台主机都是 0 台 VM
- [ ] 4 推送 bridge，检查两台主机
- [ ] 5 更新 Tillicum 工作树
- [ ] 6 迁移 save 目录里格式变了的状态文件(如果有)
- [ ] 7 relay 槽数：工作站 8、Windows 4
- [ ] 8 放行作业，盯启动
```

**1 提交**：在 Mac 工作树里 `git commit`，然后 `git push origin pool-expand`。用到数据生成的代码要先提交再运行。

**2 作业**：
```bash
ssh tillicum1 'scontrol hold <下一个> && scancel <当前>'     # 只换代码、不急的话只 hold 下一个，等当前作业自己结束
```
`afterany` 链上，当前作业一结束下一个就会开始，所以**一定先 hold**，不然它会用旧代码启动。

**3 等 VM 清零**：`python3 examples/cua_desktop/vm/vmhosts.py check`，看 `running_vms 0`。作业停了 10 分钟以上还有 VM，就是泄漏，按 `rl-vm-leak-cleanup` 处理后再继续。

**4 推送 bridge**：
```bash
python3 examples/cua_desktop/vm/vmhosts.py push     # 推 bridge、bridge_host.sh、模拟网站配置和生成的 host.env，每个文件校验 md5
python3 examples/cua_desktop/vm/vmhosts.py check    # 期望：vm_image ok ×2、bridge_loads ok、running_vms 0、ksm_run 1、mock_sites_up 31/31
```
然后在两台主机上删掉生产目录里的 `__pycache__`(`/mnt/d` 上可能读到旧的 pyc)。`host.env` 由 `vm_hosts.json` 生成(`VM_PATH` 是训练镜像，`EVAL_VM_PATH` 是原版镜像)。relay 站 `~/cua-rl-station/envs/vm_hosts.json` 是另一份旧格式的副本，改镜像路径时要同步改。

**5 Tillicum**：作业用哪个目录，以 `scontrol show job <下一个> | grep -o "Command=[^ ]*"` 为准(v2 是 `rl/slime-cua-v2b`)。
```bash
git -C <slime-cua 工作树> bundle create /tmp/x.bundle <Tillicum 当前提交>..pool-expand
scp /tmp/x.bundle tillicum1:/gpfs/scrubbed/jy050706/rl/
ssh tillicum1 'cd /gpfs/scrubbed/jy050706/rl/slime-cua-v2b && git bundle verify -q ../x.bundle && git fetch -q ../x.bundle pool-expand && git checkout -q --detach FETCH_HEAD && git log --oneline -1; find examples/cua_desktop -name __pycache__ -type d -exec rm -rf {} +'
```

**6 状态文件**：在 save 目录 `rl/cua-runs/<EXP>/`，接力作业共用。例如 10-03 把 `cua_zero_tasks.jsonl` 转写成 `cua_skip_tasks.jsonl`，每行加上 `reason`。不要改正在被作业读的文件，见 CLAUDE 的铁律 3。

**7 relay**：在 Windows WSL 上 `ps -eo pid,args | grep "[b]ridge_relay"`，看 `--slots`。槽数不对：先确认那个 PID 的命令行是 `bridge_relay.py`，按 PID 停掉，再执行
```bash
cd ~/cua-rl-station && CUA_RELAY_STATION=win python3 -B -c "import sys; sys.path.insert(0, 'scripts'); import vmhosts; vmhosts.start_relays(['win=4', 'ws=0'])"
```
`vmhosts.py follow … --up` 进程会跟着作业链切换转发，不用动它。

**8 放行**：`ssh tillicum1 'scontrol release <下一个>'`，然后按 `rl-run-status` 盯：hub 起来后两台主机应在几分钟内开出 12 台 VM。

## 远程命令的坑(都踩过)

- heredoc 里的内层 ssh 必须加 `-n`，否则它会吃掉后面的脚本行，后面的命令静默不执行。
- 经 Windows 的命令要外层单引号、内层双引号；命令里的 `|`、`>`、`&&` 会被 Windows cmd 截走(报 GBK 乱码)，复杂命令改用 `ssh osworld-windows 'wsl -e bash -s' <<'EOF' … EOF`。
- 从 ssh heredoc 在 WSL 起后台进程：用 `setsid … < /dev/null &`，**后面加 `sleep 5` 并确认日志文件已生成**，否则 WSL 会话一结束进程就没了。
- 停进程按 PID，先核对命令行；不要用 `pkill -f`(会匹配到自己)。本地停掉 task 不会停掉 WSL 上的远程进程。
- Mac 的 Bash 工具是 zsh，变量不会按空格拆开：拼多段命令的脚本放进 `/bin/bash -e <<'EOF'`。
