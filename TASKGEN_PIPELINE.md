# The taskgen pipeline

> **datagenv12(分支,未合 main)**:fmt-w1 加 `intent=restyle` 与规则式
> `grade=pptx` / `grade=image`(宿主 python-pptx / PIL 判呈现属性)。动机与闸 →
> `PLAN-20260818-datagenv12-fmt-w1.md`。**2026-08-20 起该分支扩为 targeted-200
> 定向补数据 campaign 的载体**(缺口配额、`--focus` 补丁设计)→
> `PLAN-20260820-targeted100.md`。本文其余部分描述 v11.1 行为。

How a task goes from a coordinate to a scored trajectory, what each stage
catches, and what it costs. Every check listed here exists because its
absence once shipped a defect — the "caught in practice" column is the
receipt. Commands live in [RUNBOOK.md](RUNBOOK.md); the reasoning behind the
corpus design lives in [EXPERIMENTS.md](EXPERIMENTS.md).

```
  coordinate  ──▶ gen ──▶ ship ─┬─ prebuild ─ re-emit ─ accept ─ scan ─┬─▶ control ──▶ rollout ──▶ SFT
   (taxonomy)      │            │                                      │      (VM)       (VM)
                   │            └── text only, no VM, seconds ─────────┘
                   └── LLM writes instruction + setup + probe
```

Two rules shape the whole thing:

1. **Cheap layers first.** Anything a regex can decide never reaches a VM.
   A VM minute costs ~1000x a gate check, and a rollout minute more.
2. **Every layer has a blind spot, and it is written down.** A check that
   passes is not evidence of health unless you know what it *cannot* see.
   Two of this project's worst incidents came from trusting a green check
   that structurally could not detect the defect (§ Blind spots).

---

> **v14g(2026-08-28,分支 `datagenv14`,未合 main)**:分布策略外化为配方
> (`recipes/*.yaml`,轴权重 + cells 硬钉 + forbid 约束,溯源四元组入 spec);
> 抽签轴加 evaluator 族(口径 `reference/EVAL_FAMILY_TAXONOMY.md`);新增四个
> gold grade(deck/doc/image/table_gold),ship 内插 bake 阶段(容器造
> seed+gold、host 端不动点 0/1),evaluator 用官方 `cloud_file` 从本机 serve
> 拉取。命令链 RUNBOOK §4.6,设计与验收 `PLAN-20260828-v14g-gold.md`。
> 下文描述的是 v11–v14 主线行为,对 v14g 仍成立的部分不重复。

## 1 gen — draw a coordinate, ask for a task

`ostg.taskgen.gen` draws from the taxonomy product **intent(5) × domain(13) ×
difficulty(5) × ambiguity(4)** = 1300 cells, and asks the generator model
(Opus 5) for one task per cell: an instruction, a setup script, a probe.

- **Quota is charged on keep, not on draw** — a rejected spec returns its
  cell to the pool, so gate rejections cannot bleed an axis (they once
  drained d4+d5 to 21% of a 35% target).
- **Shards** partition the cell space so N processes generate at once over
  disjoint coordinates; **waves** are sequential batches with an audit
  between them, which is where saturation gets caught.
- **`--spent-from`** seeds the ledger from earlier corpora so a new campaign
  does not re-draw cells already spent.
- **Repair before reject**: a spec failing a *fixable* gate (stray filename,
  absolute path, over-length) gets one ~200-token instruction rewrite and is
  re-gated. Setup, probe and coordinates are never touched, so repair cannot
  change what is graded. Measured: 7.6 keeps/batch vs 1.9 without it.
- **The `apps` axis is a closed 10-entry catalog** (`gen.py`'s `APPS` dict:
  the 8 GUI apps + `files` + `terminal`), enum-constrained in the tool
  schema — the model cannot emit anything outside it. There is no
  no-artifact "settings toggle" entry, so a whole task class (bluetooth,
  font size, default Python version, screen lock — no persistent artifact
  to grade) is structurally unreachable, not merely under-sampled. Detail
  and proposed fix: `IDEAS.md`「2026-08-24 批次 §L」.

**Hard gates** (reject or repair, at generation time):

