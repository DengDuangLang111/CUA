# OPS — 机器与服务运维深度手册

> 从顶层 CLAUDE.md 下沉而来(2026-08-15 文档整编)。CLAUDE.md 只留每 session
> 必需的环境事实与路由;本文承接其余全部运维细节:WSL 魔改明细、代理、隧道、
> 资源、结果目录的坑、OSWorld 任务定义语义。**改本文不改 CLAUDE.md,反之亦然。**

---

## 1 WSL OSWorld 仓库的本地魔改(跑官方评测时要意识到)

```
 M desktop_env/evaluators/getters/file.py        自定义 get_local_file(见下)
 M desktop_env/evaluators/metrics/__init__.py    导入 18 个自定义 metric
 M desktop_env/evaluators/metrics/vscode.py      改了官方 check_json_settings 行为
 M mm_agents/qwen/actions.py                     空解析 fallback DONE -> WAIT(见 1.1)
 M mm_agents/qwen/main.py                        加 preserve_thinking,透传 chat_template_kwargs
 M mm_agents/qwen/client.py                      reasoning_content 取不到时 fallback 到 reasoning
 M mm_agents/agent.py                            ANTHROPIC_BASE_URL 可配 + thinking disabled(只影响 PromptAgent/Claude,跑 Qwen 不走这里)
 M scripts/python/run_multienv_qwen.py           加 --preserve_thinking flag
?? desktop_env/evaluators/metrics/generated_tasks.py
?? synthetic_tasks/
```

共 8 个文件 +96/−40(2026-08-13 `git status` 实测,HEAD 仍是 `091f5ef1`)。
**"我跑的是纯净官方 OSWorld"这个说法不成立**,报告官方分数时这 8 处都要披露。

**对官方 361 题结果的影响已逐一验证(2026-08-13 下午)**:
- 评分通路三处全部无效——`vscode.py` 的 `defaults` 是任务 JSON 主动传参才激活,
  不传时代码路径与上游逐字节等价(diff 核过);`get_local_file` 在官方
  `evaluation_examples/examples/` 里零引用(grep 核过);`metrics/__init__.py` 纯增量。
- **唯一真正影响结果的是 `actions.py` 的空响应 DONE→WAIT**(agent 存活行为,
  上游会提前判死 episode;方向上分数不降)。引用官方分数时披露这一条即可,
  精确口径:"评分函数与上游等价,唯一行为差异是空响应不再提前终止 episode"。

### 1.1 `mm_agents/qwen/` 的改动与「未知 action 被静默吞掉」(2026-08-13 查证)

本地 patch(`actions.py:314`,`parse_internal_response` 末尾):

```python
 if not pyautogui_code:
-    pyautogui_code.append("FAIL" if infeasible_response else "DONE")
+    pyautogui_code.append("FAIL" if infeasible_response else "WAIT")
```

**这个改动是对的**,修的是真问题:模型有时 `</think>` 之后没内容,上游按 DONE 处理会直接
杀掉任务(注释说三个 impress 任务这样死的)。

但要知道这条 fallback 路径是**重载**的,它同时接住两种情况:

1. 空 / 不可解析的 response —— WAIT 正确
2. **格式合法、但 action 名在 parser 里没有分支的 tool call —— WAIT 会导致死循环**

第 2 种实测发生过:模型输出 `<parameter=action>\nanswer\n</parameter>`(**标签内带换行**,
grep 假设相邻会搜出 0——2026-08-13 两个 agent 都栽过),parser 无分支 → 落 fallback →
WAIT → 喂回同一张截图 → 循环。v11 全部 356 个 WAIT 步的完整归因(2026-08-13 逐条核):

| 来源 | 步数 |
|---|---:|
| 模型主动调 `wait`(合法动作,等一个不会发生的事) | 223 |
| `answer` 幻觉被吞(3 任务) | 106 |
| `screenshot` 幻觉被吞 | 18 |
| 空 response | 9 |

