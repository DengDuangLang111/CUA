# The taskgen pipeline

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