| gate | why it exists |
|---|---|
| no filename / absolute path at ambiguity≥2 | the instruction must stay vague while the probe stays exact |
| difficulty-scaled length caps (150/250/300 chars) | length predicts failure on every corpus measured |
| terse/sloppy ≤ 40 words | register must be real, not decorative |
| warm ⟺ open_path consistency | a cold task may not presume an open workspace |
| setup compiles; probe prints PASS/FAIL | a spec that cannot run is not a task |
| no bare `--convert-to odp/pptx` | that filter path exists on no machine (`odp:impress8` does) |
| **no leaked prompt tag** (`</setup>` etc.) | the model sometimes glues the prompt's closing tag into a field value; the setup becomes a shell syntax error, the starting state is never built, and the task scores 0 looking exactly like a weak agent |

The tag leak is also **sanitized automatically** before gating — the gate is
only the backstop.

## 2 ship — everything that can be decided from text

One command, four stages, no VM. Any hard failure stops the ship.

### 2.0 prebuild — office files are made on the host, not in the VM

**The single most important stage, and the least obvious.**

A setup that runs `soffice --convert-to` inside the evaluation VM leaves
GNOME's compositor unable to **paint** the window later opened from that
file. `wmctrl` and `xprop` report the window mapped and focused; the agent's
screenshot shows a bare desktop. The agent then burns 50 steps trying to
summon a window that, to it, does not exist.

`ostg.taskgen.prebuild` runs each soffice-carrying setup once in a throwaway
container with a real LibreOffice, snapshots the files it produced, and
rewrites the setup to materialize them via `base64 -d`. The starting state is
byte-identical; only the route changes, from "convert at eval time" to
"decode a prebuilt blob". Official OSWorld sidesteps the same trap by
downloading pre-made files; this is the self-contained equivalent.

Design details that matter:

- **Nothing is hardcoded.** The real setup runs, and whatever files appear
  under `/home/user` are discovered — any format, any count, any path.
- **App profile side-effects are excluded.** Running soffice also creates
  ~40 files of LibreOffice profile; embedding those bloated a task from 7 KB
  to 264 KB and shipped the very profile whose creation causes the bug. A
  hidden path is kept only when the setup itself wrote into it — which is
  how genuine dotfile fixtures (a Thunderbird profile, a Chrome preference
  store) survive.
- **Fail-safe.** Build failure, no fixtures, or >2 MB → the spec is left
  untouched and a warning names it, rather than silently shipping something
  wrong.
- **The build container mirrors the VM toolbox** (LibreOffice, PIL,
  openpyxl, ffmpeg, zip, poppler) so setups that also draw an image or cut a
  clip still run.
- Setups are fed on **stdin**, not through a heredoc — heredoc wrapping
  mangled five multi-kilobyte setups and left them unrewritten.

### 2.1 re-emit

Task JSON is rebuilt from specs with the *current* emitter, so emitter fixes
reach corpora generated earlier. Consequence worth knowing: **a corpus on
disk is not frozen to the code version that generated it** — provenance
lives in the run directory name, not in a git branch.

### 2.2 accept — six gates over the whole corpus

| gate | threshold | what it protects |
|---|---|---|
| instruction jaccard, any pair | < 0.40 | no two tasks share wording |
| instruction tf-idf cosine, any pair | < 0.50 | no two tasks are semantic twins |
| vs CUA-Gym (10,909 refs) | < 0.50 | no overlap with the benchmark the SFT model may be judged on |
| vs official OSWorld-361 | < 0.50 | not a paraphrase of the official corpus |
| quota drift per axis | ≤ ~2% | the coordinate design survives the culling |
| entity reuse across tasks | < 3 | no name/company/file recycled |

Also reported, not gated: distinct-bigram ratio (phrasing variety) and
grader-signature pairs. **The grader-signature list is noise** — 1355 pairs
on a 450-corpus, never acted on; treat it as verbose output.

### 2.3 scan — the defect classes that pass every mechanical gate

Static heuristics for grader defects that controls structurally cannot see.

**Each class declares a severity next to its rule**, and the two consumers act
on the severity alone — adding a class needs no change anywhere else:

| severity | gen's gate does | ship's report does |
|---|---|---|
| `REVIEW` | nothing | print for adjudication |
| `REPAIR` | reject as repairable → the instruction is rewritten and re-gated | print |
| `BLOCK` | reject outright (the fixture is wrong; words cannot fix it) | print |

The `rigid-name` class is `REPAIR` for a structural reason worth stating:
the ambiguity gate forbids the instruction from naming files, while the probe
must still decide alone — so the model relieves the squeeze by inventing a
name in the probe that the agent was never told, and the task becomes
unwinnable. Repair resolves it in the direction that keeps both invariants:
the instruction gains a naming *rule* ("named after the log"), which is a
description, not a path, so the ambiguity level is preserved. The principle
generalizes: **a grader may only be as strict as the instruction is
explicit** — if the user did not say what to call it, the grader must not
care.