幻觉步**不全在尾部**:7 个任务在幻觉后仍有真实动作(含 2 条通过轨迹)。
2026-08-13 已修(均最小化):`actions.py` elif 链末尾加 warning(纯可见性);
`lib_run_single.run_single_example` 加环境变量门控的 WAIT 断路器
(`OSTG_WAIT_BREAK=10`,WAIT 是空操作故提前终止不改分数)+ 重复动作日志
(`OSTG_LOOP_LOG=12`,只记不杀,v11-500 校准用);初始观察落盘 `initial_state.png`
(此前第 1 步的输入图从不落盘)。不设环境变量时行为与上游完全一致。

**但不要"顺手加个 `answer` 分支"**。上游的两套配对本身是自洽的:

| Agent 类 | tools def | parser | `answer` |
|---|---|---|---|
| `_QwenBaseAgent` | `build_base_tools_def` | `parse_base_response` | 声明了,且 `answer→DONE` |
| **`QwenAgent`(campaign 实际用的)** | `build_internal_tools_def` | `parse_internal_response` | **两边都没有**,用 `call_user` |

`QwenAgent` 的 enum 里只有 `… wait / terminate / call_user`,系统提示还写死
"If finishing, use action=terminate"。**所以 `answer` 是模型幻觉出来的未声明动作**,
把它映射成 DONE = 模型一幻觉就不可逆地结束 episode,比现在的 WAIT 更危险。

想真正治循环,通用做法是**连续 N 步 action 完全相同就强制终止**——
它同时治 `answer` 循环和「Ctrl+S 卡在保存对话框连按 43 次」那种模型能力问题。
N 要保守(≥10),否则会误杀连按方向键之类的合法重复。

- **`vscode.py` 改了官方行为**:给 `check_json_settings` 加了 `defaults` 选项,
  影响官方 vs_code 域 7 个用该函数的任务。报告官方分数时必须披露。
- **`get_local_file` 撞名**:上游 `091f5ef1` 自己也加了一个同名函数,但 WSL 上
  `file.py` 只有**一个**定义(第 14 行,本地版本),即本地版覆盖了官方版。
  两者语义不同:本地版相对仓库根解析、返回源路径、支持 `multi`/`gives`;
  官方版相对 CWD、复制到 cache 后返回副本、不支持 `multi`。
  生成任务里有 37 处依赖 `multi`/`gives`,**不要在未确认的情况下把这个文件恢复成上游版**。

---

## 2 代理配置(住宅代理,官方 49 个任务 + 未来真实网站任务需要)

### 为什么需要

官方 361 个任务里有 52 个运行时访问真实站点(Amazon / Delta / TripAdvisor / Airbnb 等),
其中 **44 个标了 `proxy: true`**。这些站点会拦截数据中心 IP、做地理限制,
所以需要住宅代理。**不访问真实站点的 309 个任务完全不需要代理。**

### 供应商不锁定

`desktop_env/providers/aws/proxy_pool.py` 只读五个字段:

```json
[{"host":"...","port":823,"username":"...","password":"...","protocol":"http"}]
```

模板里的 `provider` / `type` / `country` / `note` **代码里从未引用**。
`dataimpulse` 只是官方放在 `evaluation_examples/settings/proxy/dataimpulse.json` 里的示例,
**没有任何技术上的绑定** —— 任何 HTTP / SOCKS5 住宅代理都能直接用。

### 配置步骤(全部在 WSL 上)

1. **凭据文件放仓库外**(见坑①):

   ```
   /mnt/d/research/secrets/proxy.json     权限 700
   ```

   内容就是上面那个 JSON 数组。**在 Windows 本地编辑器里填,不要经 SSH 命令行传密码**
   (会留在 shell history)。

2. **设环境变量**,必须写进启动 runner 的脚本开头:

   ```bash
   export PROXY_CONFIG_FILE=/mnt/d/research/secrets/proxy.json
   ```

