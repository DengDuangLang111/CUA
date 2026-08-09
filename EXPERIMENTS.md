# Synthetic task generation for OSWorld — design, experiments, results

Status 2026-08-09. **v9 (§9) is the standard pipeline going forward** — the
ambiguity and voice axes are part of every future corpus, and the v9 tasks are
what the next trajectory rollout runs. v8 remains the corpus of the rollout
currently in flight. Sections 1–3 describe the running system and the design
behind it; sections 4–9 are the experiments that produced it, with sample
sizes attached so weak evidence can be told from strong.

---

## 1. What is running now — v8

A generator writes OSWorld-compatible desktop tasks: a scenario in plain
English, a program that builds the starting files, and a way to decide whether
the agent finished. The output is the JSON OSWorld's runner already consumes,
and the tasks run against a real Ubuntu VM under Docker.

**203 tasks over nine applications:**

| vs_code | calc | os | chrome | impress | writer | thunderbird | vlc | gimp |
|---|---|---|---|---|---|---|---|---|
| 44 | 34 | 32 | 30 | 16 | 16 | 13 | 10 | 8 |

**Three grading routes**, chosen per task rather than one imposed on all:

- **probe** (172 of 206) — a program that reads the finished state and prints
  PASS or FAIL. Used when "done" cannot be said in a rule: several files that
  must agree, a value computed from the data, a directory laid out a particular
  way.
- **table** (24) — OSWorld's own spreadsheet comparison.
- **browser** (10) — OSWorld's URL matcher.

Preferring the built-in metric where it fits means less generated code, and
grading maintained by the benchmark rather than by us.

**Tasks are self-contained.** The setup runs inside the VM as a shell command,
so the JSON carries everything it needs as text and can be handed to anyone with
an OSWorld checkout. Earlier versions pointed at a build tree on one host
machine and were not portable.

**Controls run before any rollout** (`ostg/control.py`). For each task: boot a
fresh VM, run the setup by hand and check its exit code, then call
`env.evaluate()` on the untouched desktop. An idle agent must score 0.

| set | checked | failed | setup exit ≠ 0 | scored without work |
|---|---|---|---|---|
| v8big-all | 206 | 3 | 3 | 0 |
| v8nt-opus46 | 23 | 0 | 0 | 0 |
| v8nt-opus5 | 20 | 2 | 2 | 0 |

Nothing scored above zero on an untouched desktop. Every failure was a setup
command exiting non-zero — which matters because **OSWorld never checks this**:
`_execute_setup` reads the return code only inside an `until` clause, so a task
whose setup silently failed would run to completion against a desktop that was
never prepared, and score 0 for reasons indistinguishable from a weak agent.

**The main rollout is in flight; two pilots were stopped for it.**

| run | status | max steps | thinking | solved |
|---|---|---|---|---|
| v8big-all, think-preserve | 28 / 203 scored (06:30) | 100 | on, history preserved | 10 (37%) |
| v9 corpus (§9) — the tasks the NEXT trajectory rollout will run | complete: 213 specs, under instruction review | — | — | — |
| v8nt-opus46 | stopped at 8 / 23 | 50 | off | 4 |
| v8nt-opus5 | stopped at 9 / 20 | 50 | off | 3 |

The two pilots varied the model that *generated* the tasks — Opus 4.6 against
Opus 5 — holding the solving agent fixed. They were superseded by a full-corpus
replication (§8) and stopped to free the VMs; their partial numbers stand but
carry the grader-strictness confound described in §5.

---

## 2. How a task is specified

Generation does not ask for "a task". It draws a **coordinate** and asks for a
task at that coordinate, so a run walks a product space instead of returning to
whatever the model finds most natural.

**Intent** — what kind of work it is. Five values:

| intent | the agent must |
|---|---|
| `info_seeking` | find something in the environment and report it |
| `transform` | convert or restructure existing content |
| `configure` | put an application into a described state |
| `create` | produce an artifact that did not exist |
| `repair` | fix something already wrong |

**Domain** — the professional setting the scenario is dressed in: finance,
healthcare, education, logistics, human resources, legal, marketing, scientific
research, retail, real estate, travel, manufacturing. This axis exists for
surface variety; it should not affect difficulty, and measurement says it does
not.

