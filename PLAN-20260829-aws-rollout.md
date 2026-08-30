# PLAN 2026-08-29 — 把 v14g 任务的教师 rollout 搬上 AWS

状态:**踩点全部完成,路线待用户拍板,零动作**(未起任何实例,未改任何 AWS 资源)。
本文是这次踩点的账本:所有数字都是实测或 DryRun 得来的,来源逐条标注。
定下路线后,命令进 `RUNBOOK.md`,本文只留设计与判据。

## 0 先说清楚:OSWorld 有两半,搬的是哪一半

跑一个 OSWorld 任务要两个东西:

| | 是什么 | 干什么 |
|---|---|---|
| **桌面环境(VM)** | 一台装了 LibreOffice / Chrome / GIMP / VLC 的 Ubuntu 桌面 | 被操作的对象。截图从这里来,鼠标键盘打到这里去 |
| **harness(runner)** | `run_multienv_qwen.py` 那个 python 进程 | 大脑。它拿截图 → 问教师模型 → 把动作打回 VM → 最后判分 |

两者靠 **HTTP** 通信(VM 的 5000 端口),**可以不在同一台机器上**。所以"搬上 AWS"有三种搬法:

```
路线②(推荐)   VM 在 AWS   ·  harness 留在你的 WSL      ← 只搬被控的那一半
路线①          VM 在 AWS   ·  harness 也在 AWS 一台 EC2   ← 两半都在 AWS,分开两台
路线③          VM 和 harness 都在 AWS 同一台 metal 机器上 ← 两半都在 AWS,挤一台
```

**教师模型(Qwen3.8-27B)三种路线都不动** —— 它在 Tillicum 的 H200 上,不上 AWS
(换机器起 serve 会毁掉与全部历史轨迹的可比性)。AWS 只提供"桌面",不提供"大脑"
也不提供"模型"。

## 0.1 结论(08-29 深夜定稿,与本文早先版本不同,见 §12 方案史)

**路线 ②′:VM 是 EC2,harness 也放一台 VPC 内的小 EC2(`m5.2xlarge`),
教师留 Tillicum。并发 25 路,主跑约 8 小时。**

两条决定性理由:

1. **5000 是无认证的任意代码执行端口,不该出 VPC。** 早先的 ② 要把它开给
   `205.175.106.79/32` —— 那是 **UW 的 NAT 出口**,后面可能挂着一批机器,
   而账号是 Zixian 的。**这个暴露该不该接受,判断权在他手里;②′ 让这个问题
   根本不存在,省掉一次不该由我们替他做的决定。**
2. **harness 离开 WSL → 与本地 544 完全解耦**,主跑不必等 544 收官,提早约 6 小时。
   ⚠ **提早来自解耦,不是来自少走闸** —— 冒烟 / Tier-2 40 条 / 拐点探测三件套
   全绿仍是主跑的硬前置。

标签(用户 08-29 定):`Contact=zixianm@allenai.org` / `Name=rollout`。
**reaper 的选择器 = `Name` 完整值 + 实例年龄双条件;绝不用 `Contact`
(会撞上他那 115 台)、绝不用 AMI(会撞上全账号同镜像实例)。**

## 1 已核实的账号事实(2026-08-29 实测,只读)

| 项 | 值 | 怎么得到的 |
|---|---|---|
| 账号 / 身份 | `153242493257` / `AWSReservedSSO_AllenNLP-User_.../zixianm` | `sts:GetCallerIdentity` |
| 区域 / AZ | `us-east-1` / **`us-east-1b`** | `describe_subnets` |
| 子网 | `subnet-f9f6699e`,VPC `vpc-84a800fe`,CIDR `172.31.0.0/20`,**自动分配公网 IP=True**,余 3914 IP | 同上 |
| 路由 | `0.0.0.0/0 → igw-2ba3bf53` → **公有子网**,VM 和 host 都能出网 | `describe_route_tables` |
| **配额** | 按需 Standard **9705 vCPU**(Spot 1152)| `service-quotas`,配额码 **`L-1216C47A`**(注意:不是文档常见的 `L-1216C47C`,那个查不到) |
| 官方 AMI | `ami-0d23263edb96951d8` = `osworld_client_image_30G_0719`,属主 `366177350716`,**公开可用** | `describe_images` |
| Ubuntu AMI(metal 用) | `ami-040dc3b259ece28c6`(jammy 22.04,`uefi-preferred`)| `describe_images` owner 099720109477 |

**配额不是约束。** 一台 96 核 metal 占 1%,20 台 t3.xlarge(80 核)占 0.8%。

### 安全组 `sg-0a0440f89cac11845` = `osworld-macu-sg`

描述字段自曝用途:**"OSWorld MACU control ports from beaker node"**。

```
入站(只有 4 条,全部来自同一个 /32):
  tcp 5000  <- 71.41.244.70/32      OSWorld 后端
  tcp 9222  <- 71.41.244.70/32      Chrome 调试
  tcp 8080  <- 71.41.244.70/32      VLC
  tcp 5910  <- 71.41.244.70/32      noVNC
出站: 全放行
无 SG 互引、无 IPv6、无前缀列表、无 22 端口、无 172.31.0.0/16
```

三条推论:

1. `71.41.244.70` 是 **AI2 Beaker 节点**的出口 —— Zixian 在 Beaker 上跑 harness,
   隔着公网驱动 VM。**所以他的 fork 一定能拿到公网 IP**(上游 `get_ip_address`
   只 return 私网,见 §5)。
2. 我们 WSL 的出口是 **`205.175.106.79`**,不在名单里 → **现状连不上任何 VM**。
3. **没有 `172.31.0.0/16` 规则** → 就算把 runner 放进 VPC 内也一样连不上。
   **无论走哪条路,SG 都得改。**

> 把 5000 只开给一个 `/32` 是对的做法。我 08-29 早先写的"路线 2 会把 RCE 端口
> 暴露公网、不建议"**作废** —— 白名单到 /32 时这个顾虑不成立。

---

## 2 权限地图(DryRun,零改动)

| 操作 | 结果 |
|---|---|
| `RunInstances` **不带标签** | ❌ **UnauthorizedOperation** |
| `RunInstances` **带 `Contact` 标签** | ✅ DryRunOperation |
| `RunInstances` 完整参数(照抄 OSWorld 形状)+ instance/volume 标签 | ✅ |
| `TerminateInstances` | ✅ |
| `AuthorizeSecurityGroupIngress` / `CreateSecurityGroup` | ✅ |
| metal × 6(Ubuntu AMI):m5d / c5d / m7i-24xl / c7i-24xl / m6i / i4i | ✅ 全通过 |

### 🔑 `Contact` 标签是起实例的硬门槛

AI2 用 IAM 条件(`aws:RequestTag/Contact` 一类)卡住 `RunInstances`。
**上游 OSWorld 的 `run_instances` 不打任何标签**(grep 过 `desktop_env/` `scripts/`:
无 `TagSpecifications`、无 `KeyName`),所以**照原样跑,一台都起不来**。

这同时解释了 Zixian 给的那个 `AWS_CONTACT_TAG` 变量:上游代码一个字都没读它,
是**他的 fork 加的**,而且不是为了方便清理,是为了能起得来。

### metal 报错的真相

`m5d.metal` / `c5d.metal` 配官方 OSWorld AMI 报 `InvalidParameterValue`:
**该 AMI 的 boot mode 是 UEFI,老一代 metal 不支持**。不是权限问题,
也不构成 metal 路线的障碍 —— metal 路线跑的是 Ubuntu + docker,换 AMI 后 6 种全通过。

---

## 3 ⚠️ 撞见的事:115 台孤儿实例,约 $2 万,仍在烧

查"谁在用这个 SG"时撞见的,**与我们的方案无关,但必须让 Zixian 知道**。

| | |
|---|---|
| 数量 | **115 台**(84× t3.xlarge + 31× t3.medium),全部 `Contact=zixianm@allenai.org` |
| 启动 | 2026-07-20 ~ 07-31,**已连续运行 29–41 天** |
| 镜像 | 官方 OSWorld AMI(`osworld-macu-qwen`)与 CoACT AMI(`osworld-macu`)|
| 实例费 | ≈ $14,468 |
| EBS 费 | ≈ $6,268(每卷 30G gp3 **带 4000 IOPS / 1000 MBps**,那个吞吐档很贵)|
| **合计** | **≈ $20,736** |
| **速率** | **≈ $21.95/小时 ≈ $527/天** |

账号总共 124 台在跑,**115 台是这个**。

OSWorld 的设计是每题销毁重建实例,**一台跑了 40 天的实例定义上就是孤儿**。
成因就是 `ENABLE_TTL=false` + 代码里没有任何 reaper —— 这是该风险的实证版本。

价格为 us-east-1 按需牌价估算(t3.xlarge $0.1664/h、t3.medium $0.0416/h;
gp3 $0.08/GB-月 + 超 3000 的 IOPS $0.005 + 超 125 的吞吐 $0.04/MBps-月),
AI2 若有 Savings Plan 实际更低,量级不变。

**我们没有动它们**,也不该动:不是我们的资源,销毁不可逆。

**对我们自己的教训:1796 条 = 1796 次实例起停,没有 reaper 绝不开跑。**

---

## 4 任务池的事实(1796 条,全部实测)

`ostg-v14/out/runs` 下 12 个 manifest,整包 128 MB。
权威分解:wave2 五段 1540(main s0–s3 941 + pins 138 + pending 72 + fill 292 +
fill2 97)+ v14-200 三段 220 + pilot40 36 = **1796**。
**1796 文件 / 1796 个 distinct id / 0 重复 id**(独立验证)。

- **setup 全自足**:execute 1618(base64 内联)+ open 847 + launch 605 +
  chrome_open_tabs 183 + activate_window 183。**`download` 步骤 0 条** —— VM 侧
  不需要访问我们任何 URL。
- **expected:`cloud_file` 970 / `rule` 615**。cloud_file 指向
  `http://127.0.0.1:8021/<set>/files/<slug>/gold/<name>`,
  `get_cloud_file`(`evaluators/getters/file.py:63`)在 **host 侧**下载。
  → **8021 那个 http.server 必须和 runner 同机**。现在活在 WSL
  (`python3 -m http.server 8021 --bind 127.0.0.1`,cwd=`ostg-v14/out/runs`)。
  **路线 ② 下它原地不动;①③ 必须跟着搬。**
- 判据:check_include_exclude 421 / compare_table 329 / compare_pptx 252 /
  compare_docx 198 / is_expected_url_pattern_match 183 / infeasible 182 /
  图像族 156 / compare_pdfs 40 / compare_videos 24 / check_mp3_meta 11。
- snapshot:calc 348 / chrome 302 / impress 267 / writer 254 / os 220 /
  gimp 164 / thunderbird 131 / vlc 82 / vs_code 28。
- `"proxy": true` **0 条** → `--enable_proxy` 对这批是空操作。
- 3 条用 sudo → 密码 provider 自动选(docker=`password`,AWS=`osworld-public-evaluation`,
  `desktop_env.py:130`),**别手动传 `--client_password`**。

### ⚠️ 14 个重复 slug 会挡住 merge

**slug 只有 1782 个,重了 14 个**,全部落在 wave2-main 分片之间 —— 正是
`RUNBOOK.md` 记的机制:slug 由内容派生,分片各自唯一、合并后同名,
`ostg.taskgen.merge` **直接拒绝、输出目录不写**。`out/runs/` 下还没有 `wave2-all`,
所以这一步还没跑到,一 merge 就撞。

```
assay-plate-col-widths-repair s1+s3   assay-protocol-step-renumber s2+s3
chrome-court-portal-autofill-off s1+s3  clinic-badge-tap-unlock s0+s2
cold-chain-breach-brief s0+s2         donor-portal-location-block s0+s2
ikea-returns-policy-page s0+s2        iso-9001-current-edition-page s2+s3
leave-balance-carryover-repair s2+s3  listings-deck-price-order s0+s2
pallet-weights-unit-fix s0+s2         torque-spec-deck-units s0+s2
vaccine-fridge-log-sheet s1+s2        viewing-feedback-summary-doc s0+s2
```

**处置 = cull(池 1796→1782,家族位移 ≤0.3pp)**,不改名(改名要动 9 对的
gold URL + `files/` 目录,是踩过坑的手术类型)。规则写死并**逐条打印**:
① 单方有 gold → 留有 gold 方;② 双方同态 → 留分片序小的(s0<s1<s2<s3);
③ 每条输出 `slug / kept(set,id) / dropped(set,id) / reason`,随 merge 报告归档。
(依据:`OPS.md`"选文件的代码必须打印它选了什么",一周错分换来的。)

### 老池 544:已改为本地跑,不再是 AWS 的事(08-29 晚变更)

原计划是"主池第 1 天通过率 ≥60% 才条件尾挂"。**08-29 晚用户改令:544 直接在
本地 3 VM 用 i10 冠军配置跑**(serve 267215,预计 ~20h,发车器
`tools_v11_reroll.sh`)。**544 = `v11-500-final` 444 + `v11-all` 100。**

08-29 18:5x 实测:隧道活着(18020 在监听,`ssh -L` 挂在 Tillicum 的 g019),
但 serve 尚未应答(27B 装载中);**runner 未起、容器 0 个、内存 20G 全空** ——
即 544 尚未真正开跑,在等 serve。

这批**不需要 8021**(实测):