| class | signature | caught in practice |
|---|---|---|
| missing source data | instruction cites content the setup never writes | 1 (v11) |
| rigid output naming | probe demands an exact filename the instruction never gave | 4 (v11), more in later waves |
| dated constant | "this year" in the instruction, a hard-coded year in the probe | 1 (v11) |
| absent-key default | `.get(key, True)` on an app config whose factory state is absent-and-off | 1 (v11) — the task was unwinnable |
| inverted verdict | `print('FAIL' if hit else 'PASS')` | 1 (v11, also caught by control) |
| fake media | media files fabricated from literal bytes | 1 (v11) |

Tuning notes: same-base-name exports, conventional names (`README.md`,
`__init__.py`), and warm folder-target tasks are exempt — those were false
positives.

## 3 control — the VM negative check

Fresh VM per task: run the setup by hand and read its **exit code** (OSWorld
never does), execute the `open` steps, then call `evaluate()` on the
untouched desktop. **An idle agent must score 0.**

Catches: a setup that fails silently, a probe that crashes (the task would
otherwise vanish from the denominator), a probe that passes without work
(SFT poison), and — since 2026-08-10 — a **warm start that never became
visible**.

That last lane is judged from **the agent's own screenshot**, not from the
window manager. The wmctrl version of this check passed the entire calc
domain, which then scored 0/15 three times over: existence is not visibility.

## 4 rollout — the referee

Qwen3.6-27B against the real VM, official protocol (50 steps, temp 0.6,
top-p 0.95, 3 environments, thinking captured). Whatever slipped past every
earlier layer shows up here — but as an *ambiguous* signal, because a
grader defect and a weak agent produce the same 0. Resolving that ambiguity
means frame-by-frame adjudication, which is why the cheap layers matter: at
~4 adjudications per 100 tasks, a 451-task corpus would otherwise cost ~19
manual investigations.

Recovery is built in: re-running with the same `--result_dir` skips scored
tasks and redoes the rest, which heals Slurm handoffs, memory restarts and
requeued victims in one stroke.

## 5 optional positive checks

- **gold injection** (`ostg.taskgen.gold` + `control --gold`): inject a known-good
  end state and require 1.0, proving the grader *can* pass. **Redundant when
  a rollout follows immediately** — the rollout is a stronger positive test.
  Worth running only when shipping a corpus without rolling it.