**Difficulty** — 1 to 5, defined by *structure*, not by adjectives:

| level | definition |
|---|---|
| 1 | one application, one requirement |
| 2 | one application, two or three requirements that must all hold |
| 3 | one application and four or more requirements including an ordering or tie-breaking rule; or two applications with one to three |
| 4 | two applications and four or more requirements including an ordering rule; or three applications with one to three |
| 5 | three or more applications, four or more requirements, including an ordering or tie-breaking rule |

Levels 4 and 5 exist to find where the model breaks, so a quota keeps them a
minority: 15 / 25 / 25 / 20 / 15 percent.

This definition is itself an experiment result. v3 used a bare requirement count
as its difficulty axis and the rollout showed that count does not predict
success (section 5). Application count was folded in because that is what
actually separates easy from hard.

**Artifact host** — where the answer must end up: spreadsheet, text document,
slide deck, source code, raster image, PDF or archive, filesystem, preference
store, browser tab, terminal output, app data store, desktop session. Each
intent may only end in artifacts that make sense for it, and the host determines
which grading route applies.

**A fourth axis, ambiguity, is defined but not yet crossed in.** The probe
decides alone, so today every instruction must name one unambiguous end state.
Using it means changing the prompt and the grader together.

Generation is sharded: N processes take disjoint slices of the coordinate
product and run at once. The partition is permuted before striding — a raw
stride aligns with the innermost axis and would hand one process a single
difficulty level — and the permutation seed is a constant, so every process
derives the same partition.

---

## 3. How duplication is measured

Generated tasks must not restate what a benchmark already contains, and must not
restate each other. Three detectors, chosen because each is blind to something
the others catch.

**1. Jaccard over instruction tokens.** Set overlap of the vocabulary. Catches
tasks that reuse the same words. Cheap, and insensitive to how common those
words are — "the file" counts as much as "amortisation".

**2. TF-IDF cosine over instructions.** Weights each token by how rare it is
across the corpus, so sharing a distinctive word counts for more than sharing a
common one. This is the primary text detector and the one used against external
corpora. It ranks pairs differently from Jaccard, which is the point: one pair
that scored 0.37 by Jaccard scores 0.52 here.

**3. Grader signature — what the probe reads.** A fingerprint of the paths,
keys and fields a task's grading code touches. This catches re-dressed
duplicates: two tasks whose nouns all changed but which check the same thing in
the same place.

The third is used **only within a generated set, never against external
corpora**, and as a grouping aid rather than a gate. Two reasons, both measured.
OSWorld's tasks have no probes to sign. And signatures were tested for
cross-corpus transfer and failed: the measurement returned 0.097 with the true
match ranked 1254th, because signature vocabulary is a property of who wrote the
grader, not of what the task is about.

Thresholds: Jaccard pairs at or above 0.4 and TF-IDF pairs at or above 0.5 are
flagged inside a set; against an external corpus, 0.5 is the review line.
Signature pairs are grouped at a measured knee of 0.30. Flagged pairs are
reviewed by hand, with the earlier-generated task kept.

### What v8's 211 tasks score

Every detector passes, with no pair reaching its threshold:

| detector | max | p90 | over threshold |
|---|---|---|---|
| within-set jaccard | 0.38 | 0.10 | 0 at ≥ 0.4 |
| within-set TF-IDF | 0.45 | 0.09 | 0 at ≥ 0.5 |
| vs CUA-Gym (10,909 refs) | 0.41 | 0.25 | 0 at ≥ 0.5 |
| vs OSWorld (369 refs) | 0.28 | 0.17 | 0 at ≥ 0.5 |

**CUA-Gym constrains this work; OSWorld does not.** Its p90 is 0.25 against
OSWorld's 0.17, and it has thirty times the tasks over nearly the same
applications. The earlier v3 measurement said the same thing at a smaller scale
(0.13 median against 0.07).

The closest within-set pair shows why two text detectors are worth running:

    iab-tcf-v2-2-spec-page ~ iab-tcf-v2-2-policy-spec-page
    TF-IDF 0.45, jaccard 0.23

