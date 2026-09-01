# OPS — 机器与服务运维深度手册

> 从顶层 CLAUDE.md 下沉而来(2026-08-15 文档整编)。CLAUDE.md 只留每 session
> 必需的环境事实与路由;本文承接其余全部运维细节:WSL 魔改明细、代理、隧道、
> 资源、结果目录的坑、OSWorld 任务定义语义。**改本文不改 CLAUDE.md,反之亦然。**

---

## 1 WSL OSWorld 仓库的本地魔改(跑官方评测时要意识到)

```
 M desktop_env/evaluators/getters/file.py        自定义 get_local_file(见下)
 M desktop_env/evaluators/metrics/__init__.py    导入 20 个自定义 metric;**2026-08-22 补回 9 个被误删的上游导入** —— 加 generated_tasks 块时同一个 diff 里删掉了它们,导致 361 里 8 题在 env.reset() 就崩、全臂强制 0 分(清单与影响面 sft/FAILURE_ANATOMY.md §9)
 M desktop_env/evaluators/metrics/vscode.py      改了官方 check_json_settings 行为
 M mm_agents/qwen/actions.py                     normalize_inline_parameters(环境变量门控,默认关)+ 日志;**空解析 fallback 已于 08-14 恢复上游 DONE**(可比性优先,旧文误记为 WAIT);08-18 起 OSTG_TYPE_NO_SPLIT=1 时多行 type 一条 typewrite 直发(默认 0=上游逐行拆,验收报告 sft/FAILURE_ANATOMY.md;**kD 及之前所有臂 = 拆行语义,kC 起 = 合并语义**);08-18 深夜再加 **OSTG_PARAM_DIALECT=json**:把 Qwen3-VL 原生 Hermes JSON tool_call 归一化成本模块既有的嵌套 XML 形式(与既有 `inline` 方言同构),**默认不设=行为逐字节不变**(闸A 全库 6,385 条回放 100% 一致;闸B JSON 与 XML 产生相同 pyautogui 100%;灵敏度对照能抓错)。目的:VL backbone 对照实验复用全部动作语义,避免重写时丢失 terminate(failure)。闸的 pipeline 命令 `ostg.sft.vlcheck dialect`
 M mm_agents/qwen/main.py                        加 preserve_thinking,透传 chat_template_kwargs;**08-29 再加 `OSTG_REASONING_EFFORT`**(设了才注入 chat_template_kwargs.reasoning_effort;不设=模板默认 xhigh,逐字节同旧行为。模板只认 xhigh/medium/low,传 high 会 400——见 RUNBOOK「chat template, read at source」)
 M mm_agents/qwen/client.py                      reasoning_content 取不到时 fallback 到 reasoning
 M mm_agents/agent.py                            ANTHROPIC_BASE_URL 可配 + thinking disabled(只影响 PromptAgent/Claude,跑 Qwen 不走这里)
 M scripts/python/run_multienv_qwen.py           加 --preserve_thinking flag(评测侧空转,见下);08-18 起崩溃题落 result.txt=0.0 + harness_error.json(孤儿题修复,**代价:崩溃题不再被补跑趟自愈**,恢复靠按 harness_error.json 显式删目录重跑);**09-01 加 signal handler 父子判别**(worker 继承父进程 handler 后对 `processes` 调 `is_alive()` 断言,断言落进任务 except 写假零,10 例;现子进程直接 `sys.exit(0)`,不写 result.txt)**+ AWS SSO 快速失败**(按类名 `TokenRetrievalError` 判定,SIGTERM 父进程中止全跑;71 例逐题假零的教训)
 M desktop_env/controllers/setup.py              **09-01 新增** `_server_restart_policy_setup`:给客机 `osworld_server.service` 打 systemd drop-in(`StartLimitIntervalSec=0`),去掉"60 秒内崩 5 次即永久判死"的限速。**只在 `OSTG_GUEST_RESTART_UNLIMITED=1` 时调用,不设=逐字节同旧行为**。根因与实测 sft/FAILURE_ANATOMY.md §10.0,语义验证 §10.12
 M desktop_env/desktop_env.py                    **09-01**:`reset()` 里按上述开关调用(快照回滚会抹掉 drop-in,故每任务重打;+4 行)
 M desktop_env/controllers/python.py             **09-01**:截图非 200 时把 response body 前 500 字记进日志(此前只记状态码,68 次 HTTP 500 无从分辨"handler 抛异常"与"进程已死");纯日志
 M desktop_env/server/osworld_server.service     **09-01**:仓库副本同步改 `StartLimitIntervalSec=0`。**对预制镜像 `happysixd/osworld-docker` 无作用**(单元烤在镜像里),仅保证未来自建镜像不再带此限速
 M lib_run_single.py                             存 initial_state.png(第 1 步观测原本不落盘);OSTG_WAIT_BREAK / OSTG_LOOP_LOG 两个环境变量(不设则完全惰性);**08-31 加 J2 磁盘状态收割**(`OSTG_FINAL_STATE=1` 才启用,不设完全惰性):setup 后采一次 VM 内文件普查作基线,判分前再采一次做差集,把 agent 改动的文件转录成文字存 `final_state.json` 给强判官。两个插入点:`obs = env._get_obs()` 之后(基线)、`env.evaluate()` 之前(收割)。安装器 `ostg-v16/patches/apply_j2.py`(幂等,只改 run_single_example)
?? mm_agents/qwen/final_state.py                 **08-31 新增**:J2 收割+转录模块。转录**按容器格式分派**(ODF 的 .odp/.odt/.ods 读 content.xml;OOXML 各用各的库——python-pptx 读不了 .odp、openpyxl 读不了 .ods),图片只做魔数检测(抓 `cp x.png y.jpg` 这类名实不符)。宿主侧转录,VM 不需要任何库
?? desktop_env/evaluators/metrics/generated_tasks.py    整个自定义 evaluator 模块(08-18 起含 check_pptx_props / check_image_props,fmt-w1 的规则式格式判据)
?? synthetic_tasks/ · taskgen_tasks*/ · taskgen_out/ · eval_valpanel_tasks/
?? evaluation_examples/verified_eval50_nonproxy.json · ..._eval100_...
```

 M mm_agents/qwen/prompts.py                     **08-28 补记**:apply_tool_dialect —— OSTG_PARAM_DIALECT=json 时把工具调用格式说明改写成 Hermes JSON 方言;**不设则提示词逐字节不变**(它是 actions.py 那条 dialect 机制的配套文件,机制早已记账、文件名漏记)

 M mm_agents/qwen/images.py                      **08-28 深夜**:process_image 的 max_pixels 环境变量化(`OSTG_MAX_PIXELS`,不设=13107200,逐字节同旧行为)。图窗试点 D 臂用 491520(≈960×512,~480 视觉 token/张;旧值下 1920×1088=2040 token/张)。坐标回缩 adjust_coordinates 原生按发送尺寸换算,无需配套改动