- **LLM audit** (`ostg.taskgen.audit`): a third-party model reads instruction +
  grader and reports coverage gaps and **world assumptions** (beliefs about
  the live web or an app's defaults baked into grader constants). This is the
  only layer that covers wrong-world-belief defects in general; `scan` covers
  one narrow pattern of it. Use a fixed judge across corpora — judge
  severities differ measurably between models.

---

## Blind spots — what each layer cannot see

| layer | blind to | covered by |
|---|---|---|
| gen gates | anything semantic | scan, audit |
| gen's `apps` axis | task types with no artifact to host (OS settings toggles) — not a gate rejection, the schema enum makes them unaskable | nothing yet — see `IDEAS.md` §L |
| prebuild | non-office environment traps | control, rollout |
| accept | everything except similarity/quota | scan, control |
| scan | defects with no textual signature | audit, rollout |
| control | any defect that also fails on an idle desktop (e.g. a probe with a wrong world belief) | audit, rollout |
| audit | anything only execution reveals | rollout |
| rollout | tells you *that* a task failed, not *why* | frame-by-frame adjudication |

**The two incidents worth remembering**, both from trusting a green check:

1. `windows=2` from wmctrl meant "a window object exists", not "the agent can
   see it". A whole domain shipped and scored 0/15 three times.
2. A control pass means "an idle agent scores 0". It says nothing about
   whether a *working* agent can score 1 — the absent-key probe passed
   control and was unwinnable.

## Cost model (measured, 450-task scale)

| stage | wall clock | resource |
|---|---|---|
| gen (4 shards) | ~3 h | API |
| prebuild | ~30 min | 1 container |
| accept + scan | seconds | none |
| control | ~1 day at 3 lanes | VM |
| rollout | ~3–4 days at 3 envs | VM + served model |

## Corpus health, v11-500 (450 tasks, 2026-08-10)

Every gate green: jaccard 0.38 · cosine 0.49 · vs CUA-Gym 0.47 · vs
official-361 0.46 · quota drift 2% · entity reuse 0 · bigram 0.69.

**450 tasks occupy 450 distinct coordinate cells** — no two share an
(intent × domain × difficulty × ambiguity) combination. Median 32 words,
32% at ≤25 words, 8% carry an absolute path (official: 5%), 63% cross an
application boundary, 68% warm start, 151 tasks carry prebuilt fixtures.
Intent, difficulty and ambiguity all within 2% of quota; 13 business
domains; 9 applications; grading routes probe 374 / table 63 / browser 14.

The corpus is named **v11-500**: it is the v11 pipeline unchanged, drawing 500 more
coordinates from the same 1300-cell taxonomy, with every v11 fix already in force.

From 472 generated: 5 sanitized (leaked tags), 1 culled (broken setup that
could never build its own fixture), 17 culled by similarity over two iterative rounds, 2 instructions repaired
and 1 task blocked by the severity-aware scan. 3 review items remain, all
adjudicated benign.

## 附:v11 与 v16 两代语料的生成原始设置对照(2026-09-03 整理,来源:运行目录 args.json / specs 字段 / RUNBOOK §1 §12 / JUDGING §2 §2b §4)

| 环节 | **v11(r5 语料,362 条)** | **v16(判官制,554 / strict 340 条)** |
|---|---|---|
| 代码 | `ostg-v11.1`(gen/ship/control/rollout/judge/arb/curate),wrapper `os-simple-taskgen-v8` | `ostg-v16`(branch `datagenv16`):`gen16` / `emit16` / `strongjudge` / `curate16` |
| 生成模型 | `claude-opus-5`,thinking **关**,强制工具调用,max_tokens 48000 | `claude-opus-5`(经 ppapi,`PPAPI_MODEL` 默认),同 v11 regime |
| 生成契约 | 每题 = 指令 + setup + **probe(程序判据)**,+ 修复回路(可修闸失败时 ~200 token 只重写指令) | 每题 = 指令 + setup + `apps_used` + `infeasible_reason`,**无 probe/无 verifier**,强判官当唯一裁判 |
| 抽样空间 | intent(5:info_seeking/transform/configure/create/repair)× domain(13)× difficulty(**5 档**,d3+ 双应用,配额 .15/.25/.25/.20/.15)× ambiguity(4,配额 .10/.30/.30/.30)× voice(4);apps 封闭 10 项目录 | 同一套 lottery(taxonomy.cells + recipe + draw_vocab)只换契约:difficulty 改 **3 档 = 计数应用数 = 判据数**(均分 ⅓);intent 换 **19 族**(discover/understand/consume/create/creative-production/transform/correspond/review/organize/plan/analyze/execute-workflow/paperwork/automate/maintain/recover/protect/self-presentation/follow-procedure);os 域按 state 45/terminal 45/files 10 硬配;指令长度按官方分位带 50–250/120–320/200–400 |
| 生成命令 | 100 集:与 v10 同命令同 seed(`--n 5 --batches 13 --shard i/2`);500 集:`--n 5 --batches 29 --shard i/4 --seed 20260812 --spent-from v11-s0/s1 --avoid-corpus cua-gym --refill 2` | `gen16 --n 1500 --seed 1661 / 1662 --workers 6 --seed-rate 0`,各 780 格(prod-a / prod-b) |
| 生成时闸 | 无文件名/绝对路径(ambiguity≥2)、长度上限 150/250/300、terse≤40 词、warm⟺open_path、setup 可编译、probe 打 PASS/FAIL、无 `--convert-to odp/pptx`、无泄漏提示标签;可修者先修再判 | 只留机器能查的:长度带、应用计数 = 档位、ambiguity 路径规则、死短语 |
| ship / accept | `ship`:prebuild 办公文件在宿主机 → re-emit → 六道闸(指令 jaccard<.40、tf-idf<.50、vs CUA-Gym<.50、vs 官方 361<.50、配额漂移≤2%、实体复用<3)→ scan 静态缺陷类(rigid-name 等) | `emit16`:合并+去重 → 碰撞参照(osworld examples、cua-gym tasks)→ prebuild → setup smoke → task JSON |
| control(阴性对照) | 每题新 VM:跑 setup 读退出码 → 执行 open → 对未动桌面 `evaluate()`,**空转 agent 必须 0 分**;warm 可见性按 agent 截图判 | 无(没有 probe 可对照;smoke 只验 setup) |
| 产出题数 | 100 集 100 题(`v11-all`)+ 500 集 **444** 题(`v11-500-final`);单/多应用 40/60 配额 | main **1195** 题(specs 599+596)+ pilot **191** 题;manifest 里 multi_apps 790/1195 |
| rollout(教师) | `qwen38-27b-local`(Qwen3.8-27B,FP8 serve),**WSL docker**,窗 **20/10**,max_steps 50,temp 1.0 / top_p .95 / top_k 20,max_tokens 81920,sleep 3.0,3 env(100 集)/ 1 env(500 集);运行 `v11-100-t1-20260814`、`v11-500-t1ms50-20260814` | 同模型同采样,**AWS provider**,窗 **10/1**(= 学生训练窗),max_steps 50,sleep 3.0,20 env(main)/ 5 env(pilot);运行 `v16-main-1`、`v16-pilot-200` |
| 判定 | ① probe 程序判分(checker);② 盲评判官 trajaudit(Qwen3.8-27B v1 low + Opus 5,10 帧 + 动作 + 90 字思考摘要,temp 0);③ arb 仲裁(Opus 5 + extended thinking,checker 与判官分歧时);④ stepaudit 步级 | 强判官 `strongjudge` v3:Opus 5,`--truth all --think 0 --answer 1 --last 8`(初始帧 + 末 8 帧、全部动作、agent 成果自述,不给思考);规则闸拦 agent 自称 FAIL/空轨迹(gate),另 `--gate 0` 复核 |
| 准入 | `curate`:判官提名、仲裁定罪、只有证据能封杀 → tier1/tier2/rescue/drop:100 集 69/1/10/0,500 集 209/41/44/0;shipped 362 条 | `curate16`:verdict=success 且**每一条**要求 done=yes → **554**(40% of 1386);`--strict` 再加:无 critical 失败、无证据违规、无 cannot_tell、无 inferred、derived=10 → **340**(24.7%) |
| 末步 | `terminalfix` 三路(48 原样 / 259 补指令 / 69 重写)→ **100% 显式 terminate** | 原生 88–100% 散文结尾;`mixbtf` 版补做终止规范化(实测对分数 0 影响,RESULTS §5.36) |
| build | `ostg.sft.build --whole-traj-filter --terminal-rewrite`,r5 = Bhqs2t 第 5 版重建(meta 带溯源);nocap 版 `--think-cap 0`(r5 用 2048);img10/fold1 | `build --include admitted --whole-traj-filter --think-cap 2048 --image-max 10 --fold-size 1`(strict 版另 `--terminal-rewrite` + `verify --require-terminate`) |
| 样本 | 6,474(v11100 1,358 + v11500 5,116) | 13,372(main + pilot,准入版);strict 版 + WebSTAR 步级过滤后 7,311 行(含 r5 半区) |

**两代之间真正的变量**(除了题本身):(1)v16 没有程序判据,准入完全靠判官;(2)教师 rollout 的观察窗
v11 是 20/10、v16 是 10/1;(3)v16 的 multi_apps 配额 66%(790/1195)但 strict 后真 multi 只剩 16.5%(FA §12);
(4)v11 有 control 阴性对照,v16 没有;(5)v16 末步散文(已证明不影响分数)。

### 附.1 两代抽样空间逐轴枚举(2026-09-03,源:`ostg-v11.1/ostg/taskgen/taxonomy.py`、`gen.py`;`ostg-v16/ostg/taskgen/taxonomy.py`、`gen16.py`)

**共用不变的三轴**(v16 的 `taxonomy.cells` 原样复用 v11 的 lottery):

| 轴 | 取值 | 配额 |
|---|---|---|
| domain(13) | finance · healthcare · education · logistics · human_resources · legal · marketing · scientific_research · retail · real_estate · travel · manufacturing · nonprofit | 均匀(走完整乘积空间) |
| ambiguity(4) | a1 explicit(点名文件与位置,逐条列要求)· a2 functional(按"它是什么"描述对象,不许文件名/路径,setup 保证唯一)· a3 deictic(目标已在屏上:"this sheet",无文件名)· a4 outcome(只说要达到的结果和约束,操作由 agent 推断) | .10 / .30 / .30 / .30 |
| voice(4) | terse(只说目标和约束)· sloppy(小写、缩写、无标点)· polite("Please…")· contextful(目标 + 一条改变"正确"定义的上下文:收件人/期限/约束) | .30 / .10 / .25 / .35 |

**v11 独有轴**

| 轴 | 取值 | 配额 / 规则 |
|---|---|---|
| intent(5) | info_seeking(找已有信息并按要求汇报)· transform(改形状/格式/顺序)· configure(改设置或环境状态)· create(从头产出工件)· repair(找错并改) | 最少使用优先,硬保证均匀 |
| difficulty(5) | d1 一应用一要求 · d2 一应用两三要求 · d3 两应用一到三要求(跨一次边界)· d4 两应用四要求含排序规则 或 三应用一到三要求 · d5 三应用以上四要求含排序/平局规则 | .15 / .25 / .25 / .20 / .15(d3+ 为多应用,合计 60%) |
| artifact(12) | spreadsheet · text_document · slide_deck · pdf_or_archive · raster_image · source_code · filesystem · terminal_output · browser_tab · preference_store · app_data_store · desktop_session | 由 intent 决定候选集(INTENT_ARTIFACTS),按轮转取 |
| primary app | artifact → 承载应用表(ARTIFACT_HOSTS,按官方 361 频次排序)轮转;apps 目录封闭 10 项:calc · writer · impress · chrome · gimp · vlc · thunderbird · vscode · files(→os)· terminal(→os) | 无目标份额(v14 起才有 APP_MIX) |
| warm | browser_tab 或 a3 必 warm;其余 GUI 主应用 65% warm;files/terminal 不 warm | 布尔 |
| source | browser_tab → live_web;transform/repair → self;其余轮流 second_local_artifact / prompt_literal | — |
| grade | browser_tab → browser(官方 url 匹配)· spreadsheet → table · 其余 probe | 由格子决定,模型不能降级 |

**v16 独有轴**(gen16 在 cells 之后重画:primary → intent16 → combo → warm → seeds → os_kind;legacy 的 intent/artifact/grade/infeasible 丢弃)

| 轴 | 取值 | 配额 / 规则 |
|---|---|---|
| difficulty(3) | d1 一个计数应用(或纯系统),一个判据 · d2 两个计数应用两判据,数据跨边界两侧都判 · d3 三应用三判据 | ⅓ / ⅓ / ⅓;计数应用 = calc/writer/impress/chrome/gimp/thunderbird/vlc/vscode,os/terminal/files 是设施不计数 |
| intent16(19) | discover-information · understand-material · consume-media · create-content · creative-production · transform · correspond · review-annotate · organize · plan · analyze-decide · execute-workflow · paperwork · automate · maintain · recover · protect · self-presentation · follow-procedure | 近均匀洗牌发牌;creative-production 只发给 impress/gimp/writer 主应用 |
| primary(9) | os .060 · chrome .215 · calc .186 · impress .131 · writer .120 · gimp .086 · vscode .081 · thunderbird .064 · vlc .057 | OFFICIAL_MIX(官方参与份额解出),最大余数法配额 |
| secondary(combo) | d2 一个、d3 两个伴应用,按 COMPANION_MIX 权重抽(chrome 40 · calc 25 · writer 17 · impress 11 · vscode 10 · gimp 9 · thunderbird 9 · vlc 6);再以 d2 56% / d3 47% 把一个伴应用换成 os | 复制官方 multi_apps 的 app+os : GUI-GUI ≈ 6:4;闸按抽到的组合精确校验 |
| os_kind(主应用 = os 时) | state 45% · terminal 45% · files 10% | 硬配(自由生成曾塌成 193/197 全是文件操作) |
| warm | 0..(手上 GUI 应用数)均匀取整数 = 预开应用个数;a3 至少 1;os 不预开 | 闸校验 open_paths 数 = warm |
| action seed | 每主应用 8–10 个操作菜单(如 calc:freeze panes/chart/autofilter/pivot…;若存在 seedpools.json 则 45–60 个 LLM 枚举操作覆盖) | 默认 80% 手牌带 seed;**生产跑用 `--seed-rate 0`,即全部不带** |
| len_target | 从 LEN_BANDS 抽:d1 50–250 · d2 120–320 · d3 200–400 字符 | 闸只查带边(×0.7 / ×1.3) |
| infeasible | 轴已删除(08-30),全部 feasible;模型仍须填 infeasible_reason 字段 | — |

v16 的 `taxonomy.cells` 内部仍按 legacy 常量走(difficulty ⅓×3、APP_MIX os .35…、infeasible 7.5%),但这些结果随即被 gen16 覆盖或丢弃;有效轴以上表 gen16 列为准。
