# RL 训练 VM 的环境配置

> 本文件是 RL 训练用 VM 环境的唯一记录：用哪个镜像、里面装了什么、为什么装、哪些故意不装、bridge 怎么跑题、怎么复查。
> 题库构成见 `RL_TASK_POOL.md`；VM 主机、relay、并发见 `RL_ENV_PLAN.md`。
> 代码：slime-cua 分支 `pool-expand`，`examples/cua_desktop/vm/`：`image/`(镜像构建)、`worker_bridge.py`、`guest_census.py`。

## 1 一句话

训练 VM 用自己构建的镜像 **`Ubuntu-cuagym-v1.qcow2`**：在 OSWorld 的 `Ubuntu.qcow2`(Ubuntu 22.04.3，Python 3.10.12)之上，装好 CUA-Gym 题目的初始化和打分脚本要用的东西，合并成一个独立文件。
- 构建只做一次，用 `vm/image/build_image.py`。
- 两台 VM 主机的 `docker_vm_data/` 里各放一份，由 `vm_hosts.json` 的 `vm_path` 指向它。
- eval 继续用原版 `Ubuntu.qcow2`，评测条件不变。

这和 OSWorld 自己的做法相同：它也是一个装好应用的镜像，docker 以只读方式挂载，每台 VM 的写入落在各自的覆盖层。

## 2 为什么要自己做镜像(2026-10-03)

CUA-Gym 的题是在他们自己的 VM 上验证的，那个镜像没有公开：

| 来源 | 内容 |
|---|---|
| 论文 C.4.2(arXiv 2605.25624) | rollout 用 2,000 台 OSWorld VM，按任务 `config.json` 里的快照恢复；镜像**没公开** |
| 代码 `utils/env.py`、`.env.example` | 阿里云 ECS 私有镜像(`ALIYUN_IMAGE_ID`)，经他们内部的 `OSWorld-RL` 控制 |
| `vm_requirements.txt` | 40 个包，没有版本号，代码里没有任何地方引用。**它不代表他们的镜像**：其中有 pytest，但 `04a48571` 的打分脚本注释写的是"初始环境里没有 pytest" |
| `utils/reward_judge.py` | 部分题调大模型打分。**不用**(用户 10-03："不要管它那个大模型评分的部分")，这 46 道题在 rollout 前跳过(`skipped_llm_judge`) |

在这之前，我们是在每台 VM 开机时现场补装(10-03 的 3e5eae1 版和中间版本)，问题很多：
- 开机多 262 秒，而且依赖外网，当天 apt 让开机失败了两次；
- 对脚本和 agent 两套可见性(私有库目录 + PYTHONPATH + sitecustomize + .pth)，很绕；
- 替身命令、写死的清单散落在 bridge 里；
- 预装的包和"让 agent 自己装"的题冲突(`04a48571` 初始状态就得 0.2 分)。

用户 10-03 决定"直接做镜像"，上面这些全部删除。

## 3 装什么：一条规则

**装题目的初始化和打分脚本要用的；不装题目要求 agent 自己去装的。**

依据是对全题库脚本的扫描，加上在真 VM 上的探测(第 7 节)，不靠猜，也不照搬官方清单。

### 3.1 Python 库(`image/requirements.txt`，55 个，装进系统 Python 的 `/usr/local/lib/python3.10/dist-packages`，agent 也能用)

| 类别 | 包 | 谁要 |
|---|---|---|
| 办公文档 | openpyxl、python-docx、python-pptx、XlsxWriter、odfpy、ezodf、xlwt、xlrd、dbf | 1,699 个脚本 import openpyxl，1,165 个 import docx |
| PDF | PyMuPDF(fitz/pymupdf)、PyPDF2、pypdf、pikepdf、fpdf2、pdfminer.six、pdfplumber、pdfrw、img2pdf | 479 + 167 import pymupdf/fitz |
| 表格与图像 | pandas、scikit-image、opencv-python-headless、gimpformats | 7 个打分脚本用 `skimage.metrics.structural_similarity`；GIMP 题读 .xcf |
| 媒体与其他 | mutagen、piexif、pygame、pytesseract、musicbrainzngs、playwright、toml、tomli、psutil、Babel、bibtexparser、rispy | 脚本 import，或初始化时自己 pip 安装。42 道题先检查 playwright，缺了就现场装 |