They share one rare term. Jaccard barely registers it against everything else in
the two instructions; TF-IDF weights it heavily and surfaces the pair — and it
is a real cluster, with a third member scoring 0.40 against both.

The signature detector flagged 416 pairs at or above 0.30, which is why it is a
grouping aid and not a gate. Its top pairs — `clinic-vitals-days-since-visit`
against `till-returns-reconcile-fix` at 0.67 — are unrelated scenarios whose
probes happen to read a table and compute a difference. That is the detector
behaving as designed: it describes the grading code, not the task.

### Similarity does not predict solvability

Across the 74-task v3 rollout, external similarity was 0.131 among solved tasks
and 0.138 among failures. Pushing tasks away from existing benchmarks costs
nothing in yield.

---

## 4. What each round established

**v2** (29 tasks) — first end-to-end generation. Established that the four-field
contract works at all.

**v3** (185 tasks, 74 rolled out) — the round that produced most of the evidence
in section 5. Also the round whose build-time controls caught **21 tasks whose
grader disagreed with its own reference solution**, fifteen of them from one
cause: the probe reached for a path directly instead of through the helper that
resolves it. That check costs a second on the host against 15–25 minutes of VM
time to find the same defect from a rollout.

**v4** (200 tasks) — a larger draw on the v3 design; generated, never compiled,
superseded.

**v5** (20 tasks, control) — introduced the structural difficulty definition now
in section 2, and moved the prompt out of Python into a file so it could be
diffed.

**v6** (15 tasks, control) — the self-contained-JSON contract: setup moves into
the VM, `solve_py` disappears. Measured against v5 at the same coordinates,
grading code per task fell from 2,260 characters to 820. Instructions fell from
704 to 321, but that belongs to a 300-character budget written into v6's prompt
and not v5's — two variables moved at once and the honest attribution is to the
rule, not the contract.

**v7** — built-in metric dispatch: emit `func`/`result`/`rules` when an OSWorld
metric fits, a probe otherwise. Wired through prompt, schema and emitter; never
generated a batch. v8 carries the idea into production.

**v8** — section 1.

---

## 5. What the 74-task rollout showed

Qwen3.6-27B BF16 on one H200, screenshot observation, pyautogui, 100-step cap,
1920×1080, temperature 0.6. **26 of 74 solved (35%).**

### Application dominates everything else

| application | solved |
|---|---|
| os | 4 / 5 — 80% |
| chrome | 14 / 27 — 52% |
| libreoffice_calc | 4 / 31 — 13% |

A six-fold spread. The same agent scores 78% on official OSWorld Chrome tasks
and 32% on official Calc tasks — ours are about 20 points harder in both, but
the ordering matches, so the gap is task shape rather than one application being
written badly.

### Instruction length predicts success, monotonically

| instruction length | solved |
|---|---|
| under 350 characters | 8 / 16 — 50% |
| 350–600 | 13 / 38 — 34% |
| over 600 | 3 / 17 — 18% |

The mechanism is visible in the trajectories. Long instructions are long because
they inline data — one listed ten clinics with two figures each, twenty numbers
the agent had to type by hand. It succeeded, in 100 steps, repeating the same
action 33 times. The fastest success took 7 steps.

This drove a generator rule: instructions are budgeted at roughly 300
characters, and more than six values must go in a file the agent opens.
Measured effect on generation — inline numbers per instruction fell from a p90
of 13 to 1.

### Requirement count does not predict difficulty

1 → 58%, 2 → 29%, 3 → 32%, 4 → 27%. Not monotonic, and the easiest bucket is
mostly Chrome configuration tasks, so what looks like difficulty is the
application effect in disguise. This is why difficulty was redefined structurally.

### Intent points the same way

`configure` 70% · `create` 38% · `transform` 30% · `info_seeking` 24% ·
`repair` 23%. Configuration tasks end in a settings value and have short action
paths.

### The graders that passed their controls hold up

A Chrome settings probe checks both `Preferences` and `Secure Preferences`,
globs across profile directories, and normalises paths before comparing. A
three-requirement task falls back to a second key name for the password setting,
because Chrome renamed it between versions. These are not naive string
comparisons.