**09-01 起共 15 个已跟踪文件**(09-01 加 setup.py/desktop_env.py/controllers/python.py/osworld_server.service 四个,净 +79/−8,分支 `fix-harness-crashes@0a6d674`,净补丁 `/mnt/d/research/patches/fix.5files.patch`,在跑树 5 文件 md5 见 sft/FAILURE_ANATOMY.md §10.12;此前 11 个:08-28 深夜加 images.py +2/−1 后;此前 10 个 +303/−40
复核于同日,HEAD 仍是 `091f5ef1`),另有
上列未跟踪新增 + 新增未跟踪:`verified_eval261_rest.json`、`eval50b`、`vlsmoke3.json`、
两个 codex-sync tar、`__init__.py.bak-before-restore-imports`。

> **08-28 复核补记**:`lib_run_single.py` 里存在一段 verifier-拒绝-DONE 逻辑,
> 但它整个住在独立函数 `run_single_example_vlaa_gui`(verifier_agent 默认 None)
> 里,`run_multienv_qwen.py` 只调用标准 `run_single_example` —— **对 qwen 线
> rollout/评测零影响**。runner 默认 `history_n=100 / image_max=20 / fold_size=10`,
> **教师谱系跑的就是这套默认**(v11-500 datagen、eval50-t38、t3850b、t38261 四个
> args.json 08-28 深夜逐一实测:h100/20fold10/ms50/t1.0)——照谱系 rollout 不需要
> 显式传窗口参数;只有改窗口的实验臂才传(见 run_eval50_stock.sh 各臂 XARGS)。
> 旧文此处写"必须显式传 --history_n 20"是把学生评测口径混进了教师谱系,已废。

> 2026-08-13 记的是"8 个文件 +96/−40",漏了 `lib_run_single.py`,行数也已过时。
> **`git diff` 不是完整清单** —— 未跟踪的新增(包括一整个 evaluator 模块
> `generated_tasks.py`)它一行都不显示,披露魔改时必须同时看 `git status`。

> `mm_agents/qwen/main.py` 加的 `--preserve_thinking` 透传**在评测侧是空转的**:
> 两份 chat template 都不引用这个变量,而 stock 模板本来就保留历史思考。
> 详见 `sft/RESULTS.md` §5.7。同名的 **swift 训练参数不是空转的**。
**"我跑的是纯净官方 OSWorld"这个说法不成立**,报告官方分数时这 8 处都要披露。

> **2026-08-22 追加,披露时必须带上**:上表 `metrics/__init__.py` 那一行在
> 2026-08-18 到 2026-08-22 之间是**有害的**,不只是"加了自定义 metric"。它删掉了
> 九个上游导入,使 **361 里 8 题从未真正评测过**(全臂 0 分,含教师)。已补回,
> 但**在此之前产出的所有 361 / 留出 50 数字都带这个折损**:全 361 −2.2pp、
> 留出 50 −4.0pp、multi_apps −5.4pp。补跑范围待定,未补跑前引用这些数字要标注。

**对官方 361 题结果的影响已逐一验证(2026-08-13 下午)**:
- 评分通路三处全部无效——`vscode.py` 的 `defaults` 是任务 JSON 主动传参才激活,
  不传时代码路径与上游逐字节等价(diff 核过);`get_local_file` 在官方
  `evaluation_examples/examples/` 里零引用(grep 核过);`metrics/__init__.py` 纯增量。
- **唯一真正影响结果的是 `actions.py` 的空响应 DONE→WAIT**(agent 存活行为,
  上游会提前判死 episode;方向上分数不降)。引用官方分数时披露这一条即可,
  精确口径:"评分函数与上游等价,唯一行为差异是空响应不再提前终止 episode"。

> **OSWorld-V2 的魔改不记在这里** —— 它是另一个 benchmark。魔改清单、0624→0808 迁移、
> 本地分叉(worktree `/mnt/d/research/OSWorld-V2-0808`,分支 `v2-0808-qwen`)与"让模型看到
> 历史 think"的三处改动,全部在 `CUA/reference/OSWORLD_V2_RUNTIME_REQUIREMENTS.md` §0.5。

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
| 教师 | Qwen3.8-27B **BF16**,别名 `qwen38-27b-local`,WSL `127.0.0.1:18020`。<br>⚠ 2026-08-18 更正:此处原写 "FP8 since 08-14",**错的**。`results_generated/qwen38-27b-local/*/MODEL_BOUNDARY.json` 自记 `"precision":"BF16"`;serve sbatch 里的 `fp8` 只作用于 `--kv-cache-dtype`,不是权重。照旧文起服务会毁掉与历史轨迹的可比性 |
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

### serve 参数与客户端的硬耦合(2026-08-19 补,查 eval4bv20 时发现)

4B eval serve 的真实启动形状(角色化端口见上节;**端口号与作业号是易变状态,
不写死在这里,用下面的方法现查**):

```
vllm serve <checkpoint 绝对路径> --served-model-name <臂名> \
  --max-model-len 262144 --kv-cache-dtype fp8 \
  --reasoning-parser qwen3 --limit-mm-per-prompt {"image": 20} \
  --host 127.0.0.1 --port <角色端口>
```

两条会咬人的耦合:

1. **`--limit-mm-per-prompt {"image": N}` 必须 ≥ 客户端 `image_max`**。
   目前两边都是 20。**只调大 runner 的 `--image_max` 而不同步改 serve
   sbatch → 请求直接 400**,而且是跑到中途图数超了才炸,不是启动就炸。
   改图窗的实验(img1/img3/vl20 这类)必须两边一起改。
2. **`--reasoning-parser qwen3` 决定了 think 不在 `content` 里**,而在
   `reasoning_content`。客户端 `mm_agents/qwen/client.py:107` 两个字段名都试,
   再由 `merge_reasoning_content` 拼回 `<think>…</think>`。**一旦 merge 拿不到
   reasoning,历史 think 会变空,而空 think 被 chat template 整块丢弃 ——
   表现是上下文静默瘦掉 ~88%,不报错、不留日志**。这一环断过一次:official-361
   跑出 7,906 步 0 个 `<think>`。两个方向的完整说明在 `RUNBOOK.md`
   「Qwen3.8's chat template, read at source」;渲染侧机制与实测数字在
   `sft/RESULTS.md` §5.7。

另外服务端没开 `--enable-auto-tool-choice` / `--tool-call-parser`:tool_call 以
纯文本回来,由 `mm_agents/qwen/actions.py` 自己解析(顶层传 `tools` 字段会报错)。