- 每个包连同依赖都固定版本：在本机为 cp310 manylinux 求解，用镜像里已有的包作约束。
- 系统 apt 装的 cryptography、PyYAML、cffi 保持原版本，系统工具要用它们。
- 有几个包在 `/usr/local` 里的版本比系统 apt 版本新：scipy 1.8 → 1.15(scikit-image 要求)、python-dateutil、pikepdf。准确清单见镜像的 manifest。

### 3.2 Ubuntu 包与其他(`image/packages.txt` 23 个 + 下面三项)

| 包 | 用途(题数为脚本里出现该命令的题数) |
|---|---|
| imagemagick | `convert`/`identify`(12) |
| xcftools | `xcf2png`/`xcfinfo`：GIMP 题的打分脚本用它读 .xcf(11)。Ubuntu 20.04 之后不再收录，装 focal 的安全更新版 deb(只依赖 libc6、libpng16-16) |
| xterm、xclip、xsel、xdotool、jq、qpdf、sox、flac、id3v2、img2pdf、libjpeg-turbo-progs、tesseract-ocr | 初始化和打分脚本里的工具 |
| inkscape、audacity、easytag、kid3-qt、kid3-cli、picard、feh、playerctl | 题目要打开的应用 |
| sysstat(`sar`/`iostat`)、tmux | 题目要求 agent 用这些工具，初始化脚本假定已安装 |
| Node v20.20.2(装到 `/usr/local`) | 17 道题的初始化脚本找 node 18+；Ubuntu 自带的是 12。版本与模拟网站一致 |
| `/usr/local/bin/chromium`、`chromium-browser` → google-chrome | 镜像里只有 Chrome，初始化脚本会启动 chromium |
| `/etc/sudo.conf` 的 `Path askpass` | 初始化脚本调 `sudo` 时不带 `-S`，也没有终端。有了 askpass，sudo 没终端时自动应答密码；agent 在终端里用 sudo 照常要输密码 |

### 3.3 故意不装的

| 不装 | 原因 |
|---|---|
| pytest、fastapi、uvicorn、Django、SQLAlchemy、pydantic、httpx、redis 等 | 没有任何脚本 import 它们；pytest 有 16 道题、fastapi 有 9 道题是让 agent 自己装，打分里有"已安装"这一项 |
| torch、openai-whisper、spacy、datasets | 题目让 agent 装 |
| black、flake8、isort、mypy、virtualenv、pandoc、pdflatex、poetry | 同上，开发工具类 |
| docker、go、rust、java/maven、数据库服务 | 开发环境题的初始化脚本自己装，或者就是任务本身 |
| pyhanko(1 道题) | 新版要求 requests ≥2.31，会替换 1,476 个脚本用的 requests；旧版依赖的包没有 wheel |
| `reward_judge` | 不用大模型评分 |

## 4 镜像怎么构建

```bash
# 在 VM 主机上，用 harness 的 python(要有 docker、requests)，需要一台 VM 的余量
IMAGE_COMMIT=<提交号> python3 image/build_image.py <原 Ubuntu.qcow2> <新 .qcow2>
```

流程：
1. 起一个构建用的容器，原镜像只读挂载；
2. VM 里跑 `provision.sh`，里面带检查：sudo 自动应答、命令都在、21 个库能 import，任何一项不过构建就失败；
3. 记录清单(`<新镜像>.manifest.txt`：提交号、node、chrome、pip、dpkg 的每个包和版本)；
4. 正常关机，取出容器的覆盖层 `/boot.qcow2`，用 `qemu-img rebase` + `convert` 和原镜像合并成独立文件。

v1 实测(Windows，10-03)：开机 21 秒，安装 191 秒，覆盖层 2.0 GB，合并 210 秒，成品 22.8 GiB。

两台主机各自构建，不拷贝。走 Tailscale 拷贝只有约 7 MB/s，24 GB 要一个小时；构建只要约 10 分钟。两边的 manifest 逐行比对，确认内容一致。

坑：
- VM 刚开机时 packagekitd 会占住 apt 的列表锁，`DPkg::Lock::Timeout` 不管这个锁，所以 `apt-get update` 要重试(`d355208`)；
- 镜像里 Google Chrome 源的签名密钥已过期，`apt-get update` 只打警告，不影响。

## 5 bridge 怎么跑一道 CUA-Gym 题