| 池 | 目录 | 条数 | expected | cloud_file | 8021 |
|---|---|---|---|---|---|
| v11-500 | `os-simple-taskgen-v8/out/runs/v11-500-final` | 444 | rule 383 / 无 61 | **0** | **0** |
| v11-100 | `os-simple-taskgen-v8/out/runs/v11-all` | 100 | rule 89 / 无 11 | **0** | **0** |

gold-file 判据是 v14g(08-28)才长出来的,老池全是规则判据 → **8021 的 root 只需
覆盖 `ostg-v14/out/runs`**。

`v11-100` 的真身以 runner 自记为准(两条独立证据链):
```
qwen38-27b-local/v11-100-t1-20260814/args.json        -> .../out/runs/v11-all
qwen38-27b-local/v11-100-t1-rerun2-20260816/args.json -> .../out/runs/v11-all
```
`v11-cc` / `v11-fix8` 在任何 rollout 的 args.json 里从未出现。三者都是 100 条但
**形状不同**(v11-all 96 个 execute,另两个 126),选错就是换语料。

### ⚠️ 主池条数待对齐:我数 1796,用户说 1689

我的普查是遍历 `ostg-v14/out/runs` 下所有 `examples/**/*.json`:**1796 个文件、
1796 个 distinct id、0 重复 id**;cull 掉 14 个重复 slug 后 **1782**。
用户 08-29 晚提的是 **1689**,差 93/107 条。**开跑前必须对齐分母** ——
标签里要带条数,数错了以后没法追溯。

---

## 5 代码事实(决定路线的三条)

1. **`aws/provider.py::get_ip_address` 只 return `PrivateIpAddress`**,
   公网 IP 仅被打印成 VNC 链接;`desktop_env.py:207` 直接拿来当 `self.vm_ip`。
   → 上游代码只能在 VPC 内驱动。
2. **runner 的 `--use_public_ip` 是死的**:靠 `inspect.signature(DesktopEnv)` 探测,
   我们的 `desktop_env.py` 没这个参数 → 只打一行 warning 就忽略。
3. **每题一台新实例**:`reset()` → `revert_to_snapshot` = 销毁旧实例 +
   `run_instances` + 等 running。1796 条 = 1796 次起停;`stop_emulator` 也是
   terminate 不是 stop;不设 `KeyName`(**ssh 不进 VM,只能靠 5910 的 noVNC**)。

---

## 6 关键算术:WSL 的内存瓶颈会随 VM 上云一起消失

`OPS.md` §5 实测:单 env 边际 **4.61 GiB** = 容器 4.08–4.11(qemu 在容器内)
+ EnvProcess worker 0.52。19.53 GiB 可用 → 3 个封顶。

**走 aws provider 后,容器那 4.08 GB 不在本地了**:

```
0.66(runner 主进程) + 20 × 0.52(worker) + 1.0(系统基线) ≈ 12 GB  <  19.53 GiB
```

→ **同一台 WSL 能驱动 20 个 env**。这是路线 ② 成立的支点,也是我 08-29 白天
推荐 metal 时漏算的一笔账。

(注意 `OPS.md` 记的"runner 内存随时间爬"依然成立,20 env 下爬得更快;
对策仍是同 `result_dir` 重跑的 heal 机制。)

### 时间账

实测 **≈380 env-秒/题**(`eval50-t38i10-20260829`,3 env,50 题跨度 1.75h;
中位 130s、均值 280s,mtime 法是下界;均值 19.6 步 → ≈14–19 s/步)。

| 并发 | 1796 条墙钟 |
|---|---|
| 3(现状) | ≈63 h |
| 12 | ≈16 h |
| 20 | ≈9.5 h |
| 24 | ≈8 h |

**并发上限的真正天花板不是 AWS,是教师 serve** —— Tillicum 上单节点 vLLM。
3→20 的拐点从未测过。**开跑前先 6 → 12 → 24 三档各 20 分钟,量每步端到端
延迟的拐点**,拐点在哪定在哪。

### 资源边界:544 在本地跑期间,AWS 侧能并发多少

WSL 总可用 19.53 GiB。544 用 3 个本地 VM 时的稳态占用:

```
3 × 4.08(容器)+ 0.66(runner)+ 3 × 0.52(worker)+ 1.0(系统) ≈ 15.5 GB
剩余 ≈ 4.0 GB
```

我们的 AWS runner 只占 worker(VM 不在本地):`0.66 + N × 0.52 ≤ 4.0` → **N ≤ 6**,
且没有余量(`OPS.md` 记着 runner 内存会随时间爬)。**保守取 N ≤ 5。**

结论:544 跑完之前(约 08-30 下午),AWS 侧只能做
**Tier-2 判定(1 env)和 6 档拐点探测**;**全量 12–20 并发必须等 544 结束**。

serve 共用同一个 `eval38h20` 自续链,**不再起第二个 serve**。因此拐点探测量到的
是"在 544 的 3 路负载之上"的拐点 —— 这恰好也是生产时的真实状态,不用校正。

---

## 6.5 serve 容量:并发上限的实测反推(本次最重要的发现)

**结论先行:教师 serve 才是全局瓶颈,而"1 卡配 3 VM"早就是满的 ——
过去加 VM 一直不见变快,不是 VM 少,是那张卡满了。**

### 单 agent 吃掉多少 serve 容量

三个锚点(全部实测):

```
① 380 env-秒/题,均值 19.6 步        → 每 agent 每 19.4 秒发一次请求
② KV 占用 4.1%@3路 × 2,317,904 token → 每请求上下文 ≈ 31.7k token
③ Prefix cache hit rate = 0.0%       → 滑窗每步全量重算,零复用
```

→ **单 agent 持续占用 ≈ 1,650 prefill tok/s**

**交叉验证**:3 × 1,650 = 4,950;serve 日志按并发聚合的实测值是 **4,731** ✓

### 单卡与多卡容量

`srvdx8_*.out` / `serve38h20_*.out` 实测:

| 并发 | prefill tok/s | 生成 tok/s | 排队 | KV 占用 | prefix 命中 |
|---|---|---|---|---|---|
| 1 | 2,793 | 46.5 | 0.06 | 1.5% | **0.0%** |
| 2 | 3,381 | 54.2 | 0.07 | 2.7% | **0.0%** |
| 3 | 4,731 | 45.3 | 0.00 | 4.1% | **0.0%** |

单请求瞬时 prefill 5,400–6,100 tok/s → 取 6,000 → **3.6 agent/卡**。

| 配置 | 总吞吐 | 支持 agent | 1796 条墙钟 |
|---|---|---|---|
| 1 卡(历史) | 6,000 | 3.6 | 63 h |
| **8 卡(DP2×TP4,效率 0.8)** | **38,400** | **≈25** | **≈8 h** |
| 要喂饱 100 路 | 165,000 | 100 | 需约 34 张卡 ≈ 4.3 个整节点 |

**显存不是瓶颈**:单卡 KV cache 实测 **2,317,904 token**,3 路只占 4.1%,
单卡光显存能装约 70 路。卡在 **prefill 算力**。

### 8 卡实测压测(08-29 深夜,作业 267240,DP2×TP4)

合成负载,**每条请求灌唯一前缀强制真 prefill** —— 用相同 prompt 压会被 prefix cache
一路命中,量出来是假数字(生产里命中率实测 0%,见下)。

```
并发   墙钟s   prompt token   prefill tok/s   单请求s
 1     96.8       16,364            169        96.8   ← 首请求含 JIT 预热,弃
 4      3.3       65,456         19,905         2.8
 8      4.3      130,912         30,505         3.4
16      6.4      261,824         41,068         4.6   ← 拐点
25     10.6      409,100         38,643         7.5
40     16.5      654,560         39,673        11.5
```

- **8 卡 prefill 上限 ≈ 40,000 tok/s**(此前推算 38,400,**误差 4%**)
- 相对单卡 6,000 是 **6.7 倍** → TP4 效率约 0.83
- **拐点在 16 路**;之后总吞吐持平,加并发只让单请求排队变慢(4.6→7.5→11.5s)
- **25 路被实测确认**:40,000 ÷ 1,650 = 24 个 agent
- 墙钟:1796 × 19.6 步 × 32k ÷ 40,000 = **7.8 小时**

**已知偏差**:压测是纯文本 prompt,生产每条含 10 张图(2040 token/张),视觉编码器
开销未测到。生产日志 MM cache 命中率 90.9%,影响有限,但**真实吞吐可能略低于 40,000**。

KV 容量实测:8 卡 **14,128,181 + 13,941,155 ≈ 2,807 万 token**(单卡 232 万的
**12.1 倍** —— 超过 8 倍是因为 TP4 把权重切四份,每卡只放 1/4,省下的全给 KV)。
按 32k/请求算光显存能装约 870 路 → **显存彻底不是瓶颈**。

### 一个大杠杆(本 campaign 不碰)

**prefix 命中率 0% 是 i10 滑窗造成的** —— 超过 10 张图后丢最老那张,前缀失效,
后面全部重算。若上下文改成只追加,命中率可到 80–90%,**prefill 成本掉 5–10 倍,
比加 8 张卡还值**。但这会动刚锁定的 i10 冠军配置(七臂试点 +12pp),
**记为后续方向,本 campaign 不动**。

## 6.6 8 卡 serve 的两个坑(08-29 实测,均已知修法)

1. **TP=8 非法**:`config.json` 的 `num_key_value_heads = 4`,KV 头只有 4 个,
   TP 切不到 8(其他维度够:注意力头 24、线性 KV 头 16/48)。
   **8 卡只能是 DP=2 × TP=4。** TP4 改变归约顺序,与产出历史轨迹的 TP1 不是
   逐位一致 —— 同权重同精度同采样档,但**要记进 `MODEL_BOUNDARY.json`**。
2. **首次启动会超时**:DP2×TP4 的 torch.compile 超过 vLLM 默认的 600 秒
   `VLLM_ENGINE_READY_TIMEOUT_S`,两个 ApiServer 直接 TimeoutError 退出,
   而 EngineCore 还在编译 —— **Slurm 显示 RUNNING 但永远不会服务,占着 8 张卡**
   (作业 267225 即此,已判定为僵尸)。
   **修法**:sbatch 里加 `export VLLM_ENGINE_READY_TIMEOUT_S=3600`;
   编译缓存(`XDG_CACHE_HOME`)热了之后重启会快很多。

**serve 按需两段式提,不长期空占**:验证阶段 **4 卡**(13 路 × 1,650 ≈ 21k tok/s),
主跑阶段 **8 卡**。Slurm 报价 ≈ **$0.90/GPU-小时**(8 卡 20 小时报 $144),
且按 **requested** 计价 —— `--time` 别开得比需要的长。

---

## 7 路线对比(全部有实测支撑)

| | ① VPC 内 host + aws provider | ② **WSL 直驱公网 IP** | ③ metal + docker |
|---|---|---|---|
| 权限 | ✅ | ✅ | ✅ |
| 补丁 | Contact 标签 | Contact 标签 + 公网 IP(3 行) | Contact 标签(仅起 host)|
| SG 改动 | 加 SG 互引规则(不依赖 IP,最稳)| 加 `205.175.106.79/32` | 加一条 SSH |
| 要搬 | 全套 + 回传 15 GB | **零** | 全套 + 回传 15 GB |
| 镜像风险 | 有(970 条 gold)| 有 | **无** |
| 成本 | VM ≈$42 + host ≈$8 | **≈$42** | metal ≈$40 |

**推荐 ②。** 零搬迁(gold 服务不动、Tillicum 隧道不动、结果直接落
`results_generated/` 连 rsync 都省),补丁最小,成本最低。
已知风险:UW 出口 IP 变动(改一条 SG 规则即修,且有 heal 机制)。

**③ 是唯一对镜像风险免疫的**(1796 条是在 docker `Ubuntu.qcow2` 上 bake +
四道闸验的),代价是全套搬迁。若 §8 的等价性判定不过,退回 ③。

---

## 8 开跑前的硬前置:镜像等价性判定

970 条 gold 比对对 LibreOffice 序列化行为敏感(v14g 自己栽过 round-trip no-op)。
换成官方 AMI = 换 comparator 的输入分布。

**判定工具现成:Tier-2 闸** —— gold 在 VM 里过一遍 `soffice --convert-to` 重存后
必须仍是 1.0。**在 AWS AMI 上跑 40 条,约 $3、半小时**,过了才谈全量。

`taskgen/control.py:27` 已有 `--provider_name`,但 `--path_to_vm` 是 required、
`snapshot_name` 写死 `init_state` → 走 aws 要改两行(§9 补丁 3)。

---

## 9 待批准的改动(全部未落地,人话版)

四处改动。前两处是**改 OSWorld 自己的代码**,第三处是**新写一个小工具**,
第四处是**改我们自己 ostg 的一行参数**。按约定先给 diff,用户点头才落。

### C1 让起实例时带上标签(必需,不做则一台都起不来)

**现在的问题**:OSWorld 起 EC2 时不打任何标签,而 AI2 的 IAM 规定"没有
`Contact` 标签就不许起实例"(DryRun 实测:不带标签 ❌ 被拒,带了 ✅ 通过)。

**要改的**:`aws/manager.py::_allocate_vm` 和 `aws/provider.py::revert_to_snapshot`
里那个 `run_instances(...)` 的参数字典,加一段 `TagSpecifications`,值从环境变量读。
两处各加约 6 行,不动任何现有逻辑。

### C2 让 harness 拿到 VM 的公网地址(路线 ② 必需)

**现在的问题**:`aws/provider.py::get_ip_address` 拿到 VM 后,**只返回内网地址**
(公网地址仅被打印成一行 VNC 链接就丢掉了)。内网地址只有 AWS 内部能连,
你的 WSL 连不上。

