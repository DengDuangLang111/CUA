# The dashboard — what every run must show

https://cua-dashboard-theta.vercel.app · source `dashboard/index.html`,
published from `main` (Vercel's production branch), live numbers written by two
daemons on the lab machine (§4).

**The rule this file exists for: a new run is not "on the dashboard" until it
shows everything the v11 entry shows.** v11 is the reference layout. Adding a
run means filling in the same sections with that run's evidence — not a
reduced version, and not waiting to be asked.

The site covers two halves of the project. **Task generation** (sidebar groups
Current / Baseline / v8 era / Corpus-only / Early) is one view per rollout.
**SFT** (§4) is three views — Overview, Tier-3 Panel, Training runs — and the
same rule applies to it: an arm is not on the dashboard until its nine tasks
are watchable, not merely counted.

---

## 1 The seven sections of a run entry

Copy the v11 / v11-500 entry and fill each in. Order is fixed, because it
reads top-down as "what happened → under what conditions → why you should
believe it".

| # | Section | Content | Source |
|---|---|---|---|
| 1 | **Results so far** | pass rate with (passed/scored of corpus), then one card per domain | live `status.json` |
| 2 | **Conditions** | corpus · generator · max steps · thinking mode · temp/top-p · sleep · envs · screen · result dir | the runner command |
| 3 | **How the corpus is designed** | coordinate draw, difficulty ladder, ambiguity mix, warm start, voice, repair pipeline | spec counts |
| 4 | **Pre-run verification** | one row per layer: scope + what it caught or removed | ship + control logs |
| 5 | **Similarity & contamination** | jaccard · cosine · vs CUA-Gym · vs official-361 · quota drift, each with its gate | `ostg.taskgen.accept` |
| 6 | **Domain mix** | task counts per application and per grading route | manifest |
| 7 | **Trajectories tab** | embedded step player + full-screen link | `ostg.traj_html` |

A run that is finished keeps the same layout; only the pills change
(`live` → `complete N/N`) and any incident worth remembering gets its own
table (see v11's calc incident).

## 2 The live half

`status.json` is the only moving part. The daemon recomputes it every 5
minutes and pushes to `main`; Vercel redeploys; the page re-fetches every 2
minutes, so an open tab updates itself.

Per run the daemon publishes:

```json
"v11_500": {"corpus": 444, "control_checked": 441, "control_bad": 0,
            "scored": 6, "passed": 4,
            "domains": {"chrome": [passed, scored], ...}}
```

Adding a run to the daemon = one more block computed from its result
directory. Keys are read by the page's `design:()` function through
`window.LIVE.<key>`.

Trajectories are heavier: the daemon regenerates them for the **active run
only**, at most every 30 minutes (rebuilding hundreds of megabytes of
screenshots on every 5-minute cycle once starved the push loop and stalled
the whole site). A finished run's viewer is frozen where it is and never
regenerated.

## 3 The SFT half

Three views under the **SFT** group, all fed by `dashboard/sft.json`:

| view | what it is | moving parts |
|---|---|---|
| **Overview** | the story: the regression, the epoch lever, what was ruled out and on what evidence | headline cards read live arm counts |
| **Tier-3 Panel** | the arbiter — every arm on the identical 9 held-out tasks | fully live: arm table, task × arm matrix, trajectories |
| **Training runs** | recipe, runs in flight, the annealing caveat | hand-written |

**The matrix is the point.** Rows are arms, columns are the nine tasks, and
every cell links into that arm's own step player for that task — so an SFT eval
is watchable exactly like a taskgen rollout, at single-task granularity. The
cell shows pass/fail + step count; the tooltip carries distinct-action count,
longest repeated action, and whether the run ever emitted `terminate`.

`sft.json` per arm:

```json
{"key":"q35-e3","label":"e3","group":"fixed data","data":"abs-pilot2",
 "samples":916,"epochs":3,"preserve":"true","passed":3,"scored":9,
 "term":4,"capped":5,"traj":"traj/sft/q35-e3/index.html",
 "tasks":{"<task_id>":{"score":1.0,"steps":19,"distinct":14,"maxrep":3,
                       "term":true,"dom":"chrome"}}}
```

Arms are labelled from a registry in `sft_dash.py`; the pipeline's
`q35-<run>-ep<k>` checkpoints are derived from a `FAMILY` table so a new epoch
snapshot needs no edit. **An unknown arm still appears**, labelled by its
directory name — an unlabelled row is a visible gap, a dropped row is an
invisible one.

**The teacher row is a synthesised arm.** `results_generated/qwen36-teacher/`
is not a rollout: it is Qwen3.6-27B's own passing trajectories for the nine
panel tasks, `cp -al`-hardlinked out of the runs that produced the SFT data
(7 from v11 at ms50, 2 from v11-500 at ms100), with a `PROVENANCE.json` naming
the source run per task. Hardlinks on purpose — no extra disk, and it cannot
drift from the run it was judged in. Its 9/9 is selection, not a score, and the
page says so next to the table. Rebuild it if the panel ever changes.

### 筛选用的训练参数从哪来(2026-08-21)

eval-50 视图可以按**数据集**和**训练参数**筛选、按任意列排序。那些参数不是手抄的
标签,是**被服务的那个 checkpoint 自己的 ms-swift `args.json`** —— 真正产出这份权重
的配置。标签会漂,`args.json` 不会。

```
Tillicum  <checkpoint>/args.json          ← 权威:lr / epochs / max_length /
   │                                         tuner / dataset 路径 / loss_scale
   │  refresh_train_facets.sh(按需跑,一次 ssh 抓全量)
   ▼
osworld-verified-control/train_facets.json ← WSL 本地缓存,按 checkpoint 路径索引
   │  sft_dash.py 的 arm_facets() 纯本地读
   ▼
sft.json 的 eval50.arms[].facets           ← 页面消费
```

**daemon 循环里绝不能有 ssh** —— 一个卡住的 control socket 会拖垮每一次刷新。所以
取数(ssh)和消费(本地读)必须分开,这是上面这条链存在的唯一理由。

- **新臂第一次出结果后,跑一次 `refresh_train_facets.sh`**(它从各臂的
  `MODEL_BOUNDARY.json` 收集 checkpoint 路径,只抓缓存里没有的)。
- 忘了跑不会静默出错:缓存里没有的臂被标成 `known:false`,页面显示
  "params unknown" 并照常列出。**露出一个没参数的行,好过少一行。**
- 早于 `MODEL_BOUNDARY.json` 约定的老臂(basekeep、bskeep、richstock 等)永远是
  unknown —— 它们的服务权重当时就没记录,这是事实,不要去猜。

评测侧的参数(image_max/fold_size、temperature、task set)来自结果目录自己的
`args.json`,一直是本地的,不需要缓存。

### `sft_dash.py` 只有一个真源:CTL 那份(2026-08-22 立规,吃过两次亏)

```
/mnt/d/research/osworld-verified-control/sft_dash.py    ← daemon 实际执行(CTL)
/home/daniel_yan/cua-dash-sft/control/sft_dash.py       ← git 存档镜像
/home/daniel_yan/cua-dash-sft/tools/control/sft_dash.py ← git 存档镜像
```

**规矩:只改 CTL 那份;镜像永远单向从它同步(改完 `cat` 回仓库并提交),
永不反向。** 镜像保留不删 —— 它有 git 历史价值,2026-08-22 恢复那次要不是有
它做对照,连"少了什么"都难确认。

**为什么要立这条**:两次改动互相覆盖,都是"在仓库副本上编辑 → 整文件推回
CTL",于是对方在 CTL 上的改动被整段抹掉。第二次的症状:

```
ARM_PANEL 里 base261/nocap261 两条消失
→ 两个臂落到默认的「已见 50」面板,而它们的 261 道题与那 50 道交集为空
→ base261 scored=0/50 mean=None,而 261 道结果好好躺在磁盘上
→ sft361 整个键消失,OSWorld 361 那一页变成空白
```

**`cp` 覆盖没有冲突标记、没有报错、没有痕迹** —— 它是"静默失效"家族在
**协作层**的成员,判据和 `sft/DATA_PIPELINE.md` §9 里那六个案例完全同型:
信息在传递链上被丢弃,而丢弃点没有断言。区别只在于那六个的传递链是代码,
这个的传递链是两个人的工作流。

**如果非要在镜像上编辑**(比如只有 Mac 侧能访问),那就必须先把 CTL 的当前
版本拉下来做基线,改完用 diff 确认只有自己那几处变化 —— 而不是整文件推。

### Why two daemons

`sft_dash_daemon.sh` works in a **second clone** (`cua-dash-sft`), sparse-checked
out so `dashboard/traj/v11*` — the 683 MB the other daemon owns — is not even
present. Two working trees, disjoint paths, two JSON files: neither can take the
other's `index.lock`, neither can clobber the other's keys, and a raced push
resolves as an ordinary rebase. Both reset to `origin/main` at the top of each
cycle and regenerate, so a reset can never lose anything.

### Publishing trajectories

A `.fingerprint` file (result count + newest `traj.jsonl` mtime) inside the
published directory decides:

- **complete arm** (all 9 scored) → published once and never again. A tier-3 arm
  is frozen the moment its ninth `result.txt` lands, unlike the live rollout.
- **arm still rolling** → refreshed at most every 30 minutes, so the arm the
  machine is currently running is watchable while it runs.
- **re-run of an arm** → fingerprint changes, republishes.

The 30-minute floor is not politeness, it is the same lesson as the rollout
viewer: **JPEGs do not delta-compress**, so republishing on every 5-minute cycle
adds the arm's full weight to git history each time. One arm at a time is
guaranteed by the 3-VM ceiling, so the throttle bounds the cost at ~4
republishes per arm.

Screenshots are recompressed (JPEG q30, 1000 px) **and then deduped by content
hash**, with the surviving filename substituted into `viewer.html`. This matters
more here than anywhere else on the site: a 50-step loop trajectory is ~50
near-copies of one screen, and the SFT panel is full of them. Measured on e3:
**352 files / 77 MB → 148 files / 4.5 MB.** Dedup must run *after* `traj_html`
writes the viewer, or the substitution has nothing to rewrite.

## 3.5 The runs table is the contract (2026-08-15)

**Rule: every rollout run appears in the "All rollout runs" table, and every row
has a trajectory cell — a step-player link once published, 没跑 until then.**
No run is mentioned anywhere on the page without a row here.

This is enforced by construction, not by discipline. The daemon discovers runs
by globbing `results_generated/*/*/args.json` — the runner writes `args.json`
into every result dir, so **a new campaign needs zero dashboard wiring**: it
appears in the table on the next cycle (scored counts, mean, steps/temp/sleep/
history read from its own `args.json` + `MODEL_BOUNDARY.json`), and its
trajectory viewers auto-publish once it has ≥10 results with activity in the
last 3 days. Old finished runs stay listed with 没跑 in the trajectory column
rather than silently vanishing.

Trajectory viewers live at `dashboard/traj/<model-dir>/<run-dir>/` — the slug
is the on-disk path, so it never needs choosing. (`traj/v11-500/` is the one
legacy flat path from before this scheme; its links are kept alive.)

### Live numbers do not ride on Vercel deploys (2026-08-15)

The page fetches `status.json` / `sft.json` from **GitHub raw**
(`raw.githubusercontent.com/.../dashboard/`, CORS `*`, ~5-min CDN cache) with
the relative path as fallback. Freshness therefore depends only on the daemon's
git push. This exists because the Vercel hobby tier allows ~100 deploys/day and
a heavy push day exhausted it mid-campaign: GitHub had current numbers, the
site served 90-minute-old ones, and nothing could deploy until the quota
recovered.

Deploys still matter for the page code and the trajectory viewers. Status
pushes stop consuming quota via `vercel.json`'s `ignoreCommand` — which the
docs confirm **overrides the UI's Ignored Build Step**, so no dashboard setting
is needed (earlier advice that the UI was required was wrong; corrected
2026-08-15). Both `vercel.json` and `dashboard/vercel.json` carry it (only the
project-root copy is read; the other is inert because the project's root
directory is not recorded anywhere we can see):

```json
{"ignoreCommand":
 "curl -sf --max-time 10 https://cua-dashboard-theta.vercel.app/ | cmp -s - dashboard/index.html && exit 0 || exit 1"}
```

**Served-content compare, since 2026-08-15.** The first version diffed
`HEAD^..HEAD` for non-json files — and had a coalescing race that ate a real
change the same day it mattered: Vercel deploys the branch head, so when a
daemon json push lands on top of a code change inside the queue window, the
check sees a json-only diff and skips the code change *forever* (the eval-50
section vanished this way; a human retrigger was needed — and the retrigger
itself could lose the same race). The current form asks the only question that
matters — *does production serve what the repo holds?* — by comparing the
served `index.html` against the repo copy. Race-free by construction,
self-healing (any missed deploy is picked up by the next daemon push, ≤5 min),
daemon pushes still cost zero quota, and a curl failure fails open into a
build. Two-stage since later the same day: the pure content-compare
turned out to skip **traj pushes** (trajectory viewers are Vercel assets too —
the 'single-file app' assumption was wrong within the hour). Current form:
build if the last commit touched anything beyond the two json files (catches
traj pushes on their own merits), otherwise build only if the served shell
differs from the repo copy (catches coalesced code changes). Residual gap: a
traj push coalesced under a json push waits for the next traj cycle (≤30 min);
the shell itself never waits.

**Deploy budget after this**: traj ≤48/day + manual docs ~10–20 ≈ 60–70,
against the hobby tier's ~100/day. Status/sft pushes: zero.

**Viewer publish thresholds (2026-08-15)**: the status daemon publishes a
run's viewers once it has ≥10 scored results — except `eval50-*` runs, which
publish from the FIRST result (user decision: eval arms must be watchable
immediately). The exception is scoped on purpose: a blanket threshold of 1
made the daemon start double-publishing the tier-3 valpanel runs (9 results
each, already hosted by the SFT daemon under `traj/sft/`) — caught mid-cycle
before the push, ~100 MB of duplicate screenshots stopped at the staging
index. Cadence (one traj push per 30-min cycle) is what caps deploys, so the
threshold change costs zero quota.

### 机制图与加固决策(2026-08-15,整日故障复盘后)

本站是三个数据面复用一条 git 通道的分布式系统:

```
status daemon(5min)┐                        ┌ 壳 index.html   ← Vercel 部署(改了必须部署)
sft daemon(5min)   ├→ github main 单分支 →─┤ 数据 *.json     ← 浏览器直拉,免部署
traj 节拍(30min)   │   ignoreCommand 分类   └ 轨迹 traj/      ← Vercel 部署(30min 节拍)
人工提交           ┘
```

一天内的五次故障共享两个病根:**部署分类器的对象(commit)会被 Vercel 合并**,
以及**静默与故障在页面上不可区分**。加固三件套(全部已实装):

1. **SHA 定址取数**:页面先问 GitHub API 拿 main 头 SHA,再拉不可变的
   `/​<sha>/` raw 路径 —— branch-CDN 的 5–15 分钟粘滞整类消失;API 失败降级回
   branch ref。限额账:60/hr/IP,2 分钟一轮 = 30/hr。
2. **健康条**(侧边栏 brand 下):`live/idle/STALLED?` + 最后推送距今 + 两份
   json 的 updated + 壳版本/SHA。判定:有进行中的 run 且 >12 分钟无任何推送
   才红 —— "没新数据"和"链路断了"从此长得不一样。
3. **status-first 循环序(2026-08-15 21:32)**:sft daemon 原本 publish(重,
   渲染 viewer,可达数分钟)在 status(轻,秒级)之前,tier-3 出新臂时把矩阵
   数据节拍从 5 分钟拖到 ~10 分钟 —— 用户第三次报"不刷新"的根因。现为
   status → **立即 commit+push 数据** → publish → status → 周期末推送
   (2026-08-16 00:17 二次修正:光把计算前置没用,推送也压在 publish 后面 ——
   数据现在算完即出门,实测落分到 github ≤5 分钟)。
4. **`tools/dash_probe.sh`**:一条命令核五层(origin 头 / 数据双路对比 /
   线上壳版本 vs 仓库壳版本 / traj 抽样 / WSL daemon 存活),任何改动后跑一次。

**否决的方案**:为 traj 拆第二个 Vercel 项目(能整个删掉分类器)——用户要单站,
且残余风险(traj 推送被合并 → ≤30 分钟自愈延迟)已被健康条变成可见事件,
不值得结构手术。若未来要做,用同域 rewrite 保住单一 URL。

**扩展契约**:加一个新区 = daemon 侧一个数据块(sft.json/status.json)+
前端一个 VIEWS 条目(+ 需要时 traj key)+ probe 里加一行抽样。eval-50 区就是
按这个路径接入的,当模板用。

### ext4 规则的第二次执行(2026-08-16 06:06)

sft daemon 的 clone(cua-dash-sft)当时漏搬,仍在 /mnt/d —— 08-16 凌晨把周期
压到 75s 后立刻现形:`git reset --hard` 单步 2–5 分钟,周期被 git 层吃掉,
"75 秒节拍"名存实亡。照方抓药搬到 `~/cua-dash-sft`(同 sparse 配置):
git status 0.109s,新 daemon 启动 12 秒内完成首推。**规则升级为:任何
daemon 的工作 clone 一律 ext4,无例外** —— 这是同一颗雷第二次爆。

### The repo must live on ext4, not /mnt/d (2026-08-15)

With ~800 MB of trajectory files in the worktree, the daemon's top-of-loop
`git checkout` / `fetch` / `reset` took **4–8 minutes per cycle** on DrvFs
(`/mnt/d`, the 9p filesystem), silently stretching the 5-minute cadence to
~20 minutes. The same checkout on WSL's ext4: **0.2 s** (measured). The status
daemon's clone is now `~/cua-dash`; `/mnt/d/research/cua-dash` is retired for
the daemon (kept only as a spare working copy). The SFT daemon's clone
(`cua-dash-sft`) still lives on /mnt/d — same disease, milder symptom (its
payload is smaller); move it the next time its cadence matters.

### Why the cycle used to take ~70 minutes, and must not again

The PIL compression step rewrites staged screenshots, so a plain `rsync -a`
from the result dir saw every compressed file as changed, re-copied the
original, and re-compressed it — every screenshot, every cycle, ~26 minutes of
no-op work. Screenshots are immutable once the runner writes them: they sync
with `--ignore-existing`, and only the small mutable files (`traj.jsonl`,
`result.txt`) sync normally. If staging ever gets slow again, check this first.

## 4 Hard-won rules

- **Push to `main`.** Vercel's production branch is `main`; pushes to any
  other branch produce Preview deployments that never reach the live URL —
  the site silently serves an old snapshot while every push "succeeds".
- **Never `git add -A` in this repo.** It has committed deletions of
  `.gitignore`/docs and added `__pycache__` binaries. Stage explicit paths.
- **The daemon must survive a bad cycle.** It runs `set +e`, force-syncs to
  the remote before writing (data is regenerated, so a reset loses nothing),
  and logs each stage so a death is diagnosable.
- **Count verdicts from the final corpus, newest re-check wins.** A raw
  control sweep can contain failures that a later re-check cleared; ordering
  the report files matters (`v11-500-recheck` sorts *before* `v500-all`,
  which silently reinstated stale verdicts once).
- **Corpus size = emitted tasks, not spec lines.** Gate-blocked specs stay
  in `specs.jsonl` but never become tasks.

## 生成器与版本管理(2026-08-17 补)

站点由 WSL 上 `/mnt/d/research/osworld-verified-control/` 的三个脚本驱动,
**该目录不在任何 git 里**——镜像已收进 `CUA/tools/control/`(md5 核对):

| 文件 | 作用 |
|---|---|
| `sft_dash.py` | 扫 `results_generated/*/eval50-<key>-<日期>/` 生成 `dashboard/sft.json`;`status`/`publish` 两个子命令,**退出码 3 = 无变化**(不是错误) |
| `sft_dash_daemon.sh` | 30 分钟一轮:status → publish → 提交推送 |
| `dash_status_daemon.sh` | 状态面板同路 |

**加新 eval 臂时**:`EVAL50_ARMS` 里补一行 `key: (label, group, note)`。
**不注册也会显示**(裸 key 当标签)——设计如此:"未标注的行是可见的缺口,
丢掉的行才是隐形的"。已注册:base/basekeep/rich150/richrich/leankeep/
b1epkeep/gb128ep2keep/gb64keep/gb128keep/richstock/leanstock/**bskeep/
bhqskeep/lorakeep**(后三个 2026-08-17 加)。
改完这个文件后要把 WSL 侧和 `tools/control/` 两边同步,md5 对齐。

## 为什么网站数字比 git 里的旧(2026-08-17 澄清)

`dashboard/vercel.json` 的 `ignoreCommand`:**只动 `status.json`/`sft.json` 的
提交跳过部署**,动了任何其他文件才部署。这是刻意的额度节流(守护进程 30 分钟
一次 = 48 次/天,加轨迹推送会超 hobby 档 ~100/天)。

**后果**:数据每 30 分钟进 git,但**网站停在最近一次"非数据提交"的快照**。
想立刻看到新数字,提交任何一个非 JSON 文件即可触发部署。

**分数口径(2026-08-17 修正)**:`mean` 的分母改为**冻结面板的 50**,不是
已跑题数——未跑完的题按 0 计(政策见 `OPS.md`)。旧口径会**系统性抬高
缺题的臂**:gb64keep 在 47 题上读作 44.5%,面板分实为 41.8%。生成器同时
输出 `mean_scored`(÷已跑,备查)与 `missing`(缺题数)。