1. **从快照恢复 VM**。快照在容器开机后马上保存，之后每道题都从它恢复，25–37 秒。
2. **按题目的 config 步骤初始化**：上传文件、执行脚本、打开文件、等待。模拟网站地址(`__CUA_GYM_<站点>_URL__`)替换成本机的站点。
   - sh 脚本里多出来的单独一行 heredoc 结束标记(如最后一行 `EOF`)先删掉，全题库 12 道有这个问题。
   - **执行步骤脱离 VM 服务运行**：VM 服务的 `/execute` 写死了 120 秒超时，而且不理会请求里的 timeout(OSWorld `desktop_env/server/main.py`)。所以先把命令放到后台运行，输出写文件，退出码写 `.rc` 文件，每 2 秒查一次。每步上限 300 秒(题目可用 `setup_timeout` 覆盖)。342296 里有 9 次 reset 就是撞上这个限制失败的。
3. **算初始分 r0**：在初始状态跑一次 `reward.py`。r0 > 0 时，这条轨迹在第一步之前就结束(`initial_state_credit`)。
4. **打分**：`reward.py` 最后一行 `REWARD: x` 就是分数。
   - 老版本的打分脚本检查失败时会直接 return，不打印这一行(如 `6d15f577` 只打印"✗ Missing file")。退出码 0 且没有 `REWARD` 行，记 0 分。
   - 退出码非 0，或输出里有 Traceback、ModuleNotFoundError、ImportError，算 `GraderError`：不重试，VM 保留，这条轨迹丢弃，记为 `grader_error`。CUA-Gym 的打分脚本在初始状态和标准答案状态上都验证过，所以崩溃多半说明镜像还缺东西，要修的是镜像，不是把题藏起来。
5. **题目自己的错只付一次代价**(`skip_tasks.py`，`<save>/cua_skip_tasks.jsonl`)：
   - 记进名单、以后不再抽的题：全 0(`zero`)、初始化脚本失败(`task_setup_error`，`TaskSetupError`：不重试、不换 VM，并记下错误信息，换镜像后可以审查)、初始状态就有分(`initial_state_credit`)。
   - 已知的坏题(10-03 验证)：`544b7d84` bash 语法错误；`5cca1ce3` 时区解析失败；`554cc85b` 打分太宽，初始就给 0.8；`ca775249` 等 5 道找不到 `site-packages` 目录(Ubuntu 只有 `dist-packages`)。
6. **只有 reset 能开新连接**(`worker.py`)：连接断了以后，step 不会悄悄换一个新 bridge。342296 里 relay 重启后，几条 step 被发到没 reset 过的 bridge，报 `AttributeError: _finished`。

## 6 VM 泄漏(10-03 的主要拖慢原因)与清理

**现象(342296)**：
- 工作站上限 8 台 VM，实际跑到 31 台；8 GB swap 全满，负载 37–52(20 线程)；
- 打分要 50 秒(正常 0.2 秒)，初始化要 120 秒；
- 8 台 VM 两小时只 reset 了 48 次，而 Windows 3–4 台做了 71 次。

**泄漏路径**(有日志为证)：
1. 旧代码在 DesktopEnv 的构造函数里现场 `pip install`；
2. 工作站一忙，安装超过 120 秒，HTTP 500；
3. 异常在构造函数里抛出，没有 env 对象可关，刚建的容器就留下了；
4. bridge 重试又建一台新容器(端口 5006 → 5008 → …… → 5019)，失败又漏一台；
5. 漏的容器让主机更忙，更容易超时。

另一种：删容器时 docker 接口超时，容器停了但没删(每台主机各 10 个已停止的容器)。删容器没带卷，又留下了数百个匿名卷。

**处理**：
- 10-03 人工清理(用户同意)：两次共删掉工作站 28 + 27 个、Windows 10 个 VM 容器，以及没有容器引用的匿名卷(Windows 434 个、工作站 358 个)。删除前确认过：都是我们的镜像、挂载我们的 VM 文件、没有活着的 bridge 在用、没有 eval 在跑。
- **从根上堵住**：
  1. 开机不再安装，第一条路径消失；
  2. 长命令都脱离 120 秒限制；
  3. 每个 bridge 把自己的容器 ID 写进 `/tmp/cuagym-vm-<pid>`；每次开机前，`_reap_orphans` 连同卷一起删掉"bridge 建的、已停止的"容器，以及"bridge 建的、超过 30 分钟、没有活着的 bridge 登记的"运行中容器。
     - 怎么判断是 bridge 建的：QEMU 带 QMP 参数(`ARGUMENTS=-qmp unix:/tmp/qmp.sock`)，只有 bridge 的快照功能会设，eval 的 VM 没有，所以不会误伤 eval。
     - 30 分钟留给还在开机、还没来得及登记的 VM。
  4. 每次 reset 在主机 `/tmp` 下建的任务目录，换题和 bridge 退出时删掉(以前从不删，两台主机累计 1,128 个)。