---

## 6. What running it costs

Measured over 74 tasks and 3,566 steps.

| | tasks | median steps | median duration | total |
|---|---|---|---|---|
| solved | 24 | 23 | 4.7 min | 2.6 h |
| failed | 45 | 64 | 16.1 min | 11.8 h |

**82% of machine time goes to tasks that produce no training data.** The 16
tasks that hit the 100-step cap consumed half the total time and yielded one
success between them.

Per-step latency is 14.6 s. The input side dominates: up to 20 screenshots per
request at roughly 1,500–2,500 tokens each, against a measured p90 output of 143
tokens — about 300:1.

Concurrency scales poorly. Going from 2 to 3 simultaneous tasks raised per-step
latency 35% (11.4 s → 15.4 s) and throughput only 11% (10.5 → 11.7 steps/min);
linear scaling would have given 15.8. The model server is the bottleneck, not
the VMs.

Two fixed costs per task come from OSWorld itself: a 60-second wait after setup
before the first observation, added upstream because `reset()` returned a
screenshot of a half-drawn desktop, and 20 seconds before evaluation so the last
action's writes land.

---

## 7. Thinking mode was inert until v8

Every run before v8, **including the official 361-task campaign**, ran without
thinking despite passing `--enable_thinking`. The agent honours that flag only
when the base URL contains "dashscope"; against a local vLLM server it is
silently discarded. Confirmed empirically: zero thinking traces in 7,906 sampled
steps of the official campaign and 3,754 steps of the v3 run.

v8 fixed it, in two independent places. `mm_agents/qwen/main.py` now sends
`chat_template_kwargs` — the form vLLM reads — including `preserve_thinking`,
which keeps reasoning from earlier turns instead of stripping all but the last.
And `client.py` had a second, separate break on the read path: vLLM 0.25
renamed the response field `reasoning_content` to `reasoning`, so even when the
server extracted reasoning, the client read the old name, got None, and
silently discarded it — thinking was generated, paid for, and thrown away in
every prior run. The client now reads both names. Verified: 233 of 233 steps
in the running rollout carry a `<think>` block. Those two files are a new local
modification of the OSWorld checkout and are not yet in its documented list of
local changes.

Related: `max_tokens` was 81920 in every run. That is not a model limit — the
model imposes none and its context is 262,144. Measured p90 output is 143 tokens
and the longest response ever produced was about 2,294. OSWorld's own defaults
are 1500 and 32768.

---

## 8. Why the tasks come from Opus 5 rather than Opus 4.6

Two rounds of evidence, one small and one at scale. The small round (20 vs 23
tasks, §4–5) produced the initial verdict. The 2026-08-09 replication then
regenerated the **entire corpus** with Opus 4.6 under the same seeds — the same
coordinate walk through the cell product, batch for batch, so the generating
model is the only variable. 207 specs came back (Opus 5: 206), at half the
wall-clock (~1.3 h vs ~2.6 h) and half the price.

| | Opus 5 | Opus 4.6 |
|---|---|---|
| hard duplicate pairs (jaccard ≥ .4 / cosine ≥ .5) | 1 + 1 | 3 + 2 (max j = .62) |
| grader-signature pairs ≥ .30 (review band) | 416 | 363 |
| probe size at d5 (avg lines / comparisons) | 39 / 8.8 | 71 / 12.1 |
| worst benchmark proximity (cua-gym / OSWorld-361) | .41 / .28 | .43 / .27 |
| entity reuse ≥ 3 tasks / distinct-bigram ratio | 14 / .79 | 26 / .75 |
| setups written as `python3 -c` | 76% | 61% |

The deciding argument is not any single row; it is the **shape of each model's
characteristic defect**:

- Opus 5's defect is *mechanical*: escaping slips inside setup strings (2 of 20
  in the pilot). A static compile gate now catches the whole class; zero have
  shipped since.