**怎么查某个端口背后真正在跑什么**:WSL 上 `ss -lntp` 只看得到 ssh 进程 ——
本地端口都是隧道,服务在 Tillicum 计算节点上。要看真实启动命令,先
`squeue -u jy050706` 找到作业与节点,再穿到该节点 `pgrep -af vllm`;
`/v1/models` 返回的 `root` 字段是 checkpoint 绝对路径,可用来核对臂与步数
(分数是权重的属性,不是 sbatch 意图的属性 —— 见 `sft/RESULTS.md` §5.2)。

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

### 5.x Tillicum 排队优先级:fairshare 是我们自己花掉的(2026-08-20 实测)

用户问"优先级怎么又变低了"后查 `sprio` / `sshare` / `scontrol show config`,
数据如下(权重:Age 1000、FairShare 1000、JobSize 1000、Partition 1000、QOS 5000):

| 作业 | 总分 | AGE | **FAIRSHARE** | JOBSIZE |
|---|---|---|---|---|
| 我们 249662 / 249689 | 1101 / 1099 | 4 / 2 | **1** | 83 |
| 他人 249686 / 249638 / 249653 | 1169 / 1122 / 1101 | 3 / 6 / 5 | **123 / 71 / 53** | 31 / 34 / 31 |

**差距全在 fairshare。** `sshare`:jy050706 RawUsage **3.77 亿**,同账户其他人各约
5000 万(**7.4 倍**),独占 `video` 账户用量的 **51.6%**,fairshare 得分 0.001333
(账户内最低;零用量的 ranjay 是 0.0107)。账户本身也超支:名义份额 0.66%,
实占集群 21.5%。**同时开四炉训练 + 常驻 eval serve 就是这么把分花光的。**

**恢复很慢**:`PriorityDecayHalfLife = 30 天`,`PriorityUsageResetPeriod = NONE`
——用量按 30 天半衰期消,没有周期清零,今晚的消耗压未来几周。

**能控的杠杆只有 AGE**:`PriorityWeightAge=1000`、`PriorityMaxAge=7 天`,
即**排队每小时约 +6 分,满 7 天 +1000 分**,和 fairshare 同权重。
**每次撤了重交,AGE 归零。** 由此定两条操作规矩:
1. **改拓扑/改配置要一次改到位**,别靠反复重交试(今晚 np2e6→np1e6→nocapnp
   连撤四轮,AGE 全清);真要调顺序用 `scontrol update jobid=X Nice=N`,
   改名用 `scontrol update JobName=`(PENDING 状态改名不丢排队年龄,实测)。
2. **控制并发炉数**:并发不只让当下排队变慢,它加深的是未来几周所有作业的坑。

注:JobSize 反而对我们有利(16 卡作业 83 分 vs 小作业 23-34),所以"拆小作业
提高优先级"在这台机器上是反的。

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

## 看门狗:两个都删了(2026-08-17)

`eval_watchdog.sh` 和 `master_watch.sh` 都是 2026-08-17 加的,当天删除。

**`eval_watchdog`**:判据 `find -name traj.jsonl -newermt "-15 minutes"` 返回空
就杀 runner —— 但**"还没写过任何东西"和"卡住了"在这个判据下完全一样**。启动三个 VM
再等 serve 端点本来就超过 15 分钟,于是它把每个 eval 都在启动阶段循环杀掉:
lorakeep 和 leanstock 当天各自 0/50 死掉,而 lorakeep 的驱动照样喊了
`EVAL50_LORA_DONE`,把链条放行,导致 lean-stock 反过来 `scancel` 了 LoRA 的 serve。
当初 15 分钟阈值的论证(6168 个间隔里最大 487 秒)测的是**任务之间**的间隔,
**根本没覆盖启动**。

**`master_watch`**:一次 ssh 探测失败就 `pkill -f run_multienv_qwen`。
网络抖一下就能清空所有 eval。

**结论(用户裁决)**:这两个工具防的是偶发卡死,造成的是系统性损失。
**写得越多越难维护,越难维护 bug 越多。** 卡死本来就有驱动的三次重试兜底;
真卡死了人看一眼即可,不值得为它常驻一个有 `pkill` 权限的进程。

**留下的规矩**:任何常驻进程,只要它的动作里有 `pkill`/`scancel`,
就必须能区分「没开始」「进行中」「真卡住」三种状态;区分不了就别写。

## 隔离改名与下一趟建队列的竞态(2026-09-01 实例)

runner 每趟起跑时 `get_unfinished()` 扫一次目录建队列:**有 `result.txt` 的算完成,
之后再改名/删除都不会进本趟队列**,要等下一趟。09-01 10:40 看门狗误杀 runner,
两个 worker 正在跑的题(writer `e246f6d8`、multi_apps `1f18aa87`)拿到截图 None →
TypeError → 10:41 写 `result.txt=0.0`;链脚本 10:41:25 起下一趟,runner 10:42:30
建队列(`Total tasks: 51`,这两题按"已完成"排除);隔离改名
`result.txt.poisoned-20260901104232` 发生在 **10:42:32,晚了 2 秒**。结果:这两题
本趟不跑,dashboard 显示 "—",traj 停在 10:41。它们会在**再下一趟**(TRY=3)被
`get_unfinished` 清目录后重跑——链每臂最多 5 趟,本趟结束于 98/100 时自动触发。

规矩:**隔离/删分要在链脚本起下一趟之前做完**;若已起,就等它自然进下一趟,
别去动在跑的 runner。判断某题是不是"被跳过":先看它目录里有没有 `.poisoned-*`
或 `harness_error.json`,再看链日志的 `pass N at X/T` 行——"—" 只表示没有
`result.txt`,不区分"没轮到"和"被隔离等重跑"。

## 作业编排的两条硬规矩(2026-08-17,各犯一次换来的)

### 一、先占再放:新作业排上之后,才取消旧作业

**犯错经过**:要把 Bhqs-2t 的两个训练臂从旧数据集换到 r5,我先 `scancel` 了
236399/236400(其中一个已经 RUNNING),然后才去准备新作业。集群当时已满,
**队列位置白丢**,重排要从头等。

**正确做法**:数据用**新名字**并存(`q38-Bhqs2t-r5-*`),新作业指向新名字直接提交;
旧作业只有在新作业**确认排上之后**才取消。数据集不覆盖,就不存在"边训边换"的冲突,
也就不必先取消。

### 二、数据 ship 完并核对通过,才提交作业

**犯错经过**:v11500 还在传时就提交了 240273/240288。当时想的是"PENDING 的作业
不读数据",但那一刻 g015 恰好空着,**作业提交后立刻被调度**,sbatch 里的 preflight
发现图片路径不存在,两个作业**双双在 5 秒内 FAILED**。

**preflight 本身工作正常**(宁可秒退也不拿缺数据训),但作业没了、还得重提。

**正确顺序**:
```
to_swift → ship(两半都 SHIP OK)→ 在集群上独立核对行数/图引用/未解析数
        → 确认无误 → 再 sbatch
```

