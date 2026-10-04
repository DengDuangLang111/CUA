# RL 训练题库：构成与筛选条件

> 本文件只讲 v2 起使用的训练题库是什么、怎么筛出来的、怎么复现。运行进度看 `RL_ENV_PLAN.md` 开头的"现状"块。
> 版本：题库 `rl-pool-20261003d`，2026-10-03 定(用户)。

## 1 一句话

从 CUA-Gym 的 10,910 道题里筛出 **6,847 道训练题**，验证集 24 道(P2 dev，与以前相同)。
- 覆盖：LibreOffice 三件套、VS Code、PDF、VLC、GIMP、桌面多应用，以及在 31 个模拟网站上完成的网页题和跨应用题。
- 排除：与 OSWorld-Verified 重叠的题、CUA-Gym 自留的验证/留出家族、跑不了的题。
- **例外**：GIMP、VLC、Thunderbird 相关的题按用户要求不管重叠收回，但去掉在 OSWorld 中最像的题落在 eval-50 里的 15 道(见 §4.5)。

## 2 文件与版本(追溯用)

| 项 | 位置 | 指纹 |
|---|---|---|
| 训练数据(给 slime 的 parquet) | Tillicum `rl/cua-data/train_20261003d.parquet` | md5 `c99f4896…` |
| 题目 id 清单 | `cua-rl-local` `artifacts/rl-pool-20261003d/train_ids.json`(Tillicum 副本 `cua-data/train_ids_20261003d.json`) | md5 `3603c81c…` |
| 每道题的文件(task.json、初始化脚本、reward.py) | Tillicum `rl/cua-data/cuagym-tasks-20261003/<id>/` | 直接取自 CUA-Gym 包，未改 |
| CUA-Gym 题包 / 索引 | `cua-rl-local/datasets/cua_gym_tasks_v1.tar.zst` / `tasks.parquet` | sha256 `2198e335…` / `33439310…` |
| OSWorld 参照 | OSWorld-upstream `test_nogdrive.json`，361 道 | sha256 `fcb9497e…` |
| 审计 + 题库脚本 | `cua-rl-local`，分支 `pool-expand`：`split-20260922/overlap_audit.py`、`rl_pool.py`(提交 `adaaa68`；每次运行前提交，产物 `summary.json` 记脚本 sha256) | — |
| 审计结果 | `artifacts/overlap-audit-20261003/t025-all/` | — |
| 生成 parquet、运行这些题的代码 | slime-cua 分支 `pool-expand`：`build_task_parquet.py`、`vm/worker_bridge.py`、`vm/mock_sites.py` | 生成 parquet 用 `97a6735` |
| 模拟网站源码 | CUA-Gym-Hub `53205689`(固定在 `vm/mock_sites.json`) | — |

历次版本：`rl-pool-20261001`(2,366 道，v1 用) → `20261003`(6,759) → `20261003b`(6,842，补回 GIMP/VLC/Thunderbird 题，但避开 eval-50；规则多删了 5 道) → `20261003c`(6,862，全部补回) → **`20261003d`(6,847，去掉最像 eval-50 的 15 道)**。

## 3 构成

| 类别 | 题数 | 占比 | 原题库(2,366) | 协议适配 | 原近似题 | 新类别 | 补回(重叠) | 补回(留出家族) |
|---|---|---|---|---|---|---|---|---|
| Calc | 1,465 | 21.4% | 806 | 531 | 84 | — | 44 | — |
| 多应用(桌面) | 1,230 | 18.0% | — | — | — | 1,208 | 22 | — |
| 网页(模拟网站) | 1,041 | 15.2% | — | — | — | 1,041 | — | — |
| Writer | 805 | 11.8% | 615 | — | 178 | — | 12 | — |
| VS Code | 650 | 9.5% | 552 | — | 98 | — | — | — |
| PDF | 626 | 9.1% | — | — | — | 622 | — | 4 |
| Impress | 503 | 7.3% | 393 | 18 | 92 | — | — | — |
| 跨应用(多个模拟网站 + 桌面应用) | 426 | 6.2% | — | — | — | 426 | — | — |
| VLC | 70 | 1.0% | — | — | — | 65 | 5 | — |
| GIMP | 29 | 0.4% | — | — | — | 28 | — | 1 |
| OS | 2 | 0.0% | — | — | — | 2 | — | — |
| **合计** | **6,847** | | **2,366** | **549** | **452** | **3,392** | **83** | **5** |

各列含义：
- **原题库**：v1 用的 2,366 道。
- **协议适配**：初始化后要"打开文件"、打分前要按 Ctrl+S 的题，以前 bridge 跑不了。
- **原近似题**：与 CUA-Gym 留出集相似度 ≥0.30、以前被剔除的题。
- **新类别**：PDF、VLC、GIMP、多应用、OS、网页、跨应用。
- **补回**：§4.5。