3. **runner 必须开代理开关**。campaign 用的 runner 是
   `scripts/python/run_multienv_qwen.py`,它有 CLI flag:

   ```
   --enable_proxy
   ```

   (定义在该文件 `:105`,透传给 `DesktopEnv(enable_proxy=...)`)
   `/mnt/d/research/osworld-verified-control/run_verified_campaign.sh` 里
   目前**没有**这个 flag,跑 49 个 proxy 任务前要加上。

### 验证三步

```bash
# ① 代理本身通不通(返回 IP 应与直连不同)
curl -s -x http://USER:PASS@gw.dataimpulse.com:823 https://api.ipify.org

# ② OSWorld 能否加载配置(打印 1 即成功)
cd /mnt/d/research/OSWorld && PROXY_CONFIG_FILE=/mnt/d/research/secrets/proxy.json \
  python3 -c "from desktop_env.controllers.setup import get_global_proxy_pool as g; print(len(g().proxies))"

# ③ 实跑最简单的 proxy 任务
#    chrome/f3b19d1e-2d48-44e9-b4e1-defcae1a0197  "Find the FAQ page about ticket delivery."
#    只判 URL 正则,不需要文件对拍
```

### 坑

1. **凭据文件不受 `.gitignore` 保护。**
   `.gitignore` 第 209 行虽然写了 `evaluation_examples/settings/proxy/dataimpulse.json`,
   但该文件**已被 git 跟踪**(作为模板提交在仓库里),gitignore 对已跟踪文件无效。
   填真凭据会出现在 `git status` 里。解法:用仓库外的路径 + `PROXY_CONFIG_FILE`,
   或 `git update-index --skip-worktree <path>`。
2. **代理池在模块 import 时初始化**(`controllers/setup.py:38`)。
   `PROXY_CONFIG_FILE` 必须在 Python 进程启动**之前**设好,运行中改不生效。
3. **官方 `run.py` 没有 `enable_proxy` 参数**,`DesktopEnv` 默认 `False`。
   用官方 run.py 跑 proxy 任务会**静默降级为无代理**,只在日志里留一行
   `Task requires proxy but proxy is disabled at system level`,不报错。
4. **`client_password`**:`_proxy_setup` 需要 VM 内 sudo 密码改系统代理,
   `DesktopEnv` 默认 `"password"`。

---

## 3 结果目录与轨迹分析的坑

| 内容 | 路径(WSL) |
|---|---|
| 官方 361 campaign | `/mnt/d/research/OSWorld/results/qwen36-27b-bf16-local/osworld-verified-361-temp06-sleep3-maxsteps50-20260731/` |
| 生成任务(3.6 学生) | `/mnt/d/research/OSWorld/results_generated/qwen36-27b-bf16-local/` |
| 生成任务(3.8 教师) | `/mnt/d/research/OSWorld/results_generated/qwen38-27b-local/` |
| campaign 控制与日志 | `/mnt/d/research/osworld-verified-control/` |

runner:`scripts/python/run_multienv_qwen.py`(**不是**仓库根的 `run.py`)。

每个任务目录含 `result.txt` / `traj.jsonl` / `recording.mp4` / `runtime.log` / `step_*.png`,
外加批次根目录下的 `summary/results.json`(`{application, task_id, status, score, timestamp}` 数组,
统计整批分数用这个比 find 快)。

**Mac 上只有汇总元数据,没有轨迹本体。** 要做轨迹级分析必须先从 WSL 同步。

### 3.1 别在 Mac 上分析轨迹 —— 先 ssh 过去看

任何关于"现在跑到哪了 / 有多少条成功轨迹 / 步数分布"的问题,
**一律 ssh 到 WSL 现查**,不要用 Mac 上的任何副本推断:

```bash
# ① 有哪些批次(按时间倒序,第一个就是最新的)
ssh osworld-windows 'wsl -e bash -lc "ls -1t /mnt/d/research/OSWorld/results_generated/qwen38-27b-local/ | head -20"'

# ② 某批次跑完没 + 分数分布
ssh osworld-windows 'wsl -e bash -lc "cd /mnt/d/research/OSWorld/results_generated/<model>/<BATCH> && find . -name result.txt -exec cat {} \; | sort | uniq -c"'

# ③ runner 还活着吗(活着说明还在跑;顺带打印完整命令行,这是唯一可靠的参数来源
#    —— 包括 result_dir 在哪个 model 目录下,数结果前先看这行,别数错目录)
ssh osworld-windows 'wsl -e bash -lc "pgrep -af run_multienv_qwen | head -3"'
```