- **部署注意**：旧代码的 bridge 不登记容器。新代码只能在所有 bridge 一起重启时上线(换作业时)，否则会把旧 bridge 正在用的 VM 当孤儿删掉。

**主机存储**：
- RL 在 VM 主机上的长期占用只有镜像文件：原版和 cuagym 版各约 24 GB。
- 每台运行中的 VM，覆盖层加内存快照约 2–5 GB，删容器时连卷一起删掉。
- 轨迹和数据都在 Tillicum 上。
- Windows 的 D 盘在放入 v1 镜像后只剩 25 GB。

## 7 怎么复查(题库或镜像变了就重跑)

```bash
# 1. 扫描：题库脚本 import 的模块、执行的命令、自己 pip/apt 装的包(任意机器，Python ≥3.10)
python3 vm/guest_census.py scan <train_ids.json> <题目目录> > needs.json
# 2. 探测：在 VM 主机的 bridge 目录里，用 bridge 的方式开一台 VM(OSWORLD_VM_PATH 指向要查的镜像)，
#    逐个 import / 查命令，缺的命令用 Ubuntu 的 command-not-found 数据库对应到包名
python3 guest_census.py probe needs.json > probe.json
```

| 对 rl-pool-20261003d(6,847 道)的探测 | 缺的模块(真正需要的) | 缺的命令(真实程序) |
|---|---|---|
| 原版 OSWorld 镜像 | dbf、ezodf、pdfminer、playwright、skimage、toml、xlwt、pyhanko | 28 个(convert、xcf2png、node、inkscape、xclip、xterm ……) |
| Ubuntu-cuagym-v1 | 只剩按规则不装的：pytest、datasets、spacy、pyhanko | 0 |

扫描出来的命令候选词约 4,200 个，大多是 heredoc 里 Python 代码的单词(`from`、`ws` ……)。能对应到 Ubuntu 包的 171 个，人工逐个看调用位置后定下第 3.2 节的清单。

## 8 验证(10-03，Windows，新镜像 + 新 bridge)

- **探测**(`guest_census.py probe`)：原版镜像缺的 28 个命令全部在了；模块只剩按规则不装的那几个。
- **19 道针对性的题**(覆盖每个新增依赖，加上已知问题题)：**15 道符合预期，0 个环境错误**。
  - 不符合的 4 道都是第 5 节列的坏题，训练时由跳过名单拦下：`93d4677f`(初始 0.2)、`554cc85b`(初始 0.8)、`544b7d84`(语法错误)、`5cca1ce3`(时区)。
  - `04a48571`(让 agent 装 pytest)初始分从 0.2 变成 0，新镜像不装 pytest。
  - `6d15f577`(老版打分脚本)以前 reset 要 485 秒还失败，现在正常记 0 分。
- **两台主机的镜像**各自构建，manifest 除标题行外逐行相同(2,206 行：node、Chrome、全部 pip 和 2,017 个 dpkg 包)。
- **冷启动**约 70 秒(旧方案现场安装要 369 秒)；从快照 reset 19–35 秒。
- **还没验证的路径**：OSWorld 题(训练中的 eval-50)切回原版镜像。`task_check.py` 没有真正跑 OSWorld 题。v2 的 eval 每 10 轮一次，第一次在第 10 轮，那之前要单独验证。

## 9 改动记录

- 2026-10-03(slime-cua `pool-expand`)：
  - `7e0db22`：镜像构建工具和清单；
  - `708a732`：bridge 改用镜像，删掉运行时安装层；长命令脱离 120 秒限制；没有 REWARD 行的规则和 `GraderError`；`skip_tasks.py`；VM 泄漏清理；只有 reset 能开新连接；
  - `d355208`：apt 列表锁重试；
  - `8f796f1`：OSWorld 题(eval-50)用原版镜像(`eval_vm_path`)，CUA-Gym 题用训练镜像，换题型时冷启动换镜像。
- 部署：10-03 17:3x，两台主机 `vmhosts.py push`，`bridge_host.sh check` 全部通过；342296 取消，342297 换新代码排队。
- 更早(`3e5eae1`)：多余的 heredoc 结束标记、`TaskSetupError` 不重试、跳过大模型评分题。