按应用名统计(题面或类别里提到该应用，关键词匹配)：
- GIMP 131 道、VLC 130 道、Thunderbird 15 道。多数在多应用题里。
- 用到 Chrome 的约 1,690 道：网页和跨应用题 1,467 道全部用 Chrome；另有 197 道桌面题的初始化会打开 Chrome，26 道题面提到浏览器。

其他特征：

| 特征 | 数值 |
|---|---|
| 初始化脚本 | Python 5,858 道，sh 989 道 |
| 打分前要先执行操作(多为 Ctrl+S) | 577 道 |
| 带 TASK_ID(能确定所属家族) | 4,671 道，来自 775 个家族 |
| 没有 TASK_ID | 2,176 道，只能靠文本相似度防重叠 |
| 难度标注 | hard 2,743、medium 1,786、easy 420，未标 1,898 |
| 题面长度 | 中位 34 词(OSWorld 25) |
| 打分 | `reward.py` 部分分，中位 4 个检查项；训练奖励在 0–1 之间，成功率按满分 1 算 |

## 4 筛选条件

### 4.1 漏斗(从 CUA-Gym 10,910 道)

| 步骤 | 去掉 | 剩下 |
|---|---|---|
| CUA-Gym 全部 | — | 10,910 |
| 不在审计范围(4 道 `vs-code` 拼写的类别、1 道空记录) | 5 | 10,905 |
| OSWorld 衍生家族(家族名以 `osworld_` 开头) | 940 | |
| 与 OSWorld 相似度 ≥0.25 | 587 | |
| 四个应用里没有 TASK_ID 的题 | 837 | |
| CUA-Gym 自留的 dev/留出家族 | 1,612 | |
| P2 dev(作验证集) | 24 | |
| 人工审过否决 + 跑不了 | 58 | |
| **训练题库** | | **6,847** |

"相似度"和"衍生家族"两行已经扣除了补回的 83 道。

### 4.2 与 OSWorld 的重叠审计(`overlap_audit.py`，阈值 0.25)

- **范围**：一道题只要它的应用(跨应用题有多个)里有一个在审计列表里，就参与审计。列表覆盖全部桌面应用、31 个模拟网站和 `os`。
- **对照集**：OSWorld `test_nogdrive.json` 361 道。
- 满足任一条件就排除：
  1. 家族名以 `osworld_` 开头(整个家族排除)；
  2. 题面与某道 OSWorld 题的相似度 ≥0.25；
  3. `reward.py` 的检查项与某道 OSWorld 题(题面 + 评分函数名)的相似度 ≥0.25。
- 相似度的算法：先删掉数字、引号里的内容、单元格区域、文件名，再算 tf-idf 余弦；idf 按 OSWorld 那 361 道统计。
- 0.25 的依据(09-22 重叠审计)：大约在池子的 95 分位，人工看过高分段，真实的同类操作重叠一直延续到约 0.30。
- 两个已知重复的题对作为对照，都必须排在第 1 近邻，否则审计直接报错退出：`de0be554` ↔ `66399b0d`、`38b4cbf8` ↔ `01b269ae`。

### 4.3 家族与留出(`rl_pool.py`)

- **没有 TASK_ID 的题**：在 Calc、Writer、Impress、VS Code 这四个按家族划分过训练/验证/留出的应用里排除，因为分不清它属于哪个家族；在其他应用里保留，因为那些应用不分家族。
- **CUA-Gym dev/留出家族**：留给题库内的泛化评测，不进训练。只有 §4.5 补回的题例外。
- **不再剔除**与留出集相似的题(用户 10-03)。

### 4.4 运行协议(这道题的 bridge 能不能跑)

- 初始化文件必须是 py 或 sh 脚本。
- 初始化步骤只能是 download、execute、launch、open、sleep；打分前的步骤只能是 execute、sleep。
- 初始化不能上传答案文件，即文件名不能含 golden/solution/expected/answer。
- `reward.py` 必须打印 `REWARD: <分数>`。
- 网页和跨应用题必须用占位符 `__CUA_GYM_<站点>_URL__` 写站点地址，而且站点要在 `vm/mock_sites.json` 里；把地址写死的题排除。
- `split-20260922/exclude.json` 里人工审过否决的 7 道排除。
- **不要求**逐题人工审核。坏题在训练中第一次抽到时就会被识别并记进跳过名单，以后不再抽，每道只付一次代价：初始化失败的、初始状态就已经得分的(r0 > 0)。打分脚本崩溃的不进名单，按环境问题单独计数。见 `RL_VM_ENVIRONMENT.md` §5。

### 4.5 补回 GIMP、VLC、Thunderbird 题(用户 10-03："全都加回来，不要管重合先"；随后"这15道剔除掉")