### 3.2 `traj.jsonl` 的行数 ≠ 步数(做 SFT 数据必看,2026-08-13 实测)

`lib_run_single.py` 对**每个 pyautogui 动作**写一行,而一个模型 response 可以吐出多个动作。
于是同一个 `step_num` 会出现多行,**这些行的 `response` 字段完全相同**(已用 md5 核对)。

实测 v11 那 39 条成功轨迹:**1041 行 / 946 个唯一 step,膨胀 10%,10/39 条轨迹受影响**。
最极端的一条里 `step_num=16` 占了 9 行。

> **按行做 SFT 样本 = 同一段模型输出被当成最多 9 个独立样本重复训练。**
> 必须先按 `step_num` 聚合:一个 step 出一个样本,`action` 是该 step 所有行的动作按序拼接。

同一目录下还有两个坑:

- **撞 `max_steps` 上限却判 1.0 的轨迹**:v11 有 4 条正好 50 步。抽查其中一条,
  agent 最后卡在 "This site can't be reached" 错误页上反复点击,evaluator 仍判过。
  **这类轨迹后半段是纯噪声,进 SFT 是毒数据**,要单独审或截断。
- **坐标是 relative 0–999**:runner 没传 `--coord`,走 `QwenAgent` 默认 `"relative"`。
  实证:`<parameter=coordinate>[180, 257]` → `pyautogui.doubleClick(345, 277)`
  (180×1920/999=345,257×1080/999=278)。
  → **SFT 标签必须用 `traj.jsonl` 的 `response` 字段,不能用 `action`**,两者差近 2 倍尺度。

---

## 4 模型服务与 Tillicum 隧道

| 项 | 值 |
|---|---|
| 学生 | `Qwen/Qwen3.6-27B` BF16,别名 `qwen36-27b-bf16-local`,WSL `127.0.0.1:18001` |
| 教师 | Qwen3.8-27B(FP8 since 08-14),别名 `qwen38-27b-local`,WSL `127.0.0.1:18020` |
| 权重 | `/gpfs/scrubbed/jy050706/models/`,`max_model_len=262144` |
| 凭据 | `/mnt/d/research/OSWorld/.env` 里的 `OPENAI_BASE_URL` + `OPENAI_API_KEY`(64 位)。**该变量名承载的是 Tillicum vLLM bearer token,不是 OpenAI 平台密钥** |

### 链路

```
WSL 127.0.0.1:1800x/18020
  └─ ssh -L                              (tunnel_qwen36_auto.sh 拉起)
       └─ ProxyCommand → ControlMaster socket  ~/.ssh/cm/qwen36-tillicum-login
            └─ jy050706@tillicum-login02.hyak.uw.edu
                 └─ jy050706@<Slurm 计算节点> : 8000
```

- 身份文件:`~/.ssh/id_ed25519_tillicum`(WSL 上,**没有 `~/.ssh/config`**,全靠脚本显式传参)
- Slurm 作业名 `eval`,分区 `gpu-h200`,时限 `1-00:00:00`
- ControlMaster `ControlPersist=48h`——**只要它活着,后续所有 Tillicum 操作都不用再过 Duo**
- 隧道脚本会自动 `squeue` 找当前节点,Slurm 换节点时自动重连

### runner 标准超时(2026-08-16 定)

一切 runner 调用统一带 `OSWORLD_OPENAI_TIMEOUT=600`。代码默认 130s(10 连接
+120 读取)是为普通 API 延迟设计的,会系统性枪毙长思考:ep1(每题数刀)和
教师在难编码题上(v11-500 第 444 题三世卡死)都中过。600s 下 81920 生成上限
(~510s 含 prefill)永远先于客户端挂断到达,超时与 openai 客户端内层 ×3、
外层 ×5 的重试乘法(单步最坏 75 分钟)全部结构性休眠。

