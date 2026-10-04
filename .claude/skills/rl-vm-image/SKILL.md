---
name: rl-vm-image
description: 构建或更新 CUA RL 的训练 VM 镜像(Ubuntu-cuagym-vN.qcow2)：普查题库脚本需要哪些 Python 库和命令，按规则决定装什么，求解固定版本，在两台 VM 主机上各构建一份并比对清单，验证后切换。题库变了、训练里出现 grader_error 或"缺模块/缺命令"、或要给镜像加减包时使用。
---

# 构建 / 更新训练 VM 镜像

镜像现在装了什么、为什么装：`CUA/docs/RL_VM_ENVIRONMENT.md` §3。构建工具在 slime-cua `examples/cua_desktop/vm/image/`：`build_image.py`、`provision.sh`、`requirements.txt`、`packages.txt`。

**选包规则**：装题目的初始化和打分脚本要用的；**不装**题目要求 agent 自己去装的。后者的打分里常有"已安装"这一项，预装了初始状态就会得分，比如 `04a48571` 的 pytest。也不要照搬 CUA-Gym 的 `vm_requirements.txt`，它不代表他们实际用的镜像。

## 检查清单

```
- [ ] 1 普查：题库脚本需要什么，现镜像缺什么
- [ ] 2 按规则定清单(逐个看调用位置)
- [ ] 3 求解 pip 固定版本，改 requirements.txt / packages.txt / provision.sh
- [ ] 4 提交，换新版本名，两台主机各自构建
- [ ] 5 比对两台的 manifest
- [ ] 6 在新镜像上探测 + 真 VM 验题
- [ ] 7 改 vm_path，换作业时部署
```

**1 普查**(`vm/guest_census.py`)：
```bash
python3 examples/cua_desktop/vm/guest_census.py scan <train_ids.json> <题目目录> > needs.json   # 任意机器，Python ≥3.10
# 推 guest_census.py、needs.json、worker_bridge.py 到主机的测试目录(不是生产目录)，然后在主机上：
cd <测试目录> && . ./host.env && cd $HARNESS && OSWORLD_VM_PATH=<要查的镜像> PYTHONPATH=$HARNESS setsid $PYTHON -B -u <测试目录>/guest_census.py probe <测试目录>/needs.json > probe.json 2> probe.log < /dev/null &
```
- `scan` 列出模块、命令词、脚本自己 pip/apt 装的包，以及每项涉及的题数。
- `probe` 开一台 VM，逐个 import、逐个查命令，缺的命令用 Ubuntu 的 command-not-found 数据库对应到包。
- 命令词里大多是 heredoc 文本(`from`、`ws` ……)，要看 probe 能对应到包的那部分。
- 占用 1 台 VM 的名额。主机上跑着旧代码 bridge 的训练时，不要在那台主机上起新代码的 bridge，因为孤儿清理会误删训练的 VM。

**2 定清单**：每个候选都看调用位置。在题目文件里搜它出现的那一行，判断是脚本自己用，还是写给 agent 的说明。再查题面里有没有让 agent 装它：
```python
re.search(r"\b(pip|install|installed)\b", instruction, re.I) and re.search(r"(?<![\w.-])<包名>(?![\w-])", instruction, re.I)
```

**3 求解版本**：见 `resolve_pins.md`。要点：
- 按 cp310 manylinux 求解，用镜像自带的包作约束；
- cryptography、PyYAML、cffi 保持系统版本；
- 只有源码包的单独列在 `requirements.txt` 末尾；
- Ubuntu 22.04 没有的工具(如 xcftools)在 `provision.sh` 里装旧版 deb。

**4 构建**：先提交，manifest 会记下提交号。新镜像用新名字(`Ubuntu-cuagym-v<N+1>.qcow2`)，旧的留到新的验证通过。
```bash
# 推 image/ 和 mock_sites.json 到主机上的一个构建目录(保持 image/ 和 mock_sites.json 的相对位置)，md5 校验后：
IMAGE_COMMIT=<提交号> setsid $PYTHON -B -u image/build_image.py <docker_vm_data>/Ubuntu.qcow2 <docker_vm_data>/Ubuntu-cuagym-v<N>.qcow2 > build.log 2>&1 < /dev/null &
```
- 要占一台 VM 的名额。
- 实测：开机约 20 秒，安装约 3 分钟，合并 1–4 分钟，成品约 23 GB。
- `provision.sh` 末尾有检查，任何一项不过构建就失败。
- 两台主机各自构建，不要拷贝：走 Tailscale 只有约 7 MB/s。
- Windows 的 D 盘空间紧，先 `df -h /mnt/d`。

**5 比对**：两台的 `<镜像>.manifest.txt` 除第一行外应逐行相同：
```bash
diff <(tail -n +2 win.manifest) <(tail -n +2 ws.manifest)
```

**6 验证**：
- 在新镜像上重跑第 1 步的 probe：缺的应只剩按规则不装的。
- 再按 `rl-task-check` 跑一组针对性的题，覆盖每个新增依赖和已知问题题。

**7 切换**：
- 改 `vm/vm_hosts.json` 的 `vm_path`(`eval_vm_path` 保持原版镜像)，同步 relay 站的 `~/cua-rl-station/envs/vm_hosts.json`；
- 按 `rl-deploy` 在换作业时推送；
- 更新 `RL_VM_ENVIRONMENT.md`(§3 清单、§8 验证、§9 记录)。

## 构建时踩过的坑

- VM 刚开机时 packagekitd 会占住 apt 的列表锁，`DPkg::Lock::Timeout` 不管这个锁。`provision.sh` 会重试 `apt-get update`。
- 镜像里 Google Chrome 源的签名密钥已过期，`apt-get update` 只打警告，不是错误。
- 工作站上的成品文件属主是 root(qemu-img 在容器里以 root 运行)。不影响使用。
- VM 服务的 `/execute` 写死了 120 秒超时，长命令都要放后台运行再轮询，`build_image.py` 的 `run_long` 和 bridge 的 `_guest_long` 就是这么做的。