**要改的**:那个函数的 `return` 加一个开关 —— 环境变量 `AWS_USE_PUBLIC_IP=true`
时返回公网地址,否则维持原样。**3 行,默认行为完全不变**,不开开关就是上游代码。

### C3 孤儿清理器(新写,约 40 行)

**为什么要**:OSWorld 每题销毁重建实例,runner 一崩,在飞的实例就没人管了 ——
账号里那 115 台空转 40 天、烧掉约 $2 万的实例就是这么来的。

**怎么写**:定时列出**带我们完整 `Name` 值**且**年龄超过阈值**的实例,
**先打印清单给人看,人点头才杀**(默认 dry-run,不自动执行)。
**选择器绝不用 `Contact`**(会撞上 Zixian 那 115 台)、**绝不用 AMI**
(会撞上全账号同镜像实例)。

### C4 让 Tier-2 判定能在 AWS 上跑(改两行)

**为什么要**:§8 的镜像等价性判定要用 `ostg/taskgen/control.py`,它现在只会
走本地 docker。

**要改的**:`--path_to_vm` 从必填改成选填;provider 是 aws 时,快照名取
`IMAGE_ID_MAP` 里的 AMI(照抄 `run_multienv_qwen.py:182-186` 已有的写法)。
在 ostg 的 v14 worktree 开分支,不落 main。

> 另一条路:Zixian 的 fork 里 C1、C2 都已经有了(他能起实例、能从 Beaker 连公网 IP,
> 说明两个补丁他都打过),直接要过来能省重写 + 少一份分歧。

## 9.5 环境搬运与版本控制(08-29 深夜实测,方案 B:Docker)

### 搬什么(实测大小)

| 项 | 大小 | 说明 |
|---|---|---|
| `desktop_env/` + `mm_agents/` + `scripts/` + 根目录 `.py` | **12 MB** | 真正的代码就这么点 |
| `.venv` | **7.4 GB** | Python 3.12.3,265 包 —— **判据的命脉** |
| `ostg-v14/out/runs` | 128 MB | 任务 + gold |

**不搬**:`results_generated/` 100 GB · `docker_vm_data/` 35 GB(qcow2,AWS 路线不用) ·
`results/` 5.4 GB · `synthetic_tasks/` 1.7 GB · `cache/` 1.3 GB · `logs/` 726 MB ·
各种 `*.tar.gz` / `*.bak` / `taskgen_*`。

### 为什么用 Docker 而不是 tar

venv 的 shebang 与 `pyvenv.cfg` 写死绝对路径 `/mnt/d/research/OSWorld/.venv`,
tar 方案得在目标机造出同名路径;venv 里几十个包带 `.so`(PIL/cv2/cryptography/
lxml/scipy),链接系统库,tar 方案还要手工对齐 apt 清单,**漏一个是运行时才炸**。
镜像把路径、系统库、可复现性一次冻住,digest 即版本号。

**构建位置**:WSL 本地盘(`/var/lib/docker`,余 904 GB),**不要用 `/mnt/d`** ——
9p 文件系统慢到 `du` 都会超时(实测两次 120s timeout)。
Docker 29.6.1 + buildx 已验证可用。

### 版本锁

```
OSWorld base   091f5ef1d5544bc74953c77875d5feb5bed30108  (v0.1.16-594-g091f5ef)
魔改文件       11 个(逐个 md5 见 §9.6)
未跟踪必需     desktop_env/evaluators/metrics/generated_tasks.py
               ← metrics/__init__.py:109 硬 import;1796 条虽不调用它的函数,
                 缺了整个 evaluator 包 import 失败,一条都跑不了。git diff 看不到它。
判据实现       table.py / docs.py / slides.py / general.py —— 全是上游原版未改
venv           openpyxl 3.1.5 · python-pptx 1.0.2 · python-docx 1.2.0 · Pillow 11.0.0
               pypdf 6.7.5 · PyMuPDF 1.27.1 · numpy 1.26.4 · scikit-image 0.26.0
```

### 运行时环境变量也是配置的一部分(从跑着的 544 进程 `/proc/*/environ` 掏出来的)

```
OSTG_TYPE_NO_SPLIT=1        多行 type 一条 typewrite 直发(kC 起的合并语义)
OSTG_NO_RECORD=1            关 guest 录屏 —— mp4 本来就是截断的且无人消费
OSWORLD_OPENAI_TIMEOUT=600  否则 130s 默认超时会系统性枪毙长思考
```

**漏设 `OSTG_NO_RECORD` 会让每题多烧 15 秒重试并产生无人使用的 mp4。**

### 版本对齐核验(已通过)

魔改文件最晚 mtime = `mm_agents/qwen/main.py` 08-29 00:09;
i10 冠军 eval 跑于 08-29 02:41 → **当前树 == 产出 eval 的树,零漂移**。

### 上线前必做的判据回归自检

挑 20 条历史已判分任务,把 result 与 gold 搬到新环境**只重跑 evaluator**,
分数必须逐条一致。这是唯一能在开跑前证明"两台机器算出同样分数"的检查,
专抓库版本漂移导致的 970 条 gold 静默错判。

## 9.6 harness 主机规格(实测定的)

`m5.2xlarge`(8 vCPU / 32 GB)+ **100 GB gp3 根盘**。

| | 需要 | 依据 |
|---|---|---|
| 内存 | 25 × 0.57 + 0.6 + 1.5 ≈ **16.4 GB** | `ps` 实测 worker RSS 0.56–0.59 GB |
| CPU 稳态 | ≈ **0.03 核** | 实测 runner 进程 %CPU 0.0–0.3(全程阻塞等模型) |
| CPU 突发 | ≈ 0.7 核 | 0.066 题/秒 × 评测器 5–10 秒(156 图像 + 40 pdf + 24 视频) |
| 磁盘 | ≈ 33 GB | 镜像 8 + 容器内 8 + 结果 15 + 任务 2 |

⚠ **默认根盘 8 GB 不够** —— 磁盘满的表现是"截图写不进去",看起来像网络问题,极难查。

**内存爬升不成立(实测推翻旧记录)**:`OPS.md` 记的"3 env 跑 5 小时吃掉 4 GB"是
v11 时代(20 图/fold10)测的。i10 把图数封顶 10,上下文有硬上界。544 跑 68 分钟
实测 RSS **不升反降**(657→575 / 594→591 / 567→564)。

## 9.7 已落地的三个补丁(08-29 深夜,全部带测试,均未进主干)

| 仓库 | 分支 | 提交 | 主干 |
|---|---|---|---|
| OSWorld | `aws-rollout` | `b80d825` 实例标签 · `3df1ef4` reaper | `main` 干净 |
| ostg | `awsgate`(新 worktree `/mnt/d/research/ostg-awsgate/`) | `9cc80c09` control 走 aws | `datagenv14` 未动 |

### b80d825 起实例时打标签

`aws/config.py` 新增 `instance_tag_specifications()`,`manager.py::_allocate_vm` 与
`provider.py::revert_to_snapshot` 各三行接上。**两个环境变量都为空时返回 `[]`,
请求体里不出现 `TagSpecifications` 键 —— 与上游逐字节一致。**
volume 也打标签,否则半死实例留下的 EBS 找不回来(那 115 台的卷费就是 $6,268)。

验收:默认 `[]` ✓ / instance+volume 都带 Contact+Name ✓ / IAM DryRun 放行 ✓
(无标签时是 `UnauthorizedOperation`)。

### 3df1ef4 reaper

选择器 = `Name` 精确值 **AND** 年龄,两个条件缺一不可。
**永不用 `Contact`**(我们按账号惯例填 `zixianm@allenai.org`,和那 115 台同值);
**永不用 AMI**(官方镜像公开,别人也在跑)。
护栏:拒绝空/通用 `--name`;`--max-kill` 默认 50;打印完整匹配清单**外加故意跳过的台数**;
不加 `--yes` 什么都不做。

验收(真账号,只读):`--name rollout` 匹配 **0**、124 台报为未触碰;
`--name osworld-macu-qwen` 匹配 **84** —— 所以那个 0 是真排除,不是匹配器坏了。
**两边都验才算数,只验前者无法区分"正确排除"与"永远返回 0"。**

### 9cc80c09 control 走 aws(比原计划多改了一件)

① `--path_to_vm` 改可选;② aws 时 `snapshot_name` 取 `IMAGE_ID_MAP` 的 AMI;
③ **`--client_password` 默认从 `"password"` 改成 `""`** ← 写的时候才发现:
`"password"` 是 **docker 镜像**的密码,**AWS AMI 是 `osworld-public-evaluation`**。
不改的话,1796 条里 3 条用 sudo 的任务会**静默失败**(判 0 分,看不出是密码问题)。
`""` 让 `DesktopEnv` 按 provider 自己选,docker 行为一字未变。

验收:用桩替换 `DesktopEnv`,**未启动任何 VM** —— docker 缺参数退出 2 并给出提示 ✓ /
aws 解析到 `ami-0d23263edb96951d8` 且不传 path_to_vm ✓ / docker 带参数时 kwargs 与改动前相同 ✓

## 9.8 判据回归自检(上线前的硬闸)

**目的**:证明新环境算出的分数与老环境逐位相同。库版本漂移会**静默错判 970 条
gold 任务**,而 Tier-2 闸抓不到这一层(它验的是镜像,不是宿主库)。

**设计**:不依赖历史缓存,直接用 v14g bake 阶段自己的两条不变量 ——
`score(gold, gold)` 与 `score(seed, gold)`,seed 从任务 JSON 里的 base64 还原。
脚本 `regress.py`,两个环境各跑一遍,**要求分数向量的 sha256 完全相同**。

**结果(08-29 21:30):WSL 与容器指纹完全一致 = `d32d9bccdb2b964c`** ✅
20 条覆盖 5 个判据族(pptx / table / docx / pdf / 图像),逐位相同;
连 `spectro-plate-contrast-log` 的 `ERR:UnidentifiedImageError` 都一样复现 ——
**连错误都一致,是等价性的更强证据**。候选池 932 条。

⚠ **第一次跑指纹对不上(`e85a02b7070bf9fa` vs `ffd7f215c292ccbf`),是测试脚本的
bug 不是环境漂移**:`os.walk` 顺序依赖文件系统(WSL 是 9p/NTFS,容器是 overlayfs),
不排序就取前 20 等于两边比了不同的样本。已改为**按 task id 排序后再取**。
这类"测量工具自己不确定"的坑,和选择器不打印是同一类。
10 条 `compare_table` 全为 `1.0 / 0.0`(判据自洽 + 空判防线双双成立)。