### 合起来的时序

```
1. 建新数据集(新名字,不覆盖旧的)
2. ship,等 SHIP OK
3. 在集群上核对:行数、图片引用数、未解析数=0
4. 提交新作业
5. 确认新作业进入队列(squeue 可见)
6. 这时才 scancel 旧作业
```

**通用形式:稀缺资源永远先获取再释放;有副作用的提交永远在前置条件核实之后。**

---

## fairshare 见底:为什么我们的作业总排在别人后面(2026-08-19 查实)

**结论:不是配额不够,是 fairshare 分见底;而根因在账户份额,不在个人用量。**

Slurm 用 multifactor,权重实测(`scontrol show config`):
`Age 1000 · FairShare 1000 · JobSize 1000 · Partition 1000 · QOS 5000`。
我们一个 16 卡作业的分解(`sprio -l`):

```
PARTITION 1000 + JOBSIZE 83 + AGE 5 + FAIRSHARE 1 + QOS 12 = 1102
```

**FairShare 满分 1000,我们拿 1 分**(`sshare` 实测 0.001340,全集群倒数第一)。

同账户对比(video,8 个活跃用户平分 1 份 RawShares,人均 NormShares 0.125):

| 用户 | RawUsage | 占账户 | FairShare |
|---|---:|---:|---:|
| jy050706 | 374,188,254 | **51.86%** | 0.00134 |
| yuhengw | 154,617,604 | 21.43% | 0.00268 |
| ranjay(零使用) | 0 | 0% | 0.01072 |

但根因在**账户层**:video 的 EffectvUsage 21.37%,而每账户 NormShares 只有
0.00658(152 个账户平分)—— **整组超用约 32 倍**,所以账户里一点没用的 ranjay
也只有 0.0107。对照抢在我们前面的人:slszeto 用了 95.3% 仍有 **0.310**、
rrrd 用了 100% 仍有 **0.109** —— **他们比我们用得还狠,fairshare 却高 80-230 倍**,
差别只在所在账户人少、人均份额高。

能做与不能做:

- **换 QOS 没用**:normal(25)→interactive(35) 归一化后只从 12 分涨到 17 分,
  而要追的差距是 4~261 分。(interactive 另有 MaxWall 8h、每用户 2 作业 的限制。)
- **少用也没用**:做到账户内第一(ranjay 水平)也只有 11 分。
- **等衰减太慢**:`PriorityDecayHalfLife = 30 天`。
- **唯一有效的**:找 hyak 管理员给 video 账户提 `RawShares`(现在是 1,
  与单人账户同级,而我们有 8 个人在用)。

**实操绕行(已验证,比调优先级管用得多)**:同样的活拆成 **8 节点 × 1 卡**
比 2 节点 × 8 卡好插太多 —— 集群常有 10+ 个 mix 节点带零散空卡,整节点却很少。
一次实测:16 卡版预测 19:05 启动,同时提交的 8 节点×1卡 版 **19 秒**就跑起来了。
代价是 `--mem` 受 **240G/GPU** 限制(1 卡/节点时 `--mem=600G` 会被拒,改 200G)。

**调顺序用 `scontrol update jobid=X Nice=N`**(加 nice 降优先级、`Nice=0` 恢复,
两个方向本账号都有权限),**不要靠 scancel 重交** —— 重交会重置排队年龄,
优先级反而掉(248793→248809 掉了 42 分)。

---

## 选权重/选文件的代码必须打印它选了什么(2026-08-18,一周的错分换来的)

### 犯了什么

serve 与 LoRA 合并作业都用这一行从一次训练里挑 checkpoint:

```bash
MODEL=$(ls -d $B/out/<run>/v*/checkpoint-* | sort -t- -k2 -n | tail -1)
```

`-t-` 以 `-` 切**整条绝对路径**,第 2 段是 `gb64/v0` 这种非数字串;`-n` 把它们
全判成 0,键全相等后 GNU sort 退回整行字典序 —— 于是在
`checkpoint-{30,60,90,120,150,180,210,240,264}` 这组里选中 **90**。凡是存了
9 个存档的训练,选出来的必定是 90。

后果:**Bs-LoRA(47.81%)、Bs-gb64(45.81%)、B-gb64o(41.81%)三个已发布
的分数,跑的都是约 1 epoch 的权重,不是终点**。三个臂的 label、dashboard、
RESULTS.md 全部写着 3 epoch。错了一周。

### 为什么一周都没人发现

不是因为它藏得深,而是因为**流水线里没有任何一环把"我选了哪一步"说出来**。
`ls | sort | tail` 静默返回一个路径,vLLM 静默加载它,eval 静默出分。每一环都
"成功"了。发现它靠的是一次无关的巡查偶然 `grep` 了 serve 日志。

同一形状的错误在这个项目里已经出现过四次(检查器的 task_id 查轨迹、图片路径
相对 cwd、目录归属、图↔观察的折叠窗口)。四次的共同点都是:**一个做选择的
步骤没有把选择结果写下来**,于是错误只能靠结果离谱到被人注意才暴露。

### 定下的规矩

1. **做选择的代码必须把选择结果打进日志**,而且要连同判据一起打。
   `pick_ckpt.sh` 每次都往 stderr 写
   `[pick_ckpt] <run> policy=endpoint -> checkpoint-264 epoch=3.00 (9 available)`,
   在 Slurm 里就落进作业的 `.out`。
2. **判据从被选对象自己的文件里读,不写死。** 同样是"3 epoch",五次训练的终点
   分别是 264 / 267 / 90 / 708 / 450;epoch 只能从每个 checkpoint 自己的
   `trainer_state.json` 拿。任何写死的步数迟早会对上错误的 run。
3. **排序键要显式取出来再排,不要指望分隔符。**
   `awk -F'checkpoint-' '{print $NF, $0}' | sort -n`,不要 `sort -t- -k2 -n`。
4. **服务端要能被问"你到底加载了什么"**。vLLM 的 `/v1/models` 返回 `root` =
   真实权重路径;driver 起跑前 curl 一次写进结果目录的 `MODEL_BOUNDARY.json`,
   这一条当初就能立刻抓到本次错误。
5. **失败要响。** `pick_ckpt.sh` 在 glob 落空、policy 无匹配时 exit 1 并打
   FATAL,调用方一律 `|| exit 1`;宁可作业起不来,不要静默服务错权重。

### 现在的样子

`sft/sbatch/pick_ckpt.sh`,三种策略:

| policy | 含义 |
|---|---|
| `endpoint`(默认) | 步数最大的 checkpoint |
| `epoch:N` | 各 checkpoint 的 `trainer_state.json` 里 epoch 最接近 N 的那个 |
| `step:N` | 精确的 checkpoint-N,不存在就 FATAL |