### 常用检查

```bash
# 一句话总检(HTTP 200 + 模型 id 即全通)
cd /mnt/d/research/OSWorld && set -a && . ./.env && set +a && \
  curl -s -w '\nHTTP %{http_code}\n' -H "Authorization: Bearer $OPENAI_API_KEY" \
  http://127.0.0.1:18001/v1/models

# 隧道进程还在不在
ss -ltnp | grep 18001

# ControlMaster 是否健康(输出 Master running 即好)
ssh -S ~/.ssh/cm/qwen36-tillicum-login -O check jy050706@tillicum-login02.hyak.uw.edu

# Slurm 作业与剩余时间
ssh -S ~/.ssh/cm/qwen36-tillicum-login -o ControlMaster=no -o BatchMode=yes \
  jy050706@tillicum-login02.hyak.uw.edu \
  "squeue -u jy050706 -o '%.10i %.10j %.8T %.12M %.12L %R'"

# 直接登进 Tillicum(复用连接,不需 Duo)
ssh -S ~/.ssh/cm/qwen36-tillicum-login jy050706@tillicum-login02.hyak.uw.edu
```

### serve 端口按角色分家(2026-08-16,一次 23 秒崩溃的学费)

所有 serve sbatch 曾统一绑节点 8000 —— Slurm 把两个 serve 调到同一节点时
`Address already in use` 秒崩(lean serve 235244 因此阵亡)。约定:**每个
serve 角色固定专属节点端口,与 WSL 本地端口同尾号**:教师=8000(本地 18020,
历史遗留尾号不一致,不动它),4B rich=8011,base=8012,lean=8013,ep1=8014…
新 serve sbatch 一律按此表取港;隧道 RPORT 同步。

### 隧道自去重与孤儿自灭(2026-08-16 加固)

历史病:每个 driver 启动都无条件拉新隧道,旧清理(`pkill -f "LPORT=..."`)匹配
命令行而 LPORT 是环境变量、从未杀到过任何实例,隧道又永不自退 —— 峰值时 6 个
副本(其中 5 个死 job 的孤儿)以 ~600 次/小时空轮询登录节点。已修在脚本本身
(唯一咽喉点):启动时扫 /proc 环境变量**杀掉同 LPORT 的一切旧实例**(含历史
遗留);job 连 PENDING 都查不到持续 ~1 小时则**自动退出**。此后无论 driver
怎么反复重启,每端口至多一条隧道,且不留永生孤儿。

### 重建隧道(只有 ControlMaster 挂了才需要)

```bash
nohup /mnt/d/research/osworld-verified-control/tunnel_qwen36_auto.sh \
  > /mnt/d/research/osworld-verified-control/logs/tunnel.log 2>&1 &
tail -f /mnt/d/research/osworld-verified-control/logs/tunnel.log
```

**这一步需要密码 + Duo,一次即可**,之后 48 小时内复用。

### 注意

隧道跑在 **WSL 里**,监听的是 WSL 的 `127.0.0.1`。
WSL 里的 runner 能直连;**在 Windows PowerShell 里 curl 是连不上的。**

---

## 5 机器资源与并发

```
Windows 宿主   31.7 GiB RAM  ·  20 逻辑核
WSL2 上限      22 GB(C:\Users\Daniel Yan\.wslconfig)· swap 8 GB
Docker         Docker Desktop · overlayfs · 20 CPUs
WSL 根盘       /dev/sdd 1007 GB,docker 数据在此(不占 D:)
D: 盘          863 GB,qcow2 源镜像在此
```

单 VM 规格写死在 `desktop_env/providers/docker/provider.py:33`:

```python
self.environment = {"DISK_SIZE": "32G", "RAM_SIZE": "4G", "CPU_CORES": "4"}
```

