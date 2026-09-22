# OSWorld-V2 thinking：共享版本与两机结果汇总

## 当前状态

**已按用户要求暂停 OSWorld2，等待另一个 agent 实现采集功能。** 两台 runner、全部同组 worker、本地 monitor 和本次 VM 均已退出；Codex heartbeat 已设为 PAUSED，未经用户再次要求不得自动续跑。

保留 **4/108 个已完成结果**及所有未完成轨迹。262K 恢复批次没有产生新的 result.txt；102题等待后续恢复，036/037仍因代理凭证阻塞。最终分数尚不可用。

Teacher 已成功扩展至 **262144**：Klone作业 **40178215 / g3104 / 2×L40S** 仍在运行，保留供采集功能测试。实测55049输入token +81920请求输出预算被接受。原4个结果来自131072上下文服务；后续恢复批次为262144，须保留这个来源区别。

- [共享 fork / qwen38-v2 分支](https://github.com/DengDuangLang111/OSWorld-V2/tree/qwen38-v2)
- [固定 commit d552441](https://github.com/DengDuangLang111/OSWorld-V2/commit/d552441917f302fab410a1991cc705d7bf585d14)
- [统一启动器](https://github.com/DengDuangLang111/OSWorld-V2/blob/d552441917f302fab410a1991cc705d7bf585d14/local_eval/launch.py)
- [共享协议](https://github.com/DengDuangLang111/OSWorld-V2/blob/d552441917f302fab410a1991cc705d7bf585d14/local_eval/protocol.json)
- [机器可读汇总](OSWORLD_V2_THINK_SHARED_20260915.json)

## 本轮协议

Qwen3.8-27B BF16 / TP2；thinking=True、preserve_thinking=False；10 图、fold 1、history_n=100；100 步、输出上限 81920；temperature=1.0、top-p=0.95。模型 HTTP 请求超时为 600 秒，作为长推理余量，不是网络修复本身。

任务与判分采用官方 v2026.08.08。agent 的失败判定、非 ASCII 输入、call_user 和相应提示词恢复官方，其他已审计适配保留；不能称整个 harness 为完全原版。

## 运行位置

| 主机 | VM | 分片任务 | Runner PID | Monitor PID |
|---|---:|---:|---:|---:|
| jy-eval-wsl / workstation | 0（已停；配置4） | 68待恢复 + 3保留 | 51672（已停） | 51673（已停） |
| osworld-windows / WSL | 0（已停；配置2） | 34待恢复 + 1保留 | 24134（已停） | 24135（已停） |

两份清单无交集，合计 106；此前没开 thinking 的 39 道已出分题全部包含在新一轮里。

workstation checkout：
`/home/yanji/research/OSWorld-V2-shared`

workstation 结果：
`/home/yanji/research/OSWorld-V2-shared/results_v2/qwen38-think-i10f1-d552441-20260915-workstation-ctx262k-r1`

另一台 checkout：
`/home/daniel_yan/research/OSWorld-V2-shared`

另一台结果：
`/home/daniel_yan/research/OSWorld-V2-shared/results_v2/qwen38-think-i10f1-d552441-20260915-windows-ctx262k-r1`

每个结果目录中有 `launch.json`、`runner.log`、`monitor-status.json`、`monitor-history.jsonl`。逐题原始记录位于 `pyautogui/screenshot/qwen38-27b/tasks/<task-id>/`。
每题结束后使用同一套已提交的回调生成页面，输出在各自 `~/cua-v2-shared-trajectories-20260915/`。monitor 已暂停；恢复评测后的页面/原图检查需随监控重新启用；启动前已验证实际 V2 历史轨迹能经过相同回调生成页面。

## 环境一致性证据

- 两个 checkout 的 HEAD 均为 `d552441917f302fab410a1991cc705d7bf585d14`，server 子模块均为 `a3cc3f0c64e463f020d1a44780307e9b46cbcab1`。
- Python 均为 3.12.3，WSL 内核均为 6.18.33.2-microsoft-standard-WSL2。
- 全部 **221 个包的名称/版本完全相同**；规范化包集 SHA-256 为 `221132df561f01db728e4fb7aa19f42ba5740b45d8161dfee4b04f0972f5bec8`。
- Docker 镜像 ID 相同：`sha256:0e6497a9295647cf05bf2b2af522fdd79bdeba2737595259cab310a3bcf6baa9`。
- 两份完整 27,471,970,304 字节 qcow2 镜像 SHA-256 相同：`57c4cef4ed5b1317b0255c8c6aed795098a15aeed387fbeae1fe5870caa3c388`。
- 两边各 108 个任务源已对官方 manifest 校验；本次接入的是这些已验证的本地文件，不上传门控数据。
- 两边真实导入的 agent 都来自新 checkout，文件 SHA-256 均为 `8198beea2eb41bb2a49356e3328dc02b5b47d4661481cc320b95ca2d1a2b588d`。

GitHub 只保存代码、协议和指纹。`.env`、key、主机配置、门控任务/素材、镜像和轨迹没有上传。数据与既有匹配环境通过本地路径复用；同一 branch 名本身不保证这些外部内容一致，须固定 commit 并运行环境检查。

## 网络问题：已复现并修复

旧 Windows 的 CPU 低、内存充足，超时发生在模型 HTTP 调用。相同 635165 字节、4100 prompt-token 请求，通过普通 HTTP 和 OpenAI/httpx 客户端在两条路径都能短时成功；因此不能仅凭小请求成功就判链路健康，也不能把所有超时归因于长 thinking。

关键对照：旧 WSL 读取同一 `/openapi.json` 大响应时，默认 MSS 连续超时（12 秒/6 秒）；仅对单连接设置 MSS900，则约 0.2 秒收到全部 251447 字节。这是可复现的 MSS 敏感大响应路径问题；没有抓包确定究竟哪一层设备丢弃大包。

最终只在旧 WSL 增加到 relay 的专用路由：

```bash
ip route add 100.72.191.125/32 via 172.20.128.1 dev eth0 advmss 900
```

修复后，不加任何 socket 特殊选项的三次普通连接，均收到完整响应：0.108、0.113、0.123 秒。没有修改默认路由、全局 MTU、防火墙、模型或 agent。WSL 重启后此运行时路由可能丢失；须重新检查实际 gateway/interface，不能盲用旧地址。

共享启动器和 monitor 都检查完整的大响应，不再只查小的 health/models。新 run 的旧 Windows 已返回实际非空 think，最新检查暂无 `Request timed out`。

## 为何从 6+2 调整到 4+2

原单 VM 实测约 4.7 GiB 容器内存、4 vCPU，启动约21秒；短请求2/4/8并发吞吐约28.9/38.0/52.3 tokens/s。
但真实6-VM桌面负载令workstation CPU接近98%，并出现截图与Calc启动超时。因此当前降低为4 VM，另一台保持2 VM。短模型请求测试不是完整任务的全局最优吞吐证明，后续依据真实进度和资源监控调整。

## 结果口径与监控

- 旧的 20260905 nothink run 和此前 6+2 诊断启动批次全部保留，只作审计，不混入本次固定 commit 的干净重跑总分。
- 汇总时按 task ID 去重并保留主机来源，分别报告二元通过率和部分得分，使用完整108任务口径；未完成/代理阻塞与真实0分区分。
- 036/037 等待有效代理配置，不伪造结果、不自动购买代理。
- 主机 monitor 使用 boot ID + `/proc` start ticks 判断进程，避免 WSL 校时引起 `psutil.create_time` 漂移而误报停止。
- Codex 定时检查：`osworld-v2-windows`，每30分钟。正常时安静，故障、持续停滞、完成或需要用户操作时通知。
- Teacher资源：Klone `40172229` / `g3104` / 2×L40S，到期2026-09-22 05:11:52 PDT。模型连接依赖workstation的Klone ControlMaster，不依赖Mac在线中转。

## 最新监控检查

检查时间：2026-09-15 10:57:07 PDT。

### 阻塞原因已确定

两台分别在003（Windows）和005（workstation）遇到同一HTTP400：

```text
served context: 131072
requested output: 81920
maximum remaining input: 49152
observed input: at least 49153
total requested: at least 131073
```

两台批次均已退出；workstation的VM早已移除，后续仅结束了卡在清理超过25分钟的本次进程；009等截图连接失败是另一worker被终止后的连带结果，不能算独立模型失败。所有已完成分数及未完成轨迹保留，003/005没有写入零分。网络大响应检查和Teacher服务仍正常，旧WSL的MSS900路由仍在。

### 等待用户决策

已发出选择请求：保留全部历史并动态缩小剩余输出预算，或把服务上下文扩至模型配置支持的262144（需重启Teacher，并可能降低并发容量）。本次没有自动改模型、预算、历史窗口或评分协议，也没有盲目重启。

已完成原始得分仍为001=0.4444444444444444、002=0、004=0.1111、006=0.2222222222222222。