13 个 serve/merge 脚本全部走它,`CKPT_POLICY` 环境变量可覆盖。要跑 ep1/ep2
对照时只改这一个变量,不改脚本。

### scrubbed 定时炸弹:解释器标准库被清理器吃掉(2026-08-19 凌晨)

现象:04:10 起 qwen-serve/.venv 所有 serve 3 秒暴毙,`init_fs_encoding: unknown
encoding UTF-8`;重装后又变 `No module named encodings.idna`——边装边被吃。
根因:**Tillicum 的 `~/.local` 整个软链到 `/gpfs/scrubbed/jiayuan/home/.local`**
(旧 netid 目录),uv 管理的 CPython 物理上住在 scrubbed 上,标准库里不常 import
的文件被自动清理(stdlib 202→64 项,encodings 125→35)。与安装动作无关。
修复:`UV_PYTHON_INSTALL_DIR=~/uv-python-real uv python install 3.12.13`(真实
home,不过 `~/.local` 软链),再把 `.venv/bin/python` 软链与 `pyvenv.cfg home=`
指过去;`import vllm` 验证后 serve 正常(248861)。**未动 3.11 与 `~/.local`**
(另一会话两个训练在用)。遗留:`~/.local` 下 uv 二进制、3.11、caches 仍在
scrubbed 上,同款炸弹未拆;.venv 的 site-packages 也在 scrubbed(日常访问频繁,
风险低但非零)。彻底解法=把 `~/.local` 迁回真实 home(需与所有在跑作业协调)。
排查时的误判也记一笔:曾把"lib 里新出现 itcl4.3.5"当成外部污染证据——实为
CPython 发行自带组件,4590 个文件的变更是自己的 reinstall。**先问"我自己刚做了
什么",再指控环境。**

## §Y 单题卡死:请求进了 ssh 隧道黑洞(2026-09-01,31 分钟换来的)

### 症状

`mixa9b` 的 eval100 跑到 47/100 时,dashboard 亮起 `STALLED?`。查下来:

| 查了什么 | 结果 |
|---|---|
| 三个 Docker VM 的 `/screenshot` | 全部 HTTP 200,<0.08 秒 |
| 隧道端点 `/v1/models` | HTTP 200 |
| runner 进程 | 全部活着,`poll_schedule_timeout`(等网络) |
| 另外两道题 | **正常推进**,traj 每分钟都在写 |
| **卡住那道** | traj 停在 09:47:57,31 分钟没动,无 result.txt |
| vLLM 侧 | 一直只报 `Running: 2 reqs`,**而有 3 个 env** |

### 机制

**请求发出去了,vLLM 从没收到。** 客户端那侧 socket 是 ESTAB(所以不是"连接断了"
那种能被察觉的失败),但 ssh 转发 channel 已经不通 —— 监听口还在、别的 channel
也正常,**只有这一条进了黑洞**。客户端不停重试、不停被对端关闭,`ss` 上堆到
**10 个 CLOSE-WAIT + 1 个 ESTAB**。

放大它的是我们自己设的 `OSWORLD_OPENAI_TIMEOUT=1800`(为 A100 的长生成设的,
见 `run_eval50_klone.sh` 里 600 秒导致整步重试的旧账)。每次重试都要空等 30 分钟。

### 为什么已有的看门狗防不住

`run_eval50_stock.sh` 的守卫只查**端点是否可达**(连续 3 分钟不通就杀 runner)。
这次端点一直 200。它也不查进度。

**全局静默同样防不住** —— 另外两道题一直在写 traj,任何"整体多久没动"的判据
都不会触发。

### 判据必须是「单题卡死」

装进 `chain_eval_rest.sh` / `chain_eval_lr.sh` 的看门狗,每 2 分钟:

```
全局最新 traj.jsonl 在 5 分钟内   （别的题还在动,排除整体停摆/serve 挂了）
且 某个"有 traj、无 result"的题 traj 超过 35 分钟没写
  -> 判为隧道黑洞:重建隧道 + 杀 runner,外层 for TRY 循环重起,skip-scored 续跑
```

`STALL_MIN=35` 是刻意大于 `OSWORLD_OPENAI_TIMEOUT` 的 30 分钟再加余量 ——
**不能误杀一次合法的长生成**。

### 杀 runner 会写出假 0 分(2026-09-01 追记,连带翻出两个已发布分数的旧账)

上面那个看门狗、以及任何手工 `kill` runner 的操作,都有一个**必须一起处理的
副作用**:在飞的题会以

```
"error": "can only test a child process"
run_multienv_qwen.py line 250, in run_env_tasks
```

崩掉,而 **harness 会给它写 `result.txt = 0.0`**。于是:

1. 那道题被记假 0;
2. **`skip-scored` 从此永远跳过它** —— 再也不会重跑;
3. 臂的分数被永久低估。

这是 §X「serve 断档灌 0」的同族:**失败被写成 0 分,而不是留空**。

**全盘扫下来,历史上已经中过三次:**

| 臂 | 题 | 时间 |
|---|---|---|
| `eval50-a6v` | thunderbird/9b7bc335、thunderbird/dd84e895 | 2026-08-23 |
| `eval50-a7` | multi_apps/c7c1e4c3 | 2026-08-23 |
| `eval50-mixa9b` | libreoffice_writer/88fe4b2d、adf5e2c3 | 2026-09-01(本次) |

**`a6v`(33.9%)与 `a7`(55.9%)这两个已发布的分数各含 1–2 个假 0**,重算前不要
直接引用。同一次扫描还看到两道 `a bytes-like object is required, not 'NoneType'`
和一道 `VM failed to become ready within timeout period` —— 同样是 harness 失败
被写成 0 分,同样会被 skip-scored 永久跳过。

**处置**:`result.txt` 与 `harness_error.json` 一起改名加 `.poisoned-by-*` 后缀
(**改名不删,证据留着**),下一趟 `skip-scored` 就会重跑它。看门狗现在杀完 runner
会 `sleep 15` 再自动做这件事;手工杀的话要自己做。

### 人工处置(看门狗装上之前那次)

1. 杀 runner(链的 `for TRY in 1 2 3 4 5` 会重起,`skip-scored` 跳过已出分的)
2. `ssh -S <sock> -O cancel -L <本地>:<节点>:<远端>` 再 `-O forward` 重建隧道
3. 探活 `/v1/models` 确认 200

### 排查时我自己犯的两个错,一并记下

- **`ls -l /proc/PID/fd | head -2` 把结果截断**,得出"没有任何进程持有这道题"的
  假结论,进而误判为"任务被遗弃"。实际是 `pid 75349` 持有它。**查 fd 不要截断。**
- **拿 `ss` 的一次快照下结论**:第一次看到目标进程 0 个 ESTAB,断言"连接全死";
  下一次它有 1 个 ESTAB。**socket 状态要连着看几次再判。**