| 资源 | 每 env | 22 GB 下可支撑 |
|---|---|---|
| **内存** | **4.61 GiB**(实测,见下) | **3 个** ← 瓶颈 |
| CPU | 4 核 | 5 个 |
| 磁盘 | ~24.5 GB overlay | 30+ 个 |

### 内存实测(2026-08-14,3 VM 跑 v11-500 稳态)

之前那个"每 env ≈ 6 GB"是估的,**偏高**。`docker stats` + `free` 实测:

```
free 总量        19,998 MB   ← 注意:.wslconfig 写的是 22GB,实际只给到 19.53 GiB
稳态 used        ~15,000 MB
稳态 available   ~5,000 MB
swap 已用        155 MB      ← 3 个就已经碰到 swap 了
```

| 项 | 实测 |
|---|---|
| 单个容器(qemu 在容器内,宿主 `ps` 看不到 qemu) | **4.08–4.11 GiB** |
| runner 主进程 | 0.66 GB |
| 每个 EnvProcess worker | ~0.52 GB |
| **单 env 边际成本** | **4.61 GiB** |
| 系统基线(无 runner 无 VM) | ~1.0 GB |

**4 个 env 需要** `1.0 + 0.66 + 4×4.61 = 20.1 GB`,比 19.53 GiB 的可用量**超 0.6 GB**,
直接进 swap。所以 **22GB 这个配置下 4 VM 跑不了**——差的不多,但没有余量,
而 runner 内存会随时间爬。

要跑 4 个:`.wslconfig` 改到 **25GB**(→ 约 22.5 GiB 可用,用掉 20.1 GB,余 2.4 GiB),
宿主 31.7 GiB 还剩 6.7 GiB 给 Windows。改完必须 `wsl --shutdown`,代价见下。

**决定(2026-08-14):不改,保持 3 VM。** 代价不在内存而在中断——`wsl --shutdown`
会杀掉 SSH 隧道和 ControlMaster,**必须重新过一次 Duo**(要人在键盘前),
同时打断正在跑的 rollout 和 dashboard daemon。**下次要改,改在两个 campaign 之间**——
那时 shutdown 是零代价的。

并发内存门槛在 `synthetic_tasks/generated_trajectory_100/tools/run_generated.sh`:
1 env → 8 GB,2 env → 12 GB,**3 env → 18 GB,4 env → 24 GB**。
`run_verified_campaign.sh:167` 里 `--num_envs 1` 是硬编码,跑官方 campaign 想并发要改这里。

### 改 WSL 内存上限

`.wslconfig` 是 **CRLF** 文件,用 `sed 's/^memory=20GB$/.../'` 会因为行尾 `\r` 匹配不上——
必须用能处理 CRLF 的方式改。改完要 `wsl --shutdown` 才生效,
**而这会杀掉 WSL 里的 SSH 隧道和 ControlMaster,需要重新过一次 Duo。**

### docker 卷残留

上游 `091f5ef1` 已修容器拆除时的孤儿卷问题,不会再积累。清理历史残留(需确保没容器在跑):

```bash
docker volume prune -f
```

---

## 6 OSWorld 任务定义速查(2026-08-08 用 AST 重新核过)

三张词表,**合法值就是这三份实现清单本身,代码里没有第二处声明、没有白名单、没有 schema 校验**。

```bash
# config[].type / postconfig[].type  ->  21 个(其中官方任务只用过 12 个)
grep -nE "^    def _[a-z_]+_setup" desktop_env/controllers/setup.py

# result / expected 的 type  ->  58 个可用
#   注意 getattr 解析的是包命名空间,即 __init__.py 的导出。
#   getters/*.py 里定义了 62 个,有 4 个没 re-export,写进 JSON 会 AttributeError:
#   get_chrome_saved_address / get_extensions_installed_from_shop /
#   get_timezone_from_ip / get_timezone_from_config
grep -oE "get_[A-Za-z_]+" desktop_env/evaluators/getters/__init__.py | sort -u

# evaluator.func  ->  148 个可寻址(官方任务用到 118 个,其中 71 个只被 1 个任务用过)
grep -c "" desktop_env/evaluators/metrics/__init__.py   # 名字全在 __init__.py 的 import 里
```

