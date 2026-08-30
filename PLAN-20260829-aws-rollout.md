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