## §X serve 断档灌 0 事故(2026-08-21,nocap261)

**机制**:serve 撞墙退出后,**runner 不会死** —— agent 的 API 调用失败被吞,
任务照常推进并全部记 0。断档窗口内产出的 result.txt 与真实 0 分无法区分,
只能靠完成时间戳事后隔离。np1e6 那次"20 秒自动接力"掩盖了这个洞:接力快
是因为 serve 排队快,不是因为 runner 会等。

**诱因**:应用户要求把 serve 墙钟 4h→9h,想让长臂一口气跑完。续班 serve
一直没起来,runner 在无 serve 状态跑掉 157 题全 0。

> **归因更正(2026-08-23,查 sacct 与 QOS 表)**:当时写的原因是"fairshare
> 低只能靠 backfill,4h 的缝塞得进、9h 塞不进"——**这是错的**。真实原因是
> **`interactive` 这个 QOS 的 MaxWall 就是 8 小时,9 小时是硬性违规**,作业
> 永远不会被调度。证据:那次的作业 `251923 eval4bnc interactive 09:00:00`
> 在 sacct 里 **`Start=None`、Elapsed 00:00:00**,从头到尾没启动过 —— 不是
> 排得慢,是压根不合法。同期 **`normal` QOS 上的 9 小时作业(232347/232348/
> 252373/252375)全部 Submit 与 Start 同一秒启动**。
>
> 按 GPU 规模拆开的排队等待(2026-08-18 起,sacct 实测):
>
> | QOS × 规模 | n | 中位 | p90 | 最长 |
> |---|---|---|---|---|
> | `normal` / 1 卡 | 8 | 1 秒 | 2 秒 | **2 秒** |
> | `interactive` / 1 卡 | 65 | 1 秒 | 669 秒 | **29407 秒(8.2 小时)** |
> | `normal` / 16 卡 | 17 | 258 秒 | 25440 秒 | 34247 秒 |
>
> **单卡 serve 在 `normal` 上从没等超过 2 秒**;反倒是 `interactive`
> (MaxJobsPU=2,撞上限就得排)出现过 8.2 小时等待。那些 9.5 小时长等待
> 全是 16 卡训练作业,与 serve 不可比。

**处置**:①按 result.txt mtime ≥ serve 死点 + 得分 0 隔离 157 题(mv 到
poisoned 目录,不删);②隔离目录命名**不能匹配** driver 的
`eval50-<arm>-*` glob(第一次命名 `eval50-...-poisoned` 被 driver 当最新
结果目录认走,已改 `poisoned-eval-...`);③墙钟回 4h;④driver 重启后
凭 skip-scored 语义补跑。

**同夜续集(9B 首飞,08-22 凌晨)**:复制 serve 脚本时一条 sed 把 vLLM
端口改到 8025,验证时 `diff | head -12` 恰好截掉了端口那个 hunk,误判
"sed 没生效"——vLLM 绑 8025、隧道指 8023,两侧各自"正常"。排障链:
vLLM 日志 startup complete → 隧道日志 connection refused → 对质节点一致
→ 读 sbatch 原文才见 8025。**规矩:验证 diff/日志必须完整读或按关键词
grep,禁止 head 截断当全貌**(本项目第三次栽在"读了个开头就下结论")。

**第三幕:自续期指向别人的脚本(2026-08-22,同事在查别的事时发现)**。
serve 脚本靠 `#SBATCH --signal=B:USR1@600` 在撞墙前 10 分钟自提交后继,
提交的目标是变量 `$SELF`。我复制模板造新臂时 **`$SELF` 跟着复制**,于是
**7 个脚本指向别人**(img10 五个 + 9b-base-stock 指 4b-base-stock +
38-i 指 38)。后果链:a3 的 serve 绑 8053 供 hermes 权重 → 撞墙 → 后继
是 **nocap 脚本**、绑 8033 供 **nocap 权重** → runner 仍问 8053 →
**静默灌 0**。100 题面板 4.4h > 4h 墙,a1/a2/a3/a6v 必撞。

- **取证结论:历史数据未受污染** —— base9b 的 serve 跑 3:25:05 被 scancel、
  教师两次 2:09/1:55 被取消,**都没到 4h 墙、都没触发 trap**(sacct +
  日志无 successor 记录双证)。
- **根治**:全部 50 个 serve 脚本的 `SELF=` 换成**自引用**
  `scontrol show job $SLURM_JOB_ID` 取 Command,解析失败则置空并打
  FATAL(**宁可没有后继,也不要错误的后继**)。复制脚本时不可能再写错。
  已实测:对真实作业解析出正确路径。备份 `.bak-self-20260822/`。
- 同源残留一并修:a 系列日志里写死的 `bind=127.0.0.1:8033` 改成各自真实
  端口 —— 照日志排错会查错端口(9B 首飞那次就吃过端口不一致的亏)。
- **补扫(同事复核发现)**:我第一遍用 `serve-chain-*.sbatch` 作 glob,
  漏掉了不带该前缀的 `serve-3vl-base.sbatch`(它指向教师脚本)。
  **扫描范围写窄本身就是同一族错误** —— 二次全库扫 `*.sbatch` 补修 2 个,
  现全库 0 处字面 SELF。顺带把 a5v(已退役)的端口从 8054 挪到 8055,
  与在链的 a6v 解冲突;在链五臂端口互不相同已核。

**三层形状的 serve 校验(2026-08-22 落成,一层比一层深)**:
1. **名字**:vLLM 报的 served id 必须包含该臂期望名(整词匹配,子串不算);
   空期望 / 空应答 / 不匹配一律 FATAL —— 断言自身 fail closed。
2. **权重路径**:vLLM 报的 `root` 必须落在该臂 `EXPECT_ROOT` 前缀下。
   **名字断言结构上抓不到这一层** —— served 名写死在 sbatch、而权重路径
   可以来自别处(a6v 从 pick 文件读),于是"对的名字挂错的权重"会通过
   名字检查。名字查一致性,路径查正确性,是两个不同的问题。
   未声明 EXPECT_ROOT 的臂**打印 NOTE**,不静默跳过(未断言的臂应当在
   日志里看起来就是未断言)。
3. **evaluator 静态闸**:任务集全部判分函数在 runner venv 上可解析。

**VM 容器泄漏(2026-08-22)**:一个 08-21 04:35 的容器活了 39 小时、占
2.9GB(22GB 上限的 14%),端口 5000 零连接、无属主 runner —— 几乎肯定是
当天多次 `pkill -9` 换链时清理路径被跳过。`docker stop`(非 rm,可复活)
后可用内存 9→11GB,在跑的 kGh 无影响。其余历史容器都是正常 Exited,
不占内存,**非系统性**。驱动加了发射前 NOTE:起臂时若已有运行中容器就
打印(不 FATAL —— 陈旧 VM 不污染结果,只饿死它们;但 39 小时的沉默正是
它长大的原因)。