分派点:`controllers/setup.py:190-196`(`"_{:}_setup".format(type)` + `getattr`)、
`desktop_env.py:380`(func)、`:385`/`:395`(result / expected getter)、`:458`(evaluate)。

**打分语义**:`conj="and"` 时任一 metric 恰好 == 0.0 直接返回 0,否则**取平均**(会出部分分);
`conj="or"` 取 max,恰好 == 1.0 短路。短路用的是**精确浮点相等**,0.999 不会触发。
`conj` 无校验,写成 `"And"` 会静默变成 OR 语义。

### 6.1 runtime 真正读取的只有 5 个顶层键

`id` / `instruction` / `config` / `evaluator` / `proxy`。

其余六个 —— `snapshot`、`source`、`related_apps`、`trajectory`、`fixed_ip`、
`possibility_of_env_change` —— **全仓库没有任何代码读取**,纯装饰。

特别是 **`snapshot` 完全无效**:revert 的目标是 `DesktopEnv` 的构造参数 `snapshot_name`
(默认 `"init_state"`),而语料里 13 个 snapshot 取值没有一个等于它。
docker provider 的 `revert_to_snapshot`(`providers/docker/provider.py:153`)
干脆就是停容器删容器,参数根本不用。**想要特殊环境只能在 config 里 execute 装。**

### 6.2 会静默给错分或静默丢结果的坑(按危险度)

| # | 坑 | 位置 | 后果 |
|---|---|---|---|
| 1 | **metric 抛异常 != 判 0,而是没有 `result.txt`** | 调用点 `desktop_env.py:498/520` 在 try 之外 | 任务**从分母里消失,成功率被抬高**。更糟:`run.py:252-255` 在 resume 时会把没有 `result.txt` 的任务产物**全部删掉**,永远调试不到现场。`postconfig` 出错同理(`setup()` 是 raise),而 203/369 个官方任务带 postconfig |
| 2 | **`launch` 失败不抛异常** | `setup.py:430-439`,非 200 只 log,仅 `wait_for_cdp=True` 才 raise | config 里第二高频(275 次)。应用没起来但 setup 报成功 -> agent 面对空桌面 -> 判 0,看起来像模型不行。`activate_window` / `close_window` / `change_wallpaper` 同样只 log 不抛 |
| 3 | **`execute` 从不检查退出码** | `setup.py:486-498`,returncode 只在 `until` 分支被读 | `mkdir /nonexistent/x` 是一个"记录成功"的空操作。要保证前置条件必须写 `"until": {"returncode": 0}` |
| 4 | **占位符只有 `execute` / `command` 会展开** | 展开在 `_execute_setup` 内的闭包(`setup.py:456`,`:480` 调用) | `{CLIENT_PASSWORD}` / `{SCREEN_*}` 写进 `launch` / `open` / `download` 会原样透传成字面量 |
| 5 | **`get_vm_file` 文件不存在返回 `None` 而不是抛异常** | `getters/file.py:136-141` | `evaluate()` 里两处 `except FileNotFoundError` 基本是死代码。最终判 0 还是崩,取决于 metric 有没有 None 守卫 —— `compare_table`/`compare_docx_files`/`check_include_exclude` 有,**`compare_pptx_files` 没有**(`Presentation(None)` 会加载 0 页空模板;实测最终仍返回 0,所以是照常判 0 而非判错) |
| 6 | **`get_cloud_file` 只按目标文件名缓存** | `getters/file.py:72-78`,先查 `dest` 存在性再读 URL | 金标改了内容但 `dest` 不变 -> 跑过一次的机器永远用旧副本打分。改金标必须同时改 `dest` 或清 `cache/<task_id>/` |
| 7 | **`id` 重复 = 缓存目录串台** | `desktop_env.py:362` 以 `task_id` 做缓存目录 | 两个任务共用 id 就共用缓存,getter 的存在性检查会复用另一个任务的金标 |
| 8 | **`func` 是列表时 `"infeasible"` 失效** | `desktop_env.py:469` 比的是标量 | 会真的去调零参的 `def infeasible(): pass` -> TypeError -> 按第 1 条,没有结果 |
| 9 | **`proxy: true` 静默降级** | `desktop_env.py:290-292` 只打 `logger.info` | 官方 `run.py` 构造 `DesktopEnv` 时**根本不传 `enable_proxy`** |