- Opus 4.6's defect is *semantic*: re-dressed duplicates (3 hard pairs at
  scale, the same habit first flagged at n = 43) and, in the pilot, one task
  close enough to a public benchmark to be excluded (0.53 against cua-gym).
  No mechanical gate catches either kind; every instance costs a human or a
  second model to adjudicate.

A defect class that can be gated is strictly cheaper than one that must be
adjudicated. That asymmetry — not the row-by-row scores — is the choice.

Two findings cut against the choice and are recorded rather than hidden. At
scale, Opus 4.6's probes are *longer* and carry *more* comparisons; the pilot's
impression that Opus 5 probes deeper does not survive n = 200 — though length
is not correctness, and the one paired-rollout anecdote (§5's PDF-export pair)
had 4.6 checking file existence where Opus 5 verified file content. And 4.6
generates at half the cost. A bidirectional blind audit — each model reviewing
the other's corpus for instruction–grader divergence — is in flight as of this
writing; if it favours 4.6, this decision should be revisited.

One further result changes what the choice even means: aligned cell for cell,
the two corpora barely overlap (same-cell instruction jaccard median .14, n=45
aligned pairs; cross-corpus nearest-neighbour cosine median .16). The
coordinate dictates intent, app and difficulty; the model supplies the task's
identity. The corpora are **complements, not substitutes** — a merged ~400-task
pool exists if ever wanted, at the price of running the 4.6 half through the
same VM controls.

**The bidirectional audit landed 2026-08-09 and closed the revisit clause.**
Each model blind-reviewed the other's corpus for instruction–grader coverage
(one call per task; the 4.6-as-judge side was calibrated first — it
independently re-found all three defects we had confirmed by hand, including
the example.com gold error). Verdict rates:

| | Opus 5 tasks (4.6 judging) | Opus 4.6 tasks (Opus 5 judging) |
|---|---|---|
| covered | 35% | 15% |
| partial (grader under-checks) | 37% | **82%** |
| overreach (grader over-demands) | 28% | 3% |
| missing items per task | 0.8 | **4.3** |

The judges differ, so judge severity is confounded with corpus quality and the
absolute gap should be discounted. Two things survive the confound. First, the
failure *styles* are opposite: Opus 5's graders err toward overreach (false
FAILs — wasted trajectories), 4.6's toward partial (false PASSes — poisoned
labels), and for SFT harvesting a false PASS is strictly worse than a false
FAIL. Second, the per-grade split: 4.6 went 10/10 partial on browser tasks and
21/23 on table tasks — it keeps writing promises into instructions that the
fixed grader templates cannot check. Both agree with the pilot's PDF-export
anecdote. The decision stands.

**A common judge removed the confound.** Sonnet 4.6 then audited both corpora
under the identical rubric — four audits in total:

| judge → corpus | covered | partial | overreach | missing/task |
|---|---|---|---|---|
| Opus 4.6 → Opus 5 set | 35% | 36% | 27% | 0.8 |
| Opus 5 → 4.6 set | 14% | 81% | 3% | 4.3 |
| Sonnet 4.6 → Opus 5 set | 26% | 70% | 2% | **2.0** |
| Sonnet 4.6 → 4.6 set | 17% | 80% | 1% | **3.1** |

Same judge, same severity: the Opus 5 corpus carries ~35% fewer coverage gaps
(2.0 vs 3.1 missing items per task; covered 26% vs 17%). The direction of the
cross-audit holds; its size does not — the true gap is ~1.5x, not the ~5x the
asymmetric table implied, because Opus 4.6 judges softly (0.8/task on the same
corpus where Sonnet finds 2.0) and Opus 5 judges harshly (4.3 where Sonnet
finds 3.1). Decision unchanged; future audits should use a fixed third-party
judge so rates stay comparable across corpora.

Operationally, Sonnet's stricter pass is the quarantine input for SFT
harvesting: on the v8 corpus it flags 145 tasks partial — 120 of the
under-verifying kind, where a lazy agent could pass — and 11 with fragile
world assumptions. These cross with rollout scores when trajectories are
harvested: passed-but-quarantined gets extra review; failed-on-overreach
becomes the false-FAIL rescue list.

---

## 9. The v9 corpus — ambiguity and voice, activated