**排队被自己人挤(2026-08-23,eval 停摆 15 小时的诊断)**:a2 的 serve
只要 1 卡 4 小时,却被 Slurm 估到 15 小时后才开始。三条实测:
①**全分区零空闲 GPU** —— `mix` 节点是 CPU 有余、8 张卡全占,所以"小作业
容易 backfill"这个我常用的假设**在满载时不成立**;②a2 前面有 **16 个
作业**,我们自己的只占 1 个(h128),撤掉它只能从第 16 位挪到第 15 位;
③根因是 **fairshare = 0.001333**(RawUsage 3.64 亿、占账号 **48.5%**)——
**是我们挤了整个账号,不是训练挤了评测**。
**唯一可控的是自己作业之间的相对顺序**(纯按提交时间定):**要 eval 优先,
就先交 serve 再交训练**。错峰、"提交前看队列"都改不了 fairshare。

**方法论(与同事对练出的五条判据,详见 sft/DATA_PIPELINE §9.2)**:
①先列配置引用谁再核;②能自引用别写死,解析失败 FATAL;③日志地址与真实
参数对齐;④先宽后窄扫;⑤**检查要形状互补,不要数量叠加** —— 两个同构的
检查只是把运气翻倍。本节三层校验就是⑤的落地:名字/路径/判分函数分别回答
不同的问题,任何一层都覆盖不了另一层。

**修法落地(2026-08-23):serve-gap 守卫**。驱动本来就有"端点不在就等
30 小时、重跑跳过已判分任务"的循环 —— **缺的只是让 runner 察觉**。现在
runner 旁边跑一个守卫:端点连续 3 分钟不可达就杀掉 runner,交还给那个
等待-续跑循环。**守卫让滚墙变安全。**

> **规矩修订(2026-08-23)**:原文写"刻意不用加长墙钟,因为 9 小时那次
> fairshare 下排不上"——归因已更正(见上),9 小时那次是撞 `interactive`
> 的 8 小时 QOS 上限,不是排队。**长墙本身没有问题,选错 QOS 才有问题。**
> 可用 QOS 的 MaxWall:`interactive` 8h(优先级 35,MaxJobsPU 2)、
> `normal` 24h(优先级 35→25)、`debug` 1h。要跑超过 8 小时,换
> `--qos=normal` 即可,**不要在 `interactive` 上写 >8h 的墙**。

**关于"提前把后继 serve 挂上去攒优先级"**:不成立。`PriorityFlags` 为空
(没有 `ACCRUE_ALWAYS`),**依赖未满足期间不累积年龄优先级**,提前挂着一分
不涨。而且优先级本就不是瓶颈:fairshare 0.001333 × 权重 1000 = **1.3 分**,
interactive 与 normal 的 QOS 差 (35−25)/10000 × 5000 = **5 分**,都可忽略;
单卡作业能秒起是因为**有空闲卡**,不是因为优先级高。

**规矩**:
1. **要跑长就换 QOS 拿长墙,不要在 `interactive` 上写超 8h 的墙**;
   滚墙仍是短臂的默认,守卫保证滚墙安全;
2. 监控必须盯 **"runner 活 + serve 不在 RUNNING"** 这个组合态(已加
   SERVE-GAP 告警,连续两拍才响);告警后的正确处置是**杀 runner**,
   driver 会在 serve 就绪后重启它,已计分任务不受影响;
3. 断档窗口的 0 分是**毒数据**,任何汇总前先查各臂分数按完成时间的分桶。

## Mac 侧临时端口耗尽:会伪装成「Tailscale 挂了」(2026-08-28,一次全链路中断的学费)

**症状**:`tailscale status` 报 `failed to connect to local Tailscale service; is
Tailscale running?`,`*.ts.net` 全部解析失败,`ssh osworld-windows` 断,整条
Mac→Windows→WSL 工作链停摆。但进程其实都活着:Tailscale.app 在跑、
network-extension 在跑、系统扩展 `systemextensionsctl list` 显示
`[activated enabled]`。**照着表象去修 Tailscale 会全程走错方向。**

**真因**:Mac 的临时端口池被 TIME_WAIT 占满,内核无法为出站 TCP 分配源端口
(`EADDRNOTAVAIL`)。因果链:

```
TIME_WAIT 占满端口池 → 出站 TCP 全部失败 → Tailscale 连不上 controlplane
  → tailscaled 后端初始化不完 → 从不创建 /var/run/tailscaled.socket
  → CLI 报 "is Tailscale running?" → MagicDNS 死 → *.ts.net 解析不了 → ssh 断
```

**Tailscale 是受害者不是肇事者**,它只是第一个大声喊出来的。

实测数字:TIME_WAIT **16,483** 对端口池 `49152–65535` = **16,384 个**,100% 占满。
消退极慢 —— 20 秒只过期 1 个(用条目指纹对比测出来:共同 16506 / 新增 8 /
消失 1),等自愈要好几天。

**最大来源是我们自己的工作流**:3,035 条打向 `100.113.98.76:2222`,即
osworld-windows 的 WSL SSH,走 Tailscale 隧道。**大量短命 ssh 把端口抽干,
反过来掐死了承载这些 ssh 的 Tailscale。** 其余为微信(腾讯云 43.x/101.34/
203.205 段,约 3k)、Anthropic API、Cloudflare、IMAP 等叠加凑够 16k。

### 判别顺序(别一上来修 Tailscale)

```bash
# ① ping 通 ≠ 网络好。ICMP 不占用源端口,必须单独测 TCP
ping -c 2 8.8.8.8
curl -sS -o /dev/null -w "%{http_code}\n" --max-time 8 https://example.com

# ② TIME_WAIT 数量 vs 端口池容量,两者接近即确诊
netstat -an -p tcp | grep -c TIME_WAIT
sysctl net.inet.ip.portrange.first net.inet.ip.portrange.last

# ③ 谁干的:看对端分布
netstat -an -p tcp | grep TIME_WAIT | awk '{print $5}' | sort | uniq -c | sort -rn | head -20

# ④ Tailscale 的真实报错在统一日志里,CLI 只会说"我连不上自己"
#    注意 zsh 有同名 log 内建,必须写绝对路径 /usr/bin/log
/usr/bin/log show --last 10m --predicate 'eventMessage CONTAINS[c] "ailscale"' --style compact | tail -30
```

**关键判据**:日志里对**所有**目标(十几台 derp + controlplane + logtail)一律报
`can't assign requested address`(IPv4)或 `no route to host`(IPv6),而不是集中在
某个地址 —— 全目标失败 = 本地端口问题,不是对端或网络问题。