- **哪些题**：应用或题面匹配 `\bgimp\b|\bvlc\b|thunderbird`、但被重叠审计或家族划分排除的题，跳过这两条规则(运行协议仍然要满足)。共补回 88 道：83 道是因为与 OSWorld 重叠被排除的，5 道来自 CUA-Gym 的留出家族。
- **去掉的 15 道**：因重叠被排除、在 OSWorld 中最像的题(按题面或检查项)又正好在 eval-50 里的(`--eval-ids`)，主要是 GIMP 抠图去背景，以及 Thunderbird 文件夹整理成表格。来自留出家族的那 5 道审计时本来就不和 OSWorld 重叠，不适用这条规则。
- **剩余风险**：补回的 83 道仍是和 OSWorld 同类的题，只是最像的题不在 eval-50 里；OSWorld 全集上 GIMP、VLC、Thunderbird 题的成绩要谨慎解读。
- **没补的**：
  - 20 道 Calc 等题，只是初始化脚本里顺手关掉了 GIMP 或 VLC，并不是这三个应用的题；
  - 3 道跑不了的题。

## 5 与 OSWorld-Verified 的分布对比

| 类别 | OSWorld-Verified 361 | eval-50 | 训练题库 6,847 |
|---|---|---|---|
| 多应用 | 93(25.8%) | 12 | 1,230(18.0%) |
| Calc | 47(13.0%) | 7 | 1,465(21.4%) |
| Impress | 47(13.0%) | 7 | 503(7.3%) |
| Chrome | 46(12.7%) | 3 | 没有考浏览器本身(设置、书签等)的题；1,467 道网页和跨应用题都在 Chrome 里操作 |
| GIMP | 26(7.2%) | 4 | 29 道 GIMP 类别；题面提到 GIMP 的 131 道 |
| OS | 24(6.6%) | 4 | 2 |
| Writer | 23(6.4%) | 3 | 805(11.8%) |
| VS Code | 23(6.4%) | 4 | 650(9.5%) |
| VLC | 17(4.7%) | 3 | 70 道 VLC 类别；题面提到 VLC 的 130 道 |
| Thunderbird | 15(4.2%) | 3 | 0 道 Thunderbird 类别；题面提到的 15 道；另有网页邮箱 Gmail 281、Outlook 56 |
| PDF | 0 | 0 | 626(9.1%) |
| 不可完成题(正确回答是 FAIL) | 27(7.5%) | — | 0 |

## 6 运行这些题需要的环境

VM 里装了什么、bridge 怎么跑题：见 **`RL_VM_ENVIRONMENT.md`**(唯一记录)。这里只留与题库有关的两条：
- **模拟网站**：`vm/mock_sites.py` 在每台 VM 主机上装 Node 20.20.2 和 CUA-Gym-Hub，31 个站点各占一个固定端口(18500–18530)常驻，约 3 GB 内存。VM 通过 `host.docker.internal` 访问。
- 旧版 bridge 跑不了新题：它会漏掉 sh 初始化、"打开文件"、Ctrl+S 和站点地址替换。

## 7 已知问题与未验证项

- **真 VM 验证**：在训练镜像上做的 19 道针对性验证，以及已知坏题清单(`544b7d84`、`5cca1ce3`、`554cc85b`、`93d4677f`，以及 `ca775249` 等 5 道)，见 `RL_VM_ENVIRONMENT.md` §5、§8。题库没有逐题在 VM 上跑过；坏题靠跳过名单在训练中淘汰。
- **网页题的接口不防作弊**：题目脚本用的是不带口令的旧接口，agent 在终端里能直接改网站数据。训练中要留意网页题成功率有没有异常上升。
- **没有 TASK_ID 的 2,176 道题**只靠文本相似度防止和 OSWorld 重叠，比带 TASK_ID 的题风险高。
- **不可完成题为 0**：训练可能让模型更不愿意回答 FAIL。

## 8 复现

```bash
# cua-rl-local，分支 pool-expand；需 Python ≥3.14(读 .tar.zst)
python split-20260922/overlap_audit.py --bundle datasets/cua_gym_tasks_v1.tar.zst \
  --osworld ../OSWorld-upstream/evaluation_examples --manifest ../OSWorld-upstream/evaluation_examples/test_nogdrive.json \
  --apps <8 个桌面应用 + 31 个 *_mock + os，逗号分隔> --out <dir> --text-threshold 0.25 --check-threshold 0.25 \
  --control de0be554:66399b0d --control 38b4cbf8:01b269ae
python split-20260922/rl_pool.py --audit <dir>/tasks.jsonl.gz --bundle <解开的题包目录> \
  --split artifacts/split-20260922/split.json --panel artifacts/split-20260922/p2-panel.json \
  --exclude split-20260922/exclude.json --mock-sites ../slime-cua/examples/cua_desktop/vm/mock_sites.json \
  --readmit '\bgimp\b|\bvlc\b|thunderbird' --eval-ids artifacts/eval50/osworld_eval50_tasks.jsonl --out artifacts/rl-pool-<date>
# Tillicum(slime-cua pool-expand)：题目目录 + id 清单 → parquet
python examples/cua_desktop/build_task_parquet.py <train_ids.json> <题目目录> <out.parquet>
```