Why: measured against the official OSWorld instructions, v8's are twice as
long (median 53 vs 26 words), carry an absolute path 87% of the time (official:
5%), open with a bare imperative 1% of the time (official: 18%), and speak in
one register — a first-person workplace persona. Fine for grading, narrow for
SFT: a model trained only on over-explicit requests never practices resolving
"fix my rota thing". The instruction's explicitness and the grader's precision
are decoupled — a probe can pin an exact path while the instruction says "the
rota spreadsheet on my desktop" — so vagueness costs no grading rigor.

Design, generating as of this writing:

- **Ambiguity joins the coordinate product** (intent × domain × difficulty ×
  ambiguity, 325 → 1300 cells), four levels with a 10/30/30/30 quota: explicit
  / functional reference / deictic (target pre-opened, "this sheet") /
  outcome-only ("get the numbers right before I resend it").
- **Voice** is derived per cell at 30/25/45: terse / polite / persona.
- **Mechanical gates**: an ambiguity≥2 instruction containing /home/user or a
  filename is rejected; deictic without open_path is rejected.
- **Two prompt rules from the audit findings**: every countable promise is
  checked in full or not made (the partial-verdict feedback), and browser
  targets must have URLs that encode the work (query parameters a form fill
  produces), closing the navigation-only difficulty collapse.
- Same machinery, same seeds; the walk itself is not comparable to v8's (the
  space quadrupled), so cross-version pairing is reference-only.

The corpus completed at **213 specs**. Measured against v8 and the official
instructions:

| | official | v8 | v9 |
|---|---|---|---|
| median words | 26 | 52 | 56 |
| opens Please/Could | 28% | 1% | **26%** |
| first-person persona | 16% | 37% | 21% |
| contains absolute path | 5% | 87% | **12%** |

Ambiguity landed 14/31/26/29 against the 10/30/30/30 quota; every polite task
opens with Please/Could; persona fell from a monoculture to a plurality. The
one partial miss: terse tasks carry the register's tone but not its brevity
(median 47 words vs persona's 63) — the "one or two sentences" instruction is
half-obeyed, and a hard length cap is a one-line rule for the next iteration.

Three generator defects were caught and fixed during the run, all downstream
of the tool schema not being server-enforced: a module-resolution mislaunch
(Python prefers the working directory's package over PYTHONPATH — run from
the versioned worktree), a spec arriving as a string, and whole spec arrays
arriving as JSON strings — one shard silently discarded 17,000 string
fragments before extract learned to parse both shapes back.

The instruction review is in front of the operator now; VM controls and the
v8-protocol rollout follow approval.

## 10. Open

- **The main rollout is mid-flight** (13 of 203 at this writing); claims about
  thinking's effect on the solve rate, and the preserve/no-preserve A/B, wait
  on it. The v3 run remains paused at 74 of 185.
- **The v5/v6/v7 branches were never merged** and now sit beside a version that
  supersedes them. They should be closed out.
- **`sig.py` should be deleted** — 380 lines, measured not to transfer across
  corpora, a conclusion v8's `accept.py` reached independently and designed
  around. The negative result belongs in prose; the code does not.
- **The 82% spent on failures is unaddressed.** The safe reductions —
  `max_tokens` near the measured p90 rather than 81920, and a stability poll in
  place of the fixed 60-second settle — are identified and not implemented.
- **Voice compliance is unmeasured**: v9 assigns a register per task, but
  whether "terse" actually comes out terse (early sign: tone yes, length no)
  waits on the full-corpus comparison.
- **Browser difficulty labels in v8 overstate**: the grader checks only the
  final URL, so a d5 navigation task is effectively d1. v9's rule 13 addresses
  new tasks; v8's ten browser tasks should be read grade-first.

---

## 11. A note on confidence

Three conclusions here were stated before the evidence supported them and later
contradicted: a loop-count threshold at n=12, a claim that one prompt style never
succeeded at n=15, and a claim that streaming eliminated a gateway timeout after
two clean batches — it reduced them; seven appeared by the fourth. Each was
labelled a small sample at the time and each was still stated too firmly. Sample
sizes are given throughout so the reader can apply their own discount.