### 修复(秒级见效)

```bash
sudo sysctl -w net.inet.ip.portrange.first=16384   # 端口池 16,384 -> 49,152 个
```

思路是**绕开**卡住的 TIME_WAIT 而不是等它们过期。执行后立刻 `curl` 返回 200,
Tailscale 自己重新连上,**不需要重新登录**(profile 仍在;期间 `tailscale status`
会显示 "You are logged out",那是端口耗尽期的历史错误,不用管它)。

不够就再加 `sudo sysctl -w net.inet.tcp.msl=1000`(TIME_WAIT 30s→2s);
都无效就重启 Mac。

**这两条都是运行时参数,重启后恢复默认(portrange.first=49152)。不是永久修复。**

### 预防(2026-08-28 已落实,不是待办)

- **Mac `~/.ssh/config` 已开启连接复用。** 此前 tillicum1/2、hyak 三段是注释状态,
  而 `osworld-windows` 段**连注释模板都没有** —— 那正是 3,035 条 TIME_WAIT 的来源:
  每条 `ssh osworld-windows` 都新建一条 TCP,批量查状态时连接数 = 命令条数。
  现四段统一为 `ServerAliveInterval 60` + `ControlMaster auto` +
  `ControlPath ~/.ssh/sockets/%C` + `ControlPersist 86400`。
- **`ControlPath` 用 `%C`(哈希)而不是 `%r@%h-%p`**:osworld-windows 的
  `User "Daniel Yan"` 含空格,`%r` 会把空格带进 socket 文件路径;`%C` 是固定 40 位
  十六进制,也不会撞 macOS unix socket 路径 104 字节上限。
- **实测**:连续 5 次 `ssh osworld-windows`,到 `100.113.98.76:2222` 的 TIME_WAIT
  **增加 0 条**(3051→3051),改动前是每次 +1。备份 `~/.ssh/config.bak-20260828`。
- **代价**:master 连接保持 24h。换网络(校园网↔家里)后旧 master 会僵死、让后续
  ssh 卡住 —— `ssh -O check <host>` 查健康,`ssh -O exit <host>` 清掉重建。
- 顺带收益:tillicum 走复用后不必反复过 Duo(与 §4 的 WSL→Tillicum 链路同理)。
- **「一次 ssh 只查一件事」这条规矩在没有连接复用时会变成放大器** —— 现已配套,
  两条规矩必须同时成立。
- 轮询循环必须带 sleep,并确认退出条件覆盖失败态(否则空转刷连接)。

### 2026-08-30 复发:同病不同阶段,`portrange` 那一招已经用完了

**症状**:用户手动 `ssh osworld-windows` 报 `Can't assign requested address`,
`git push` 同样失败;而 **Claude 这边一切正常**。

**判别的关键在这个不对称**:能用的那一方是**骑在已建立的 ControlMaster 上**,
不需要新端口;要新建连接的一方直接撞墙。所以"我这儿好好的"不能作为"没坏"的证据。

```
TIME_WAIT                    49,803
portrange.first–last         16384–65535 = 49,152 个
→ 49,803 > 49,152,溢出,不是"逼近"
```

**⚠ 上一节那条救命命令这次没得用**:`portrange.first` **已经是 16384**
(08-28 那次设的,一直没重启所以还在),范围已经开到最大。下一级杠杆只剩
`net.inet.tcp.msl`(15000 → TIME_WAIT 活 2×MSL = 30 秒)。

**这次的主因不是我们**。按对端归类 49,796 条:

| 条数 | 对端 |
|---:|---|
| 6944 | 43.130.30.247 |
| 4746 | Cloudflare 172.64.155.209 |
| **3788** | **Tailscale 100.113.98.76 —— 我们的 ssh** |
| 3469 | Cloudflare 104.18.32.47 |
| 3163 | Microsoft 13.107.5.93 |
| 2636 | Anthropic 160.79.104.10 —— Claude 自己 |

我们占约 7.6%。浏览器 / Slack / ChatGPT / VS Code 加上 Claude 本体是大头,
这台机器已开机 30 天。**所以"少 ssh"治不了本,得从容量和寿命两头下手。**

### 但我们确实贡献了一个可根治的 bug:僵死 socket 让复用静默失效

08-28 那节写了"换网络后旧 master 会僵死,`ssh -O exit` 清掉"——**只有手动处置**。
实际发生的是:socket 文件留着但主连接已死,此后每次 ssh 打印

```
ControlSocket <path> already exists, disabling multiplexing
```

**这是警告不是错误**,退出码 0,脚本照跑,于是整个 session 的每一次 ssh 都在
新建连接。2026-08-30 这一整天(数百次 ssh)都是这么跑的,没人发现。

**已落实的自动化(用户级,不需要 sudo)**:

- `~/bin/ssh-clean-stale-sockets.sh` —— 遍历 `~/.ssh/config` 里的 Host,
  `ssh -O check` 失败且 socket 文件存在则删除。`ssh -O check` 只和本地 socket
  说话、不产生网络连接,所以脚本本身不加重端口压力。
- `~/Library/LaunchAgents/local.ssh-clean-stale-sockets.plist` —— 每 300 秒跑一次,
  日志 `~/Library/Logs/ssh-clean-stale-sockets.log`。
- **双向实测过**:人为造一个僵死 socket(bind 后不 listen)→ 被清掉;
  同时两个活着的 master(tillicum2 pid 11765 / osworld-windows pid 87088)**没被误删**。

### 内核参数持久化(要 sudo,文件已备好在 `~/bin/local.netport-tuning.plist`)

**两个参数都是运行时的,重启即失效** —— 08-28 设的 `portrange.first=16384`
只是因为这台机器一直没重启才还在。重启后端口池会从 49,152 掉回 16,384 个,
比这次爆得更早。

```bash
sudo cp ~/bin/local.netport-tuning.plist /Library/LaunchDaemons/
sudo chown root:wheel /Library/LaunchDaemons/local.netport-tuning.plist
sudo chmod 644 /Library/LaunchDaemons/local.netport-tuning.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/local.netport-tuning.plist
sysctl net.inet.ip.portrange.first net.inet.tcp.msl   # 应为 16384 / 5000
```

它开机设两条:`portrange.first=16384`(端口池 16,384 → 49,152 个)、
`msl=5000`(TIME_WAIT 30 秒 → 10 秒,等效容量再乘三)。

**msl 的取舍**:RFC 建议 MSL=2 分钟,macOS 默认已经激进到 15 秒;降到 5 秒的
理论风险是旧连接的重复报文被投递给复用同一四元组的新连接,现代 TCP 有
timestamps/PAWS 兜底,实践中 10 秒 TIME_WAIT 是常见调优。**如果这台机器
将来要跑对乱序极敏感的长连接,把这一条去掉只留 portrange。**