⚠ **图像族 `gold≡gold = 0.0` 是正确的,不是失败**:
`check_contrast_increase` / `check_image_mirror` 这类是**关系型**判据(问"相对原图
有没有变化"),gold 与自己比当然无变化。等值型判据才该是 1.0。
对 A/B 无影响 —— 要的是两边逐位相同,0.0 也是指纹的一部分。

## 9.9 Docker 镜像(已构建并通过等价性验收)

**`osworld-rollout:20260829` · 12.6 GB · `dbd9e87c68a3` · 构建耗时 4 分钟**

容器内自证:路径 `/mnt/d/research/OSWorld`、系统 python 3.12.3、venv python 3.12.3、
**265 个包版本与 WSL 逐个相同**、判据指纹 `d32d9bccdb2b964c` 与 WSL 一致。

### ⚠ 从 ssh 会话驱动 WSL Docker 必须带 `DOCKER_CONFIG`

`docker build` 会在 `FROM ubuntu:24.04` 就失败,报
`error getting credentials — A specified logon session does not exist`。
**拉的是公开镜像,根本不需要认证** —— 真因是 `~/.docker/config.json` 里的
`{"credsStore": "desktop.exe"}`:Docker Desktop 的凭据助手要向 Windows 要登录态,
非交互 ssh 会话拿不到,于是构建在第一行死在一个与真实原因毫不相干的错误上。

**解法**:`DOCKER_CONFIG=/var/tmp/dockercfg`(里面只有 `{}`),
**不动用户的 `~/.docker/config.json`**,Windows 侧 Docker Desktop 照常使用。



**构建上下文放 WSL 本地盘**(`/var/tmp/imgctx`),不用 `/mnt/d` —— 9p 慢到 `du` 都超时。
实测拷 venv 约 **87 MB/分钟**(约 10 万个小文件,每文件系统调用开销主导),
7.4 GB 需 **约 85 分钟**。代码 14 MB + 任务包 145 MB 是秒级。

Dockerfile 的三个关键决定:

1. **路径必须是 `/mnt/d/research/OSWorld`** —— venv 里每个 console script 的 shebang
   写死了它。这正是选 Docker 而非 tar 的理由之一:容器里造同名路径零成本。
2. **apt 装得很少**(`python3` `ca-certificates` `libgl1` `libglib2.0-0` + ssh/rsync/curl)。
   `ldd` 查过:**manylinux wheel 自带原生库** —— cv2 带 libpng/libjpeg/libav*/libopenblas,
   PIL 带 libtiff/libjpeg/libopenjp2,均为带哈希后缀的私有副本。
3. **`/usr/bin/python3` 必须是 3.12.3** —— `.venv/bin/python` 是指向系统 python 的
   符号链接,`pyvenv.cfg` 写着 `home=/usr/bin` `version_info=3.12.3`;ubuntu:24.04 正好对上。

三个运行时环境变量写进 `ENV`(它们是配置的一部分,不是偏好):
`OSTG_TYPE_NO_SPLIT=1` · `OSTG_NO_RECORD=1` · `OSWORLD_OPENAI_TIMEOUT=600`。

## 9.10 AWS 侧已创建的资源(08-29 21:40 起,全部带 Contact/Name 标签)

```
sg-0387d7986e67da5d6  osworld-rollout-host   入 22   <- 205.175.106.79/32
sg-0c0808fc290f5d551  osworld-rollout-vm     入 5000 <- [SG] host
                                             入 9222 <- [SG] host
                                             入 8080 <- [SG] host
i-05acb92a607c7228f   m5.2xlarge  100GB gp3  公网 44.214.93.217 / 私网 172.31.12.250
key pair              osworld-rollout        私钥只在 WSL(~/.ssh/id_ed25519_awsrollout,600)
```

**VM 那三条入站的来源是安全组引用而不是 CIDR** —— 5000(无认证任意代码执行)
因此永远出不了 VPC,而且 harness 主机 IP 变了也不用改规则。
**完全没碰 `osworld-macu-sg`**;跑完两个组都删,对 Zixian 零副作用。

建规则前重新量了一次出口 IP(`205.175.106.79`,与先前一致)——
UW 是 NAT 出口,这个值每次用前都该现查。

harness 主机实测:docker 29.1.3 · 根盘 95 GB 可用 · 出网 HTTP 200 ·
**`tillicum-login02:22` 从 AWS 可达**(隧道那条路提前验过,不必等搭的时候才发现不通)。

⚠ **更正**:这台起的是 **Ubuntu 22.04**(`ami-040dc3b259ece28c6`,名字里是
`ubuntu-jammy-22.04`),我早先在消息里写成 24.04 是看错了。**不影响结果** ——
我们的东西全在容器里跑,容器是 `FROM ubuntu:24.04` 且自带 Python 3.12.3 与整个
venv;指纹 `d32d9bccdb2b964c` 就是在容器内量的。宿主机只负责 docker/隧道/rsync。

## 9.11 三层引号嵌套:同一个坑今天栽了两次

CLAUDE.md 写着"外层单引号,内层双引号,**不嵌第三层**"。今天两次违反两次静默失败:

1. `ssh → ssh(login) → ssh(g022) '…'` 跑压测 —— 请求一条都没到 serve,
   日志里查不出任何痕迹。改用 `srun --jobid=… --overlap` 少一层才成。
2. `ssh → wsl → ssh(EC2) <<'REMOTE'` 装 docker —— 输出全空。
   改成"脚本先落文件,再 `bash -s < file` 喂 stdin"才成。

**可靠写法**:把远端脚本写成本地文件,逐跳用 `cat > 文件` 推送并核 md5,
最后 `bash -s < 文件`。另注意 **`ssh -n` 与 `< 文件` 互斥** ——
`-n` 会把 stdin 接到 `/dev/null`,盖掉重定向(今天推 sbatch 时因此推空文件,
靠"推完必对 md5"抓住)。

## 9.12 Tillicum 隧道:必须有人在终端前(实测,与我先前的判断不同)

**Tillicum 登录节点不接受密钥登录。** 从 EC2 和从 WSL 直连都是同一个拒绝:

```
Permission denied (gssapi-keyex,gssapi-with-mic,keyboard-interactive)
                   ^ 提供的方式里没有 publickey
```

所以 WSL 那条一直在用的连接是**人工建立的**(socket `qwen36-tillicum-login` 建于
08-29 01:05,有人敲了密码点了 Duo),脚本里的 `-i ~/.ssh/id_ed25519_tillicum`
**对登录节点是摆设** —— 真正在认证的是 ControlMaster socket。

⚠ **更正**:我先前告诉对面 session"从 AWS 正向 ssh -L,Duo 过一次,成本 0"——
方向对,但漏了一句:**这一步没法自动化,必须有人在终端前敲密码**。

**但那把新生成的公钥不是白装的**(我一度以为白装,收回):login02 不认 publickey,
**第二跳到计算节点 g022 认**(走共享 home 的 `authorized_keys`)。隧道正是靠它建的。

### 落地形状

```
EC2 上生成密钥 -> 公钥进 Tillicum ~/.ssh/authorized_keys(经 WSL 的 ControlMaster,免 Duo)
用户在终端跑一次:  ssh -t ubuntu@<harness> 'bash ~/tillicum_login.sh'
   -> 输密码 + Duo -> ControlPersist=yes 主连接常驻
隧道:  ssh -N -f -L 127.0.0.1:18030:127.0.0.1:8030 \
         -i id_ed25519_tillicum -o ProxyCommand='ssh -S <sock> -W %h:%p <login>' jy050706@g022
```
实测 `curl http://127.0.0.1:18030/v1/models` → **HTTP 200**。
`ControlPersist` 用 `yes` 而非 48h:主跑 8 小时加验证阶段,常驻才不会跑到一半再麻烦人。

## 9.13 镜像落地与三处指纹一致

`docker save | gzip -1 | ssh | docker load`,12.6 GB 传了 **6.7 分钟**,
目标机镜像 ID **`dbd9e87c68a3` 与源端逐位相同**。

> 传输中途 `docker images` 会显示一个偏小的尺寸(看到过 4.03 GB),那是 load 未完成的
> 中间态,**不能拿它当传完的证据**。以指纹为准。

**三处环境,同一个指纹 `d32d9bccdb2b964c`**:WSL 原生 / WSL 容器 / **AWS 容器**。
265 个包、判据库版本全对得上。"新机器算出的分数和老机器一样"是证明过的,不是假设。

⚠ **`.env` 被烤进了镜像**(它在 `COPY OSWorld/` 的范围内),里面有 AWS 临时凭据和
Tillicum bearer token。镜像没推到任何 registry,只在 WSL 和我们的 harness 主机上,
但这是坏习惯。**改法:运行时 `-v` 挂载 `.env`,不用镜像里那份**;
下次重建镜像要把 `.env` 排除出上下文。

## 9.14 凭据:从静态密钥切到 SSO(08-29 深夜)

静态凭据 05:20Z 到期(今晚所有 AWS 操作都在此之前完成,无一失败)。
Zixian 点了 device-code 链接后切到 SSO:

```
~/.aws/config       [sso-session ai2] sso_start_url=https://d-926772e319.awsapps.com/start
                    sso_region=us-west-2  ← 注意与账号 region(us-east-1)不同
~/.aws/sso/cache/   access token 1 小时一刷(带 refreshToken);client 注册 90 天
会话总时长          ~1 天(Zixian 原话,Slack 截图),够 8 小时主跑
```

**三个必须做对的细节**:

1. **死掉的静态密钥必须从 `.env` 里删干净** —— 环境变量优先级高于 profile,
   留着它们 botocore 会拿死凭据去调,报出来的错看不出真因。
2. **`~/.aws` 在 WSL 上是指向 Windows 的符号链接** —— `tar` 不加 `-h` 只会打包链接本身,
   到目标机变成断链(`chmod: cannot operate on dangling symlink`)。
3. **SSO 缓存要送到 harness 主机**并挂进容器(`-v ~/.aws:/root/.aws:ro` +
   `AWS_PROFILE=allennlp`),否则容器里没有会话,取不到凭据。

## 9.15 Tier-2 闸在 AWS 上的形状

```
WSL          遥控台,不跑任何东西
harness EC2  容器里跑 ostg.taskgen.control --gold ...t2.jsonl --provider_name aws
             起 8021 喂自己 gold · 下结果文件 · 跑 comparator
任务 VM      每条一台,官方 AMI:注入 gold → soffice 原格式重存 → 判分 → 销毁
Tillicum     不参与 —— Tier-2 把 agent 整个摘掉,只测判据链
```

**永远只有 2 台实例在飞**(大脑常驻 + 一台任务 VM)。实例开销约 $0.10/全场。

`gold-pilot40-t2.jsonl` 覆盖 36 条(40 条里 4 条未 bake),
**docker 上的历史基准是 36/36**,AWS 上要的是同一个数。

## 9.16 任务池上机

合并集由对面产出,我独立复核过(不只信对方结论):
**manifest 1782 / examples 文件 1782 / distinct id 1782 / distinct slug 1782(重复 0)/
cloud_file 961 条 gold URL 全部解析成功 0 失败** —— 四数一致。

⚠ **gold URL 指向的是原分片路径**(`/<原set>/files/...`),`wave2-all` 本体只有任务
JSON 和 manifest。**8021 的 cwd 必须是 `out/runs` 根(整棵树 14 个分片集)**,
只挂 `wave2-all` 会让 961 条判据全部取不到 gold。

## 9.17 今晚抓到的五个会误事的坑

1. **reaper 会杀掉大脑自己** —— harness 主机和任务 VM 都叫 `Name=rollout`。
   dry-run 默认值救的。已改 `rollout-host` / `rollout` 并复验(0 匹配 / 1 匹配双向验)。
2. **容器结果随 `--rm` 蒸发** —— 冒烟的 9 张截图和判分全没了。
   不修的话主跑 8 小时产出同样消失。已 bind mount 到宿主机 `~/results`。
3. **`client_password` 硬写 docker 的 `password`** —— AWS AMI 是
   `osworld-public-evaluation`,不改则 3 条 sudo 任务静默判 0。
4. **死掉的静态密钥压过 SSO profile**(见 §9.14)。
5. **`generated_tasks.py` 未跟踪但硬 import** —— 漏搬则整个 evaluator 包起不来。

另有三次**引号嵌套三层**导致的静默失败(压测 / 装 docker / 跑脚本),
以及一次 `~` 被 WSL 提前展开成 `/home/daniel_yan` 送到 EC2。
**可靠写法只有一条:脚本落文件 → 逐跳 `cat >` 推送并核 md5 → `bash -s < 文件`,
远端路径一律写绝对路径。**

## 9.18 ⚠ Tier-2 抓到真东西:`freeze` 规则在 AWS AMI 上判不过

**这是 Tier-2 被设计出来要抓的那一类,它抓到了。**

26/36 时出现 2 条失败,两条都是 `table_gold`,而且诊断字段全绿:

```
setup_rc=[0]  gold_rc=0  open_rc=200  windows=1   →  机器全对
score=0.0                                          →  comparator 拒绝
```

按族拆开:**deck(pptx)7/7 · image 10/10 · table_gold 8/10**,分歧只在 xlsx。

### 归因:完全分离,没有余地

pilot40 的 10 条 table_gold 里,**恰好 2 条用 `freeze` 规则,这 2 条全败;
另外 8 条不用 freeze,全过。**

```
course-waitlist-fill-crosscheck   ['freeze','sheet_data']   ✗
hr-headcount-freeze-cols          ['freeze','sheet_data']   ✗
其余 8 条                          sheet_data / +check_cell  ✓ 全过
```

`freeze` 比的是 openpyxl 的 `sheet.freeze_panes`(`table.py:574`),即冻结点单元格
(`"B2"` 之类,未冻结为 `None`)。冻结窗格是 **sheet 的视图属性**(存在 `sheetView`
的 `pane` 元素里),LibreOffice 版本之间的序列化差异会直接反映在这里。

### 暴露面:1782 条里 74 条踩雷(4.2%)

```
freeze              74 条   ← 已证实会失败
col_props.width     18 条   ┐ 同为视图属性,同类风险,
col_props.hidden    15 条   │ Tier-2 样本里没覆盖到,未知
row_props           2 条    ┘
sheet_data         296 条   ← 已证实 OK
check_cell          40 条   ← 已证实 OK
```

### 根因定案:重复逻辑漏修一处 + 唯一能暴露它的闸从没跑过

**AWS 镜像是清白的。** Tier-2 最终 36/36 判完,**34 通过 / 2 失败**,
deck 7/7 · image 10/10 · table 非 freeze 的 8/8 —— 失败只有那两条 freeze。

`bake.py` 和 `gold.py::_inject` **各自独立拼了一条
`soffice --headless --convert-to` 往返命令**。08-28 的修复提交 `62864a21`
(标题就叫 *freeze-panes survive the round-trip*)改了 `audit.py` / `bake.py` /
`prompts`,**没碰 `gold.py`**:

```
bake.py       stash freeze_panes -> convert -> restore    ✅ 修了
gold.py 的
tier2 注入     base64 -d -> convert -> mv                  ❌ 没修
```

于是 gold 里的 `'A2'` 被保住,而 Tier-2 注入时又丢掉 —— 两边不再对称,判据必然拒绝。
**真实 rollout 不受影响**:agent 走 GUI 保存,那条路径不丢视图属性;
只有 headless converter 会丢。

### 为什么一直没人发现

**唯一能暴露它的闸从来没跑过**(全部实查):

```
tools_*.sh 里含 tier2 的步骤   零
盘上的 gold_report.jsonl       零
logs/ 里提到 tier2             零
```

`EXPERIMENTS.md` 的"Tier-2 36/36"说的是 pilot40,**而且报告没留存,无法审计**。
所以修复之后这条路径再没被真正执行过,直到 08-30 凌晨在 AWS 上第一次跑起来。

**两个独立原因叠加,少任何一个都不会踩到:**
① 同一个操作在两个文件里各写一遍,修的时候漏了一处;
② 验证没进自动化、证据没留存,漏掉的那处再没被执行。

### 三条可迁移的教训

1. **对比类判据看不见"两边对称丢失"的属性。** 原始 bug(gold 也丢 freeze →
   `None==None` 恒真 → 教师白拿分)四道 VM 闸**结构性**抓不住,提交作者原话:
   *both sides lose it identically*。抓住它的是 **audit 判官**看渲染后的 gold。
   **凡是"比较 A 和 B"的闸,都对 A、B 共同的系统性缺失免疫。**
2. **同一个外部命令在两处拼装 = 一定会漏修一处。** 应当抽成共享 helper
   (`_office_round_trip(target, ext)`),让修复只有一个落点。
3. **闸不进自动化 + 报告不留存 = 等于没跑。** 一句"36/36"没有 artifact 支撑时,
   既无法审计,也挡不住回归。

### ⚠ 一个我还不能断言的地方(已被上面推翻,保留原文以存过程)

"docker 上 Tier-2 是 36/36"来自 `EXPERIMENTS.md` 的叙述,**但 docker 侧的
`gold_report.jsonl` 在盘上找不到**(各分片集只有 `bake_report` / `control_neg_0` /
部分 `control_t1`)。所以严格说,我现在证明的是"**AWS 上 freeze 判不过**",
而不是"**AWS 与 docker 不同**"。

另一种可能是:`soffice --convert-to` 这个往返**本来就会丢掉冻结窗格**,与版本无关,
而 docker 侧的 Tier-2 从未真正覆盖过这两条。**下一步的定性诊断要把这个分清楚**——
取回 AMI 重存后的实际 `freeze_panes` 值与 gold 对比,再决定修法。

## 9.19 第七个坑:SSO 缓存挂只读 → T+1h 全线崩

```
-v ~/.aws:/root/.aws:ro   →  access token 到期,botocore 写不回刷新后的 token
                          →  OSError: [Errno 30] Read-only file system
                          →  所有 AWS 调用失败,在飞的 25 台 VM 全部泄漏
```

**只会在跑满 1 小时后发作。** Tier-2 那 36 条跑了 46 分钟,**差 14 分钟就撞上**;
真到主跑,它会在 T+1h、25 台 VM 在飞时准时引爆。

**修法**:`~/.aws` 必须**可写**挂载,不能带 `:ro`。已改并在注释里写死原因。

### 七个坑的完整清单(按"什么时候才会暴露"排)

| # | 坑 | 怎么死 | 只在真跑才暴露? |
|---|---|---|---|
| 1 | reaper 撞名杀掉 harness 主机 | 整跑停摆 | **是**(要先有主机) |
| 2 | 容器结果随 `--rm` 蒸发 | 8 小时产出归零 | **是** |
| 3 | `client_password` 用 docker 的密码 | 3 条 sudo 任务静默判 0 | 否(读码可得) |
| 4 | 死凭据压过 SSO profile | 报错指向错误方向 | 是 |
| 5 | `generated_tasks.py` 漏搬 | evaluator 包 import 失败 | 否(grep 可得) |
| 6 | `gold.py` 漏修 freeze 往返 | 74 条 freeze 任务误判 | **是**(要 Tier-2 真跑) |
| 7 | SSO 缓存挂只读 | **T+1h 全线崩,25 台泄漏** | **是**(要跑满 1 小时) |

**七个里有五个是"只在真跑才暴露"的** —— DryRun 与代码审查都看不见。
这就是每一步都要真跑一次小规模验证的理由。

## 9.20 还没被任何测试碰过的东西(开跑前的已知风险)

至今**所有测试都是 `num_envs=1`**。下列没有一个被执行过:

| 风险 | 为什么担心 |
|---|---|
| **25 路并发** | 多进程 worker 启动 · 25 台 EC2 同时 `RunInstances`(API 限流)· **共享 `cache/` 目录的并发写**(25 个 worker 写同名文件)· 8021 被 25 个请求同时打 |
| **chrome 的 9222** | 183 条任务的 setup 要 host→VM:9222。规则写了,**从没有一个字节流过那个端口** |
| **SSO 跨小时刷新** | 第 7 个坑刚修,"可写之后确实能刷新"尚未证明,要跑过 1 小时才知道 |
| 8 小时累积 | 磁盘 15 GB(余 83 GB)· 内存爬升(i10 下实测不爬,但样本只有 3 路 68 分钟)· serve 撞 20 小时墙 |
| 同 `result_dir` 重跑 | 恢复机制的核心,在 AWS 上没试过 |
| 结果 rsync 回 WSL | 没试过 |

**建议加一道阶梯冒烟**:40 条 · `num_envs=8` · 约 20 分钟 · 约 $1,
任务**故意挑含 chrome 的**,跑到一半掐掉再用同 `result_dir` 重启。
一次覆盖:并发多进程 / 9222 / cache 竞争 / 8021 并发 / 磁盘内存趋势 / 恢复路径。

**把"8 小时后才发现"压缩成"20 分钟就发现"** —— 七个坑里五个只在真跑才暴露,
没有理由认为第八个不存在。

## 9.21 阶梯冒烟:40 条 / 8 路(08-30 07:1x–07:39)

**第一次跑并发。** 六个此前完全没被触碰的维度一次验完,平均分 **0.746**。

| 覆盖目的 | 结果 | 说明 |
|---|---|---|
| **chrome / 9222** | **7/10** | **那个端口从没通过一个字节,现在验过了**;3 条失败是教师没导航对 |
| **freeze** | **3/6** | ← 见下,这是关键 |
| gold 比对(calc/impress/writer) | 7/8 | 8021 + comparator 在并发下正常 |
| check_include_exclude(最大族) | 6/6 | |
| infeasible | 3/3 | |
| 8 路并发 | ✅ | 8 台同时 `RunInstances` 未被 API 限流 |
| **`cache/` 目录并发写** | ✅ | 我最担心的一处,无异常 |
| 磁盘 / 内存 | ✅ | 余 82 GB / 27 GB |
| 结果落宿主机 | ✅ | 653 张截图,bind mount 修复有效 |

### freeze 3/6 得分 = 那 74 条任务是干净的

`adspend-channel-rollup-frozen` / `billing-hours-freeze-and-total` /
`hr-oncall-rota-build` **在真实 agent 路径下拿到 1.0**。这证明:

- **GUI 保存保住了冻结窗格**,只有 headless converter 会丢;
- Tier-2 那两条失败是**注入路径的机制假象**,不是任务或镜像的问题;
- **74 条 freeze 任务在主跑里正常,`gold.py` 的漏修只影响 Tier-2 这道闸本身。**

失败的 3 条与其他族失败率一致(教师本就 56–80%),不是系统性的。

### ⚠ 我那个 freeze 补丁失败了,已撤回

给 `gold.py` 加 stash/restore 后:`gold_rc` 从 **0 变 1** —— 注入整个失败。
原因:`python3 -c "import openpyxl"` 是**在 VM 里**执行的,AMI 的 python 没有
openpyxl,`&&` 链一断,目标文件停在 seed 状态(所以 `Summary` 整张表消失)。
**坏补丁比没补丁危险**,已 `git checkout` 回退。正确修法需要先确认 VM 里有什么,
而且**不在主跑路径上**(rollout 不调 `gold.py`),不阻塞。

## 9.22 三项收尾验证

**② 结果 rsync 回 WSL —— 通过**
745 文件 / 175 MB / **16 秒 / 8.2 MB/s**;落地 40 任务目录 / 37 result.txt /
626 截图 / 40 traj.jsonl。外推 1782 条约 15 GB → 全量约 30 分钟,边跑边增量拉无感。

**③ SSO 跨小时刷新 —— 通过(实测,非推理)**
```
原 token 过期 07:17:01Z  →  现 08:09:38Z
缓存文件写入 07:09:38Z,属主 root      ← 到期前 8 分钟自动续并写回
```
证明 §9.19 那个 `:ro` 修复是对的。主跑 8 小时会经历约 8 次这样的刷新。

**副作用**:刷新后缓存文件变成 root 属主,宿主机 `ubuntu` 读不了(监控脚本会瞎)。
同理 **结果文件也是 root 属主**,宿主机侧手工管理要 `sudo`;
rsync 读取不受影响,容器内 runner 也是 root 所以恢复机制不受影响。

**① 同 `result_dir` 恢复 —— 验证中**
判定逻辑(`run_multienv_qwen.py:417`):有 `result.txt` 记为已完成跳过;
没有则**把该任务目录清空**再重跑。
⚠ **实例数不能当判据** —— runner 在取任务前就为每个 worker 各起一台 VM,
8 路配置永远先起 8 台,与队列长度无关。正确判据是**哪些任务目录被重写**。

## 9.23 主跑中的发现:图像族 92% 通过 —— 判据只问方向,且族内构成与官方不符

### 现象(前 444 条实时判分)

```
按域    chrome  224/298  75%      gimp  134/146  92%
按判据  is_expected_url_pattern_match   135/181  75%   ← 要落到特定 URL
        check_include_exclude            58/77   75%
        check_brightness_decrease_and_…  37/40   92%
        check_contrast_increase_and_…    34/37   92%
        check_saturation_increase_and_…  31/33   94%
        check_image_mirror               30/34   88%
```

### 原因:严格不等式,无幅度要求

`desktop_env/evaluators/metrics/gimp.py:301`
```python
brightness_reduced = brightness_tgt > brightness_src
```
**降低 1/255 即通过**(外加 structure-sim 0.03 防止毁图)。四个判据都可以用
`Colors → Brightness-Contrast → 拖滑块 → 导出` 或 `Image → Transform → Flip` 完成。
`gimp.py` 是上游原版文件(evaluators 里只有 `file.py`/`__init__.py`/`vscode.py` 被改过)。

### 这批数据"是不是更简单"——量化对照

```
                    wave2-all(1782)  v11-500(444)  v11-all(100)
难度 >=3(multi-app)     62%             60%           61%
app_count >= 2          62%             60%           61%
ambiguity 分布          几乎重合         —             —
图像单向判据            8.8%(156)       0%            0%
```

**设计维度没有变简单** —— 难度/多应用/歧义三条曲线与 v11 重合。
**变的是新增了 v11 完全没有的族**,而该族判据宽松,把表观通过率抬高了。

### 对面给的立项背景(v14g 为何加这一族)

1. 补的是**官方评分家族形状**:08-28 家族普查显示官方 369 里 image_property 占 7.3%,
   而 ostg 旧 5694 条该族**整列为零**(五个零族之一);8.8% 是照 7.3% 配平的。
2. 判据"只问方向"是**有意沿用官方语义**(纲领:彻底和官方统一标准),
   audit 的 judge 提示词里写过 `magnitude-not-threshold`,松紧被看见并接受过。

### ⚠ 但我核官方那一族后,发现配平只做了一半

官方 gimp 26 条的判据构成(实查 `OSWorld-upstream`):

```
infeasible 9 · check_config_status 4 · check_include_exclude 2
四个方向判据合计 4  ← 仅 15%
另外 11 种各 1 条:check_palette_and_structure_sim · check_structure_sim ·
  check_green_background · check_file_exists_and_structure_sim · check_image_size ·
  check_structure_sim_resized · check_textbox_on_leftside · check_triangle_position …
```

| | 官方 | 我们 |
|---|---|---|
| 族规模 | 26/369 = **7.0%** | 156/1782 = **8.8%** ✅ |
| 族内判据种类 | **15 种** | **4 种(同一类)** |
| 方向判据占比 | **15%** | **100%** ❌ |

**我们把官方这一族里最浅的 15% 拿来铺满了整个族。** 官方另外 85% 要求真操作
(文本框摆位、三角形位置、调色板匹配、精确尺寸、缩放后结构相似、绿背景替换),
我们一条都没有 —— **这是一个伪装成覆盖的覆盖缺口:格子填上了,填的是最薄的一层。**

### 对语料的后果

```
图像族占任务池   8.8%
按 92% 通过率    约 143 条成功轨迹
整体若 ~60%      成功语料约 1069 条
占成功语料       ≈ 13.4%      ← 超配约 1.5 倍,且轨迹最短、动作最单一
```

对面的 curate 方案(按池占比封顶 ~90-95 条 + 子模式去重,而非整族降权)方向正确,
**但子模式多样性的天花板本身就很低** —— 封顶之后仍然只有四种滑块动作。

### 为什么当初只取 4 个 —— 机器层原因(对面补充,免得下一轮的人以为是随手挑的)

v14g 的 image 族走的是**"seedful 方向判据"gold 机型**:`expected` = 种子图本身,
判据只比方向,**不需要生成任何 gold 文件**。官方另外 11 种做不到这一点:

```
要 gold 参照物   check_palette_and_structure_sim · check_green_background ·
                 check_structure_sim_resized
参数化规则       check_image_size · check_triangle_position · check_textbox_on_leftside
```

每一种都要不同的 gold/规则机器,08-28 当天为了落地砍了范围。

**所以修法不是改 `IMAGE_FUNCS` 白名单一行,是给 image 族扩 2–3 个 gold 机型 ——
工作量在 build/bake 侧。**

### 结论与去向

**这是下一轮 gen 的输入,不是这一轮的问题。** 若目标是"和官方统一标准",
配平对象应是**族内判据分布**而不只是族规模。

分工(08-30 与对面议定):
- 数字与对照表 → 本文(已写);
- **下一轮 gen:image 族内判据分布配平(4→15 种,需扩 gold 机型)** → `IDEAS.md` 候选实验队列;
- `SFT_DATA.md` curation 节:image 族按池占比封顶 ~8.8%(90–95 条)+ 子模式去重,
  **并注明子模式天花板 = 4 种滑块动作**。封顶数字不因此收紧 ——
  训练价值 ≠ 评测镜像,滑块 grounding 仍是净增量,但要把它的浅记录清楚。

## 9.24 全池零多 func 判据:难度虚高,但语料无害

### 事实一:1782 条里没有一条是多判据的

```
app=1    单 func 判据   686 条    实测通过 80%
app>=2   单 func 判据  1096 条    实测通过 76%    ← 占全池 62%
多 func 判据                0 条
```

图像族更极端:d1 0/22 · d2 0/33 · d3 0/39 · **d4 0/35 · d5 0/27** ——
难度 4/5 的 62 条,判据只看那一张图,指令里"再写个文本文件记录尺寸/字节数"
那一半**判据看都不看**。

单 func 判多应用**不必然错**(最终产物编码整条链时合法,如"从浏览器取数填表"用
`compare_table` 隐含验证浏览器那步)。但图像族证明**会漏**。

### 事实二:我担心的语料危害没有发生(数据自纠)

原判断:"教师做一半拿满分 → 语料教模型做一半就停"。实查后**不成立**:

```
图像族含附加写文件要求的   26 条
其中满分                  24 条
满分且轨迹里有写文件动作   21 条
满分但看不到附加动作       3 条  ← 逐条看全是正则误判("on my Desktop" 被当成附加任务)
```

**凡有附加任务的,教师 21/21 全做了。轨迹完整,curate 拿到的是真实成功样本。
这批数据在这一点上干净,无需处置。**

### 仍然成立的两条

**① 难度标签虚高** —— 判据不验难的那一半,d5 的实际判分门槛≈d2:

```
难度 1  78%  →  难度 5  71%     只掉 7 点
app=1   80%  →  app>=2  76%     只差 4 点
对照 v14g 按坐标实测:d1-3 62% / d4 42%,跨度 20 点
```

**② 通过率口径要注明** —— 当前 78%(剔除图像单向判据后 73.2%)是
"完成了**被判分的那部分**"的比率,不是"完成指令全部要求"的比率。
**与历史 56% 直接比较不成立。** 报数时一律标"判据口径通过率"。

⚠ **难度曲线的解读不能单归因**(对面 08-30 更正我):曲线平化至少有两个因素叠加 ——
**判分门槛虚高**(本节)**+ i10 配置对长任务的真实增益**(七臂试点 +12pp)。
把 7 点跨度全算到判据头上是错的。

### 去向

不影响本轮(数据好、轨迹完整)。属**下一轮 gen 的输入**,且**已有正式去处**:

**v15 已于 08-30 获用户批准**,A+B 两类全上 —— A = 官方 21 个规则类函数直接复用;
B = 12 个 gold 参照类扩机型;**复合判据是 Phase 2 主件、d≥3 强制**。
第一步已完成:28 个函数的官方用法契约入库(v15 分支 `0f832068`,
含 **57 个官方复合判据真实用例**,形状直接抄官方)。
本节的 1096 条 app≥2 面会在对面的 divcheck 尺子里单列一行。
**细节归 v15 侧文档,此处只留数字与互引,不重复记。**

### 本节对下游的一个实际影响

21/21 这个数让对面把 build 阶段原计划的"旅程完成度**全量**抽检"降级为
**5% 轻量抽样守门** —— 因为"理性应试者会抄近路"的模型对这个教师不成立:
**它看不见判据,所以照单全做**,偷懒才会跳步而它没偷懒。

## 9.25 难度阶梯 75% 是虚的:`app_count` 把 files/terminal 当成应用

### 拆开"多应用"

按 `related_apps` 分成文档类(calc/writer/impress/chrome/gimp/thunderbird/vlc/vs_code)
与辅助类(files/terminal/os):

```
类别                                     池中    已判分   通过率
单应用                                    686     295     76%
多应用【真】>= 2 个文档应用                 275      94     69%
多应用【虚】1 文档应用 + files/terminal/os   821     407     75%
```

**标为多应用的 1096 条里 821 条(75%)只是带了个文件管理器或终端,
通过率 75% 与单应用的 76% 无差别。真正的多应用只有 275 条 = 全池 15%,69%。**

### 这就是难度曲线平坦的机制

```
全部:       d1 75%  d2 77%  d3 78%  d4 73%  d5 70%     非单调
剔除 gimp:  d1 72%  d2 72%  d3 72%  d4 69%  d5 65%     d1–d3 完全持平
对照 v14g 按坐标实测:d1-3 62% / d4 42%,跨度 20 点
```

难度阶梯按 `app_count` 搭(约定 d>=3 即 multi-app),而该数 75% 由辅助工具凑出
→ **阶梯的三分之二级是假台阶**。与 §9.24 的"判分门槛虚高"是**两个独立**的平化来源。

### 应用组合 × 通过率(已判分 ≥8 条)

```
gimp 93% · files+gimp 92% · gimp+terminal 90% · files+gimp+terminal 88%
chrome+writer 85% · chrome+files 84%
────────────────────────────────────────────────
calc+writer 64% · files+calc 63% · chrome+calc 62% · chrome+files+os 62%
files+calc+writer 62% · chrome+files+writer 60%
```

**难的不是"应用多",是"数据要跨文档应用搬运"** —— 计算机使用最硬的技能,
池中仅 275 条。gimp 系列全在 88–93%,因为方向判据对附加应用视而不见(§9.23)。

### 给 v15 配方的两条

1. **`app_count` 应按文档应用数计**,`files`/`terminal`/`os` 不计入难度维度
   —— 它们是动作,不是应用切换。否则抽签器以为在采多应用,实际在采单应用。
2. **跨文档搬运是稀缺且最有价值的坐标**,当前仅 15%,该显著加权。

### 队列偏序:当前 78% 会掉

```
已跑  calc 330/344(65%) · chrome 298/298(75%) · gimp 164/164(91%)
未跑  impress 265 · writer 251 · os 219 · thunderbird 131 · vlc 82 · vs_code 28
      = 976 条 = 55%,六个域一条没碰
```

runner 按**字母序**取域,当前 78% 由三个域(两个最容易的)撑出。
剩余按 50–60% 估,**最终落在 63–70%**。**报数一律不得用运行中的值。**

### 附:规则层的塌缩比判据层更严重(calc 实测)

上游 `table.py` 支持 **15 种规则**,我们只用 **8 种**:

```
从未用过(7 种):data_validation · pivot_table · sheet_fuzzy · sheet_name ·
                sheet_print · sparkline · zoom
```

**`pivot_table` 与 `data_validation` 一条都没有** —— 电子表格最有代表性的两个高级能力。

用到的 8 种分布也极度倾斜(325 条 `compare_table`):

```
sheet_data  315 次 96.9%    check_cell 220 次 67.7%(约覆盖 40 条,一条内可多次)
freeze       74 次 22.8%    col_props   25 次  7.7%
style         4 次  1.2%    chart        2 次  0.6%
row_props     2 次  0.6%    filter       1 次  0.3%
```

规则组合只有六种,**头部一种(纯 `sheet_data`)占 58%**。

### 三层塌缩是同一个形状

```
应用层   9 个应用,难度实由"是否跨文档搬运"决定,而那只占 15%
判据层   官方 image 15 种判据,我们只用 4 种(全是方向判据)
规则层   官方 table 15 种规则,我们只用 8 种,头部一种占 58%
```

**每一层都是"格子填上了,填的是最窄的那一角"。**

### ⚠ 病因更正(对面 08-30 纠正我,他是对的)

我原写"白名单形同虚设",暗示白名单太窄 —— **实际相反**:
**v14 的白名单本来就放行 13 种规则(含 `pivot_table` / `data_validation` / `zoom`),
LLM 一条都没写。**

真凶是**示例引力**:生成提示词里 `gold_rules` 的唯一示例就是 `sheet_data`,
**不开思考的模型照着唯一示例抄**。

所以修法不是改白名单,是**让示例跟着抽签走** —— 配方抽中哪种规则类型,
提示词就给那一类型的官方真例(机械、零认知负载,与判据枚举同一套无思考设计)。

### ⚠ `pivot_table` 未必零成本(同上,更正我)

我原写 `pivot_table` / `data_validation` "都有上游现成判据,不需要新 gold 机型,
低成本高回报" —— **判据侧成立,答案侧不成立**:
答案脚本用 openpyxl,而 **openpyxl 基本造不出真透视表(能保不能建)**。
所以 `pivot_table` 一条没有,可能不止是"没人写",还有"**写了也烤不熟**"。

补波顺序据此定为:
1. **`data_validation` 先上** —— openpyxl 原生支持,真正零成本;
2. **`pivot_table` 先手工过一条烤箱**(soffice 侧路径),烤得熟再进配方,
   烤不熟就记档为"需新答案机型",**不放进承诺**。

### 附:calc 的操作词表窄

344 条 calc ≈ **5 种电子表格技能 × 69 种领域外衣**:写表头 / 算一个公式列 /
排序 / 写指定单元格 / 建汇总 sheet。外衣散得好(9 行业 · 4 intent · d1–d5),
骨架极窄。全池 `chart` 2 条 · `filter` 1 条 · `style` 4 条 ——
**图表、透视、条件格式、筛选、数据验证几乎为零**。与图像族同源:
覆盖的是每个应用里最窄的一角。

## 9.26 三层塌缩的机制定性:配方最细的轴比"操作"粗一级

### 现象:同一个形状出现三次

```
image   官方 15 个判据  →  我们用 4 个,全是方向判据
table   官方 15 种规则  →  我们用 8 种,头部一种占 58%
deck    判据最严(16 项默认开)→  88% 的任务都在动标题
```

**倒挂值得单记**:`compare_pptx_files` 空 options 默认比较 16 项
(含颜色 RGB 容差 0),是三个域里最严的;而 impress **71%**,
高于判据最松的 calc(188 条纯 `sheet_data`,只比数据不比格式)的 **66%**。
→ **判据严度不能单调解释通过率**,记进报数口径备忘。

### 机制:抽签器只称量 5 个轴,"操作"不在其中

`recipe.py` 的契约(原文):

> Schema v1 exposes exactly the knobs the sampler weighs
> (**difficulty / ambiguity / voice / app / family**) plus infeasible_share…
> Axes the sampler covers by product-walk (intent, topic) are **NOT weighable keys**
> — accepting them would promise steering **the mechanism does not do**

配合 `taxonomy.FAMILIES`(**117 funcs → 11 groups**)与 `wave2-main.yaml`(称量 6 族):

```
官方判据 117 个
  ↓ 归族                11 组
  ↓ 配方称量             6 组(table .211 · deck .197 · doc .159
                              · browser .147 · image .125 · config .161)
  ↓ 族内选哪个具体判据/规则   ← 【无人称量】
  ↓ LLM thinking:False,每族提示词一个示例
产出                    每族塌缩成一个代表
```

**配方能称量的最细粒度是"家族"(≈10 个判据一组);而决定难度与训练价值的是
"具体哪个操作",比最细的轴还细一级,因此完全不受控。
不受控的维度不会均匀分布,它会塌向生成器的众数。**

三层塌缩因此不是三个独立缺陷,是**同一个控制粒度问题的三次显影**。

### 这个取舍是有意做的,不是疏忽

`taxonomy.FAMILIES` 注释:

> **actions stay annotation(measured 25% inter-labeler disagreement)**,
> families are a string in the task JSON

**因为"动作"的人工标注不一致度实测 25%,当初没把它做成配额轴。**

⚠ **但这个理由挡不住"判据"轴**:判据类型是任务 JSON 里的**机器可读字段**,
不需要人标注,不存在一致性问题。**当初挡住动作轴的论据,不适用于判据轴。**

### 去向:通用子轴,不是逐族补丁(08-30 与对面议定)

逐族补丁的问题:11 个族要挖 11 次坑。**该预言在对面侧已应验两次**
(他已写了 `BROWSER_FUNCS` 与 `TABLE_RULE_DRAW` 两张临时表),故止损转通用机制。

落地分两层:
1. **生成侧通用词汇轴(现在落)**:单一 `VOCAB = {family: {取值: 权重}}`,
   格子抽完后逐格抽词。**不参与格子间债务记账**(词是格内属性,不跨格竞争),
   加权随机即可;漂移由体检盯,盯出问题再上债务式。
2. **配方侧暴露(补波配方时落)**:recipe schema 加**可选 `vocab` 段**,
   逐族声明合法集 + 权重,验证后透传给生成侧 —— **schema 小改,sampler 零改**。

**`vocab` 段的七条校验规则**(照 `recipe.py` 既有纪律推,对面 08-30 全收):
① 合法集来源是代码不是配方(与"不能凭空发明 app"同源,报错须带该族合法集全文);
② 只能给已称量的族写 vocab(无法兑现的政策失败要响);
③ 权重逐字消费不重归一(重归一会移动债务项,破坏同 seed 复现);
④ 缺省=沿用现状**但 loader 必须列出未声明 vocab 的族**(静默缺省正是本次塌缩
   潜伏这么久的原因之一);⑤ 显式 `0` = 禁止,与"缺省"语义不同;
⑥ **抽中的词必须进 spec 溯源**,与 `recipe_name`/`recipe_hash` 并列 ——
   否则体检算不出"声明分布 vs 实际分布"(同 `OPS.md`"选择器必须出声");
⑦ 可执行性分类写在代码不写在配方(`FAMILY_VOCAB_KIND`)。

**体检阈值:头部词 > 50% 告警。** 依据是本次三个实测读数 ——
`table` 头部组合 **58%** · `deck` 动标题 **88%** · `image` 方向判据 **100%**,
三者都在 50% 以上**且都是事后才发现的**,故 50% 是有实证支撑的阈值。

**未 bakeable 的词:能列不能称(裁决取严格版)。**
我曾倾向"包含 + 仅警告",被对面用规则 ② 驳回且他对:
给未烤词加权 = 机器兑现不了的政策(抽中 → 烤死 → 格子回池 → 声明 10% 实交 0%),
**正是"silently trimmed"那一类**。故 loader 对加权非 bakeable 词**报错**,
错误信息带 bakeable 现状与解锁路径(过烤箱试针 → 代码翻旗 → 配方才许加权)。
合法集 = 官方判据支持什么(**稳定事实**);`bakeable` = 答案机器造不造得出
(**随代码版本走的状态**)。两者不混。
落地:`FAMILY_VOCAB` 合法集 + `KIND` + `bakeable` 三表进 `taxonomy`,与 `FAMILIES` 并列。

**两类族要分开处理**:
- `table` / `browser` / `image` 的"词" = **机读判据/规则** → 门闸可执行验证;
- `deck` / `doc` 的"词" = **操作焦点**(title/reorder/字体/备注…)→
  门闸看不见动作,走 prompt 引导(focus 值进坐标行)+ 体检指纹事后验证。
  **impress 的"88% 动标题"就是这一类的基线读数。**

## 9.27 impress 分布实测:表层不重复,操作层塌缩;并抓到两类零解任务

测法(可复现,全部只读):对 `wave2-all/manifest.json` 里 265 条 impress 任务,
逐条打开 `runs/<batch>/files/<slug>/{seed,gold}/*.pptx`,按 `compare_pptx_files`
**真正开启的 14 个 `examine_*` 开关**逐维 diff,再与 `v14g-1782-aws` 的
`result.txt` 联表。脚本:`diff_deck*.py` / `join_score.py`(WSL `/home/daniel_yan/`,
需用 `/mnt/d/research/OSWorld/.venv/bin/python`,系统 python 无 python-pptx)。

### 判据层

| 判据 | 条数 | 占比 |
|---|---:|---:|
| `compare_pptx_files` | 250 | 94.3% |
| `check_include_exclude` | 13 | 4.9% |
| `infeasible` | 2 | 0.8% |

250 条 `compare_pptx_files` **全部 options 为空**,即 14 个默认 True 的开关全开
(6 个位置/尺寸类开关默认 False)。判据本身不松。

### 两个必须先扣掉的测量陷阱(我第一版都踩了)

1. **round-trip 伪影**:`font_name/font_size/font_bold/color_rgb/alignment/bullets`
   在 seed→gold 上 **100% 全变**。逐 run 拆开看,970 个同文本 run 里 970 个是
   `None → 具体值`(seed 由 python-pptx 造,属性继承;gold 过了一遍 LibreOffice
   保存,继承属性被固化),真正 `值→另一个值` 的只有 5 个。**不扣掉这层,
   "格式类任务占 100%" 是假的。**
2. **notes 假阳性**:整表比 notes 列表会把"加片多出一条空 notes"算成改动,
   得出 35.6%;只在 zip 对齐的片上比,真值 **2.0%**。

### 语义操作分布(247 条可测)

| 操作 | 条数 | 占比 |
|---|---:|---:|
| 改标题文字 | 145 | 58.7% |
| 改正文文字 | 135 | 54.7% |
| 增删幻灯片 | 84 | 34.0%(加片 36 / 删片 48) |
| 重排顺序 | 37 | 15.0% |
| 纯格式(字号/加粗/颜色/下划线) | 9 | 3.6% |
| 改备注 | 5 | 2.0% |
| 改版面尺寸 | 4 | 1.6% |

操作组合签名 12 种,最大一种 24.7%。

### 结论:表层不重复,操作层重复

不重复的证据:instruction **265/265 全唯一**,leading 6-gram 263 种,
slug 265 种全唯一,领域 13 个,difficulty 1–5 铺满(39/43/59/58/48),
多应用组合 11 种(单应用 34.7%,files+impress 34.0%,files+calc+impress 12.5%)。

重复的证据:**14 个判据维度里只有 6 个被这批任务碰过**;文本编辑(标题+正文)
覆盖约 85%,而格式 3.6% / 备注 2.0% / 版面 1.6% 三类加起来不到 8%。
这与 §9.23(图像 4/15)、表格(8/15 规则)是**同一个机制**(§9.26):
配方能称量的最细轴是 family,"具体做哪个操作"比它细一级,于是塌向生成器众数。

**订正**:此前口头说的"deck 88% 动标题"是粗测,真值是标题 58.7% / 正文 54.7%,
合起来文本类 85%。以本节数值为准。

### 按操作看通过率(已判分 140 条)

| 操作 | n | 通过率 |
|---|---:|---:|
| 只改标题 | 20 | 85.0% |
| 删片 | 26 | 84.6% |
| 重排 | 26 | 76.9% |
| 纯格式 | 9 | 77.8% |
| 标题+正文 | 24 | 50.0% |
| **加片** | 25 | **8.0%** |
| **改版面尺寸** | 4 | **0.0%** |

difficulty 与通过率基本无关(1→64.3% / 2→62.5% / 3→64.5% / 4→46.7% / 5→66.7%),
与 §9.25 的结论一致。

### 零解任务甲:加片(36 条,通过 8%)

`store-hours-slide-append`(difficulty 1,"在末尾加一页 Sunday Hours / 11:00-17:00")
13 步自己收工,截图里第 4 页标题正文都对,判 0。读 `runtime.log`:模型右键
新建幻灯片 → 选版式 → 填标题正文 → Ctrl+S,全程无误。

机制:**gold 的新页占位符格式继承自 seed 模板(正文 Calibri 32pt 左对齐带项目符号,
语料众数占 94.9%),而 GUI 新建的页继承 LibreOffice 自己的自动版式**(截图里
正文是居中大字)。grader 比 `font_size`/`alignment`/`bullets` → 必挂。
通过的 3 条(`spectro-deck-split-runs-per-slide`/`tour-deck-split-per-day`/
`trial-deck-rebuild-from-enrolment`)都是"拆分/重建"类 —— **复制已有页会带走格式**,
这正是唯一能对上的做法。删片 84.6% 通过恰好互为对照:删除不新建占位符。

结论:任务可解但只有一条窄路(复制现有页再改),指令里对格式只字未提。

### 零解任务乙:改版面尺寸(4 条,通过 0%)—— 这条是真 bug

`compare_pptx_files` **根本不比较 `slide_width`/`slide_height`**(函数体内这两个
标识符只出现在同文件相邻的 `check_slide_orientation_Portrait` 里)。而这 4 条的
gold 与 seed **除了画布尺寸没有任何其他差异**。于是:

- 什么都不做 → 各判据全等 → 应判 1.0;
- 按指令真去改 → LibreOffice 改画布会重排/缩放占位符与字号 → 被比较的维度变了 → 判 0。

**做对反而必错**。两条日志(`food-bank-deck-widescreen`、`assay-deck-slide-size-16by9`)
都显示模型正确完成了 16:9 设置,双双判 0。四条:
`food-bank-deck-widescreen` / `vaccine-clinic-deck-widescreen` /
`store-hours-slide-widescreen` / `assay-deck-slide-size-16by9`。

### 对本次 campaign 的影响

40 条(加片 36 + 尺寸 4)= impress 域的 **15.1%**,产出的教师轨迹几乎全是 0 分,
对 SFT 无用。不影响正在跑的 run(继续跑完更划算),但:

- **尺寸类 4 条:出数据时直接剔除**,它们是自相矛盾的任务,不该进语料。
- **加片类 36 条:保留但标记**。它们不是坏任务,是"窄路任务";若要它们出轨迹,
  要么在 gold 生成时改用 GUI 可达的构造,要么承认这批只产 0 分。
- 生成侧要记的规矩:**gold 的构造路径必须是 GUI 可达的**;凡 gold 由脚本直接
  写 XML/画布属性而 GUI 会附带重排的操作(改画布、改占位符几何),都要么别出题,
  要么在 evaluator options 里显式关掉受牵连的维度。

## 9.28 infeasible 任务的影响:全局只虚高 1.2 点,但 os 域虚高 9.4 点,语料里 34% 是"看一眼就拒"

### 判法(先把机制读清楚)

`desktop_env.py` 里就两条,都不走任何判据:

- `evaluator["func"] == "infeasible"` → **最后一个动作是 `FAIL` 判 1,否则判 0**;
- 反过来,**任何可行任务只要最后一个动作是 `FAIL`,直接 `return 0`**,判据一条都不跑。

`lib_run_single.py` 里另有一条"verifier 连拒 3 次且理由含 `infeasible`/`impossible`/
`not supported` 等关键词 → 替模型发 `FAIL`"的逻辑。**本次跑不受它影响**:该逻辑在
`run_single_example_vlaa_gui()` 里,而 runner(`scripts/python/run_multienv_qwen.py`)
调的是 `run_single_example()`,且 runner 全文 `verifier` 出现 **0 次**。死代码,已确认。

### 规模:全池 181 / 1782 = 10.2%,但集中在 os

| domain | infeasible | 全域 | 占比 |
|---|---:|---:|---:|
| os | 118 | 219 | **53.9%** |
| vs_code | 5 | 28 | 17.9% |
| chrome | 41 | 298 | 13.8% |
| thunderbird | 9 | 131 | 6.9% |
| libreoffice_writer | 5 | 251 | 2.0% |
| libreoffice_impress | 2 | 265 | 0.8% |
| gimp | 1 | 164 | 0.6% |
| libreoffice_calc / vlc | 0 | — | 0% |

**os 域一半以上是不可行任务**,即该域实际只提供 101 条可行任务。指令样例:
"从西门子 PLC 现场总线拉冲压配置""把登录改成指纹""从 CAN 总线上的 GPS 授时"——
都是真做不了的外设/企业服务类。这是不是配方有意为之,需要回 ostg 侧对配方,
本节只记事实,不下判断。

### 对分数的影响:全局小,分域大

已判分 1642 / 1782(92.1%)时的读数:

| | n | 通过率 |
|---|---:|---:|
| 可行 | 1466 | 64.5% |
| 不可行 | 176 | 75.6% |
| 混在一起 | 1642 | 65.7% |

全局只虚高 **1.2 个点**(因为不可行只占 10%)。但分域差很多:

| domain | 可行 | 不可行 | 域内混报 | 虚高 |
|---|---:|---:|---:|---:|
| os | 55.4% (n=101) | 72.9% (n=118) | 64.8% | **+9.4** |
| thunderbird | 27.2% (n=92) | 88.9% (n=9) | 32.7% | +5.5 |
| chrome | 74.7% (n=257) | 78.0% (n=41) | 75.2% | +0.5 |

**规矩:报 os 和 thunderbird 的通过率必须可行/不可行分开报**,合报没有意义。

### 对语料的影响(比分数重要)

133 条判 1 的不可行轨迹,步数分布:

| 步数 | 条数 | 占比 |
|---|---:|---:|
| **1 步** | **38** | **28.6%** |
| 2–3 步 | 7 | 5.3% |
| 4–10 步 | 47 | 35.3% |
| 11–25 步 | 28 | 21.1% |
| >25 步 | 13 | 9.8% |

**45 条(34%)是"看一眼截图就发 FAIL"**,平均 10.4 步。这批原样进 SFT 教的是早退,
而早退在这个 harness 里代价极高:**可行任务一旦发 FAIL 直接判 0,连部分分都没有**。
用 refusal 轨迹换来的收益是 10% 的题,代价是 90% 的题上多一个廉价的退出动作。

另一头:43 条判 0 的不可行任务,模型硬做到平均 **18.1 步**才收工,纯浪费算力。

### 顺带查到的第三类:12 条 harness 崩溃(0.7%),全判 0

`harness_error.json` 存在的 12 条,平均分 0.000:

- 10 条 `Setup step 2 failed: _open_setup ... 404 NOT FOUND /setup/open_file`
  (writer 5 / os 3 / thunderbird 3 里的多数)—— 打开文件那步 404,瞬时故障;
- 2 条 `TypeError: a bytes-like object is required, not 'NoneType'`,
  在 `lib_run_single.py:84` 的 `_f.write(obs['screenshot'])` —— 截图取回来是 None。

这 12 条是**可重跑捡回**的,不是任务本身的问题。

### 结论与动作

1. **报数**:可行 / 不可行分开报,os 与 thunderbird 尤其。
2. **出语料**:1 步 FAIL 的 38 条(连同 2–3 步的 7 条)建议整体剔除;其余不可行轨迹
   限流,别让 refusal 在语料里的占比超过它在评测集里的占比。
3. **重跑**:12 条 harness 崩溃的。
4. **回问生成侧**:os 域 53.9% 不可行是不是配方设计值。

## 9.29 收尾与 v16 起跑:SSO 会话到期、25 台泄漏、`_open_setup` 根因、4×4 卡 + 反代

### SSO 会话到期(2026-08-30 08:40 PDT)

时间轴(太平洋时间,harness 时钟是 UTC,已换算):

| 时刻 | 事件 |
|---|---|
| 08-29 21:59 | harness 建好 |
| 08-29 **23:16** | Zixian 批准设备码登录 —— **这次会话的起点** |
| 08-30 00:09 | token 最后一次成功刷新,`expiresAt` 写着 01:09 |
| 08-30 00:50 | 主跑开跑 |
| 08-30 **08:40** | 第一条 `TokenRetrievalError`,**距登录 9h19m** |
| 08-30 08:45 | 剩余队列(vlc 43 + vs_code 28)5 分钟内空转报错 |
| 08-30 08:59 | 最后一条正常判分(在飞任务收尾) |

机制分两层,别混:

- **access token 生命期 1 小时**(缓存 `expiresAt` 减写入时间正好 60 分钟),靠 refresh token 自动续,正常无感;
- **上限是 SSO 会话时长**,AI2 管理员在 IAM Identity Center 里设,我们看不到也改不了。

注意 01:09 到 08:40 这 7.5 小时调用一直正常 —— 说明中间在用的是 SSO 换出来的角色临时凭证,
等它也到期、回头找 token 续时才发现 token 早死了。**具体每层设了多久,没有证据,不猜。**

配置是标准 `[sso-session ai2]` + `sso_registration_scopes = sso:account:access`,无静态密钥。
`registrationExpiresAt` 是 11-28,坏的不是客户端注册。

**操作规矩:按登录时间算,不是按开跑时间算 —— 登录后 9 小时内必须再续一次。**
好消息是不用停跑:容器挂载的就是 `~/.aws`,中途续一次新 token 写进同一个文件,
容器下次刷新直接读到。这次栽在 23:16 登录、00:50 才开跑,所以跑到第 7h45m 就断了。

### 25 台实例泄漏 —— 根因不是 SSO,是没有 TTL 兜底

日志里 **24 次 `Stopping AWS VM i-...` 每一次后面都跟着 `TokenRetrievalError`**,
`has been terminated` 只在 08:40 之前出现过。销毁调用也要凭证。

但更根本的是这条,每创建一台实例都会打印一次:

```
Failed to auto-create scheduler role 'osworld-scheduler-ec2-terminate':
AccessDenied ... not authorized to perform: iam:CreateRole
Scheduler role ARN not available; skipping TTL schedule creation.
```

harness 本来要给每台实例挂到时自动销毁的调度,因为没有 `iam:CreateRole` 建不出来,
直接跳过。**所以凭证一死就没有任何东西会去收实例。**

处置:凭证刷新后 reaper dry-run 匹配 **25 台**(不是 24)、125 台别人的一台没碰,
反向对照 `--name rollout-host` 只匹配 harness 那 1 台。`--yes` 执行,复验 running=0。

**下次根治(按优先级)**:① 给 harness 挂 instance profile,凭证由 EC2 metadata 自动轮转,
永不过期;② 让 Zixian 建好 `osworld-scheduler-ec2-terminate` 角色,实例带 TTL 自毁;
③ 人工每 8 小时续 —— 最差。**用户已选 ③(人工)**,所以第 1 条那条规矩必须执行。

### ⚠ 撤回一个判断:`_open_setup 404` 不是瞬时故障

我早先记的"13 条 `_open_setup 404` 是瞬时的、可重跑捡回"**是错的**。重跑后
**10 条一模一样地又崩**,域分布分毫不差(writer 5 / os 2 / thunderbird 3)。

根因:把每条任务 `config` 里 `execute` 步的所有重定向目标收集成"实际写出集合" W,
和 `open` 步的 `path` 集合 O 对账 —— **10 条全部 O ⊄ W**:

| 花样 | 例子 |
|---|---|
| 扩展名不符 | 写 `channel_brief.docx` / 开 `channel_brief.odt`;写 `depot_rota.odt` / 开 `depot_rota.txt` |
| 文件名不符(open 的是模型该产出的东西)| 写 `arrears_ledger.csv` / 开 `arrears_summary.odt`;写 `funding_log.csv` / 开 `grant_brief.odt` |
| setup 一个文件都没写 | thunderbird 3 条开 profile 目录、os 1 条开 Desktop 文件 |

**排除了 payload 过长这个可能**:崩溃的 writer 任务 setup 只有约 6KB,
同域正常任务中位 **19682**、p90 **49496**、最大 **98227**,全跑通了。崩的反而是短的。

**该加的静态闸(不用跑任何东西)**:收集 `execute` 步的 `> '<path>'` / `tee` / `cp` / `mv`
目标成 W,收集 `type: open` 的 `path` 成 O,**要求 O ⊆ W**,否则拒收。
补充两条:`open` 的路径若同时出现在 `evaluator.result.path`,那是"模型该创建的产物",更不该 open;
setup 完全没有写文件却有 `open` 的任务直接可疑。

**关键:"setup 在容器里实跑 rc==0" 这道闸抓不到这一类** —— 出问题的是 `open` 步不是
`execute` 步,而 `execute` 的 rc 就是 0(它老实写了文件,只是名字不对);`open` 要 GUI +
VM 里的 Flask `/setup/open_file`,构建容器根本不执行它。已把这条告知 v16 生成侧。

### 86 条重跑

崩溃任务的 `result.txt` 值是 0,而恢复机制是"有 `result.txt` 就跳过",所以必须先把
86 个目录挪走(`results_crashed_20260830/`,**move 不是 delete**)再跑。
注意目录是容器里 root 写的,`shutil.move` 要 `sudo`。

清单 `rerun86.json` 走额外 bind mount 传进容器,`rerun_inner.sh` 把
`--test_config_base_dir`(仍是 wave2-all,要 `examples/` 和 `files/`)和
`--test_all_meta_path`(指新清单)拆开。

### v16 起跑的服务端:4 个 4 卡 serve + 隧道 + 反代

| 作业 | JobID | 节点 | 节点端口 | harness 本地端口 |
|---|---|---|---|---|
| srv-4a | 268322 | g005 | 8041 | 18041 |
| srv-4b | 268323 | g011 | 8042 | 18042 |
| srv-4c | 268324 | g012 | 8043 | 18043 |
| srv-4d | 268325 | g013 | 8044 | 18044 |

脚本 `/gpfs/scrubbed/jy050706/qwen-serve/srv-q4.sbatch`,由 `srv-dx8-v2` 派生,24h(QoS `normal`
的 `MaxWall` 正好 `1-00:00:00`)。**4 卡比 8 卡容易插队**:整节点难等,4 张卡的缝随处都是 ——
提交时 g005/g011/g013/g014 各空 4 张,四个作业全部**立刻 RUNNING,零排队**。

与 `srv-dx8-v2` 逐项一致:BF16 / `kv-cache-dtype fp8` / `max-model-len 262144` /
`reasoning-parser qwen3` / 同一份 override-generation-config / `limit-mm-per-prompt image:20` /
`served-model-name qwen38-27b-local`。三处有意差异:TP4 无 DP;`--mem` 1600G→250G
(主机内存不影响输出,1600G 会让作业在"有卡没内存"的节点上排队);JIT 缓存按端口分家。

**反代**(`/etc/nginx/conf.d/teacher-lb.conf`):`127.0.0.1:18040` → `least_conn` 到四个端点。
runner 只认一个 `--base_url`,有了它就能保持**单进程 `--num_envs 48` + 单 result_dir**,
恢复机制不用改,4 个端点自动均衡(预切 manifest 会让先跑完的端点闲着)。三个非默认值:

| 项 | 默认 | 设为 | 理由 |
|---|---|---|---|
| `client_max_body_size` | 1m | **256m** | 每请求带 10 张 1080p 截图的 base64,几 MB 起步,不改必 413 |
| `proxy_read_timeout` | 60s | **900s** | 81920 token 生成含 prefill 约 510s,runner 侧超时 600s,反代必须更长 |
| `proxy_buffering` | on | **off** | 流式响应不缓冲,否则首 token 延迟被拉长 |

### 两个瓶颈都实测排除了

- **AWS 配额**:`L-1216C47A` 上限 **9705 vCPU**,全账号在跑约 686(108 台 t3.xlarge +
  31 台 t3.medium + 零散)。48 台 t3.xlarge 只占 192,挤不着任何人。
- **harness**:m5.2xlarge(8 vCPU / 30G),**25 路时 load average 0.95**(12% 利用率),
  内存用 8G 剩 21G。48 路外推约 1.8。**不用换机型。**

### `snapshot` 字段是惰性的(v16 不用改 1560 个 JSON)

- `run_multienv_qwen.py:181-192`:`snapshot_name` 由 runner 自己定,aws 路径下取
  `IMAGE_ID_MAP[region][screen_size]` = **AMI id**,和任务 JSON 无关;
- `IMAGE_ID_MAP` 的键是 `(region, screen_size)`,不是应用名;
- 全链路 grep `["snapshot"]` / `get("snapshot")` 扫 runner + `lib_run_single.py` +
  `desktop_env.py` → **零命中**。

实证:v14 跑通的 1782 条,snapshot 取值就是应用名(calc 344 / chrome 298 / impress 265 /
writer 251 / os 219 / gimp 164 / thunderbird 131 / vlc 82 / vs_code 28)。

⚠ 但 `revert_to_snapshot(path_to_vm, snapshot_name)` 确实把 `snapshot_name` 当 `ImageId`
直接塞进 `RunInstances` —— 哪天有人把任务 JSON 的 snapshot 接进这条路,那才会炸。现在没接。

## 9.30 v14g-1782-aws 最终成绩单(2026-08-30 收官)

重跑那 86 条之后,**1782/1782 全部判分**。仍崩溃 13 条(即 §9.29 那个确定性
`open` 路径 bug,writer 5 / thunderbird 6 / os 2),**有效 1769 条**。

| domain | 可行(n / 通过) | 不可行(n / 通过) | 崩溃 |
|---|---|---|---|
| gimp | 163 / **91.4%** | 1 / 100% | 0 |
| vs_code | 23 / **82.6%** | 5 / 100% | 0 |
| chrome | 257 / 74.7% | 41 / 80.5% | 0 |
| libreoffice_calc | 344 / 68.5% | — | 0 |
| libreoffice_impress | 263 / 60.5% | 2 / 50% | 0 |
| os | 99 / 56.6% | 118 / 73.7% | 2 |
| vlc | 82 / 53.7% | — | 0 |
| libreoffice_writer | 241 / 53.6% | 5 / 100% | 5 |
| thunderbird | 116 / 25.0% | 9 / 88.9% | 6 |

```
合计有效 1769   可行 1588 → 63.8%   不可行 181 → 77.3%   混报 65.2%
```

**报数一律用「可行 63.8%」**,混报的 65.2% 被 181 条 refusal 题抬高(机制见 §9.28)。

### 重跑捞回了两个被误判为"废域"的域

| domain | 断线时的读数 | 重跑后 | 说明 |
|---|---|---|---|
| vs_code | **0.0%**(28/28 全崩)| **82.6%** | 之前一条有效数据都没有 |
| vlc | 16.0%(43/81 崩)| **53.7%** | 崩的那批全是假零 |

产物落盘:WSL `results_generated/qwen38-27b-local/v14g-1782-aws/`,
**15G / 1782 目录 / 1782 份 `traj.jsonl` / 37395 张截图 / 0 个 mp4**。
vs_code 从 224K 涨到 174M、vlc 从 1.3G 涨到 2.3G —— 就是这批捞回来的轨迹。

**教训固化**:域级通过率异常低(尤其接近 0)时,先查 `harness_error.json` 计数再下结论。
这一轮我差点把 vs_code 当成"模型完全不会用 VS Code",实际是整域 28 条全崩在凭证上。

## 10 剩余未知

- **UW 出口 IP `205.175.106.79` 稳不稳定**(路线 ② 的唯一结构性风险)。
- **教师 serve 在 12–24 并发下的拐点**(所有路线共有,靠三档探测收口)。
- **镜像等价性**(§8 判定)。
- `AWS_SCHEDULER_ROLE_ARN` 是否存在(决定 TTL 兜底能不能用)。
- 开销走谁的账 / 要不要事前批(账号是 AI2 的)。

## 11 凭据现状

`/mnt/d/research/OSWorld/.env` 现有:`AWS_REGION` / `AWS_SUBNET_ID` /
`AWS_SECURITY_GROUP_ID` + 三个 STS 临时凭据(**2026-08-30T05:20:55Z 过期**)。

坑:Zixian 消息第一段是 **shell 语法**(带 `\` 续行),整段粘进 `.env` 会被
`load_dotenv` 解析成
`AWS_SUBNET_ID='subnet-f9f6699e AWS_SECURITY_GROUP_ID=sg-... \'` ——
**bash source 正常、dotenv 中毒**,只有 runner 吃到坏值。已清理并用
`dotenv_values` 复验。**以后往 `.env` 写东西,一律用真解析器验一遍,别只看键名。**

长跑的凭据方案(优先级从高到低):① runner 跑在 EC2 上 → 挂 IAM instance profile,
凭据由 IMDS 自动轮换,永不过期(仅路线 ①③ 可用);② SSO device-code
(`aws sso login --use-device-code`,Zixian 点一次,缺 `[sso-session ai2]` 的
`sso_start_url`);③ 手抄 export(现状,一天一次,**路线 ② 只能用这个 —— 这是
② 的另一个代价**)。

---

## 附:可复现的只读探针

全部是 `describe_*` / `get_*` / `DryRun=True`,不创建不修改。凭据从 `.env` 读:

```python
import os, boto3
from dotenv import dotenv_values
os.environ.update({k:v for k,v in dotenv_values('.env').items() if v})
ec2 = boto3.client('ec2', region_name=os.environ['AWS_REGION'])
```

- 身份:`boto3.client('sts').get_caller_identity()`
- 子网/路由:`describe_subnets` / `describe_route_tables`
- **安全组要打印 `IpRanges` + `Ipv6Ranges` + `UserIdGroupPairs` + `PrefixListIds`**
  —— 只看 `IpRanges` 会漏掉 SG 互引(我第一轮就漏了)
- 机型可用性:`describe_instance_type_offerings(LocationType='availability-zone')`
- 配额:`service-quotas` ec2 **`L-1216C47A`**
- 谁在用某 SG:`describe_instances(Filters=[{'Name':'instance.group-id',...}])`
- 权限:`run_instances(DryRun=True, ...)` →
  `DryRunOperation`=有权限 / `UnauthorizedOperation`=无权限