### 6.3 官方没做的事

- **没有任何 task JSON 的 schema 校验。** 最接近的只有两处 `assert`
  (`setup.py:191` 动作名 hasattr、`desktop_env.py:412-414` 等长检查),
  而且 `python -O` 下两者都会消失。打错的 type/func 要等到 `env.reset()` 才炸,此时 VM 已经起了。
- **`evaluation_examples/README.md` 是错的**:它写 `"config": {对象}`、
  `"evaluator": "路径字符串"`,实际全是 list 和 dict。**不要照官方 README 写任务。**

## 拥堵时的 serve 抢跑通道(2026-08-17 实操验证)

集群满员时,1-GPU 的 eval serve 可走 `--qos=interactive`(优先级 35 vs
normal 25,MaxWall 8h;sbatch 命令行覆盖即可,不改文件)插队到全部 normal
排队之前;eval 驱动按作业名+端口找 serve,换道零兼容成本。训练大作业不适用
(interactive 墙 8h 且属交互用途)。QOS 全表:normal 25/24h · interactive
35/8h · debug 50/1h(限1卡) · urgent 200(勿动) · long 25/7d。

## eval runner 僵死:成因与看门狗(2026-08-17)

**症状**:eval 停在 47/50 四十分钟,runner 进程活着、端点 HTTP 200、
docker 只剩 1 个容器(应 3 个)。

**链条**(日志实证):
```
TypeError: a bytes-like object is required, not 'NoneType'   ← obs['screenshot'] 是 None
ERROR: An error occurred while trying to stop recording: ConnectionResetError(104)
INFO:  Retrying to stop recording.        ← 无上限重试
```
OSWorld 每任务重启 VM(设计如此)。某步撞上重启窗口 → 截图取回 None →
任务抛异常退出且**不写 result.txt** → 清理阶段对已关闭容器"停止录屏" →
连接重置 → **重试循环没有上限** → env 进程永远转 → runner 不退出 →
驱动的 TRY 轮次被堵死 → 整条 eval 链停摆。

**排除项**:docker 根盘 1TB 用 4%(923G 空闲)、WSL 内存 19G 空闲、
容器退出码 0(正常关闭)。`docker system df` 报的 10.2TB 卷是稀疏文件表观
大小,不占实际盘(264 个泄漏卷是垃圾,不是成因)。

**另一个被误认成故障的现象**:`5bc63fb9` 的 step 41 重复 217 次 —— 不是重试,
是**模型一步吐 217 个动作**(逐行 typewrite 一个 Python 文件),每动作 ~4s,
一步烧 15 分钟。它每 4 秒写一条 traj,**不会被看门狗误杀**。

**看门狗**(`tools/eval_watchdog.sh`,不改 OSWorld 一字节以保 eval 可比性):
整个 run 目录 `STALE_MIN`(默认 15)分钟无 traj 写入 → 杀该 run 的 runner,
驱动自行用新 VM 进入下一轮。
**阈值依据(实测 3 个完整 run 的 6,168 个写入间隔)**:中位 5-6s、p99 19-59s、
**史上最大 487s(8.1min)、>10min 的 0 个、>15min 的 0 个**;且判据是"整个 run
目录静默",需 3 个环境同时哑 15 分钟才触发 —— 那种情况基本只有端点挂了,
此时杀掉正确。

**缺题记账政策(用户令 2026-08-17)**:未跑完的题**按 0 计**(所以 gb64o 的
41.8% 是 47 题摊 50 题的**下限**,ep2 的 43.8% 是 49 题);整条 eval 链跑完后
做一次**统一补漏轮**,用同一批 VM 状态补齐所有臂的缺题,可比性最好。
