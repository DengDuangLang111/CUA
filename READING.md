# CUA reading list & innovation candidates (2026-08-15)

Curated for the innovation-point search. ✅ = verified this session (paper/code
actually read); 🔎 = from memory, verify before citing.

## A. Task generation (our home turf)
- ✅ **Qwen-CUA** (2608.02352) — 40K verifiable tasks, iterative teacher-regen;
  generation pipeline CLOSED. Our evaluator-compilation is the gap they left.
- 🔎 **OS-Genesis** — reverse synthesis (explore → derive tasks); the dual of
  our forward-generate + layered-verify.
- ✅ **ANCHOR** (2602.07153) — branch-point task generation from human trajs.
- 🔎 **AgentTrek / Synatra / NNetNav** — tutorials / text / exploration as
  task sources.

## B. Training recipes & consistency (today's vein)
- ✅ **OpenWebRL** (2606.02031) — the −14.6…−23.7 history-reasoning ablation is
  buried here; they patch reasoning back with a regex and never study it.
- 🔎 **How to Train Your LLM Web Agent: A Statistical Diagnosis** (2507.04103)
  — experimental power for agent evals; we lived the 9-task-panel lesson.
- ✅ **OpenCUA** (2508.09123) — AgentNet 22.5K human tasks; their CoT is
  model-backfilled, ours is teacher-native.

## C. Data quality & scale
- ✅ **MolmoWeb** (2604.08516) — 2.2M steps + 10.5M perception, pure SFT;
  "human data limited gains".
- ✅ **ProCUA-SFT** (2606.17321) — 93K synthetic trajs → 3.1M samples; the
  scaled-up version of our shape.
- ✅ **CUA-Suite / GroundCUA** (2603.24440) — 3.6M desktop element annotations.

## D. RL follow-on
- 🔎 **WebRL**, **DigiRL** — online RL recipes; Qwen-CUA's 1–7/8-success task
  retention rule pairs naturally with our difficulty-graded generation.

## E. Benchmarks
- ✅ **OSWorld** (2404.07972) §4 + appendix; AndroidWorld/WebArena as design
  references.

## Innovation candidates (ranked by current evidence)
1. **What should a small student see** — systematic context-config study for
   CUA distillation (history reasoning rich/lean × image budget). The
   rich/lean arms + keepthink template + frozen eval-50 already form the
   skeleton; nobody has published this axis.
2. **Open verifiable-task generation with compiled evaluators + difficulty
   curriculum** — our core asset; Qwen-CUA proved the fuel matters and kept it
   closed; OS-Genesis judges with LLMs. Teacher-pass-rate as difficulty scale.
3. **Step-level conditional-correctness metrics for demonstration quality**
   (state revisitation 0.02-pass vs 0.56-fail, screen-change rate, tail runs)
   — judge-free trajectory quality, cross-model validation data in hand.

1+2 compose: the pipeline produces the corpus; the context study consumes it;
together they are "how to distill desktop competence into a small model".

## Positioning: our generation vs the two paradigms (2026-08-15)

| axis | evaluator-first (Qwen-CUA, AndroidWorld) | task-first (OS-Genesis) | ours (co-gen + admission + validation) |
|---|---|---|---|
| verifiability | by construction | derived, often degrades to LLM judge | constrained AND empirically tested (positive control must score 1.0) |
| naturalness | low (checkability warps tasks) | high | mid-high (user-voice instruction, program-decidable gate) |
| grader | handwritten / closed | LLM judge (~90% at best) | compiled deterministic probe |
| idle-agent zero | usually | often missing | rule-enforced (probe FAILs on setup state) |
| path independence | yes | unguaranteed | rule-enforced (machine state only) |
| difficulty scale | no | no | teacher pass-rate gradient, RL-curriculum-ready |
| openness | closed / small | open + judge-bound | ours, openable |

Update 2026-08-15 (corrected same day — the user caught a confound):
difficulty and app_count are perfectly confounded by design (1–2=1app,
3–4=2app, 5=3app). Validated: the app-count ladder's monotone-cliff effect and
the direction of within-tier grading; within-tier independent validity awaits
the 444-task sample (EXPERIMENTS.md, category analysis). The negative-control gap made precise:
positive control (gold→PASS) and trivial negative (initial-state→FAIL) are
systematic; **near-miss negatives (mutated gold end-states that must all
FAIL) are not** — they test probe specificity, and the two known
wrong-answer-scored-1 leaks are exactly what they would catch. Design: k
generic mutators (drop row, reorder, right-content-wrong-name, partial) + an
LLM-crafted trap per task, specificity column in the control report.

Honest weaknesses to preempt: (1) **same-head co-generation has correlated
blind spots** — a misunderstanding of app behaviour infects task and probe
coherently; positive control catches evaluator-broken cases (did: 6 right-
answer-scored-0 + 2 wrong-answer-scored-1) but **negative control is not yet
systematic** — the pipeline's most paper-critical gap. (2) Free-form probes
mean every grader is fresh code; the control layer is load-bearing.

One-line positioning: co-generate the triple, admit only the program-decidable,
then prove the grader itself correct by experiment — scalable verified
programmatic grading, which neither existing lane offers, with teacher
pass-rate as a free difficulty scale.

## How to compare our data against others (2026-08-15)

Datasets are not comparable as artifacts (environments, grading semantics,
granularity, scale all differ). Three comparisons that ARE sound:

1. **Functional (gold standard): fixed student + budget + recipe + benchmark,
   swap only the data source.** Qwen3.5-4B, e3 recipe, ~1.2k-sample budget,
   verified-eval-50; rows = ours / AgentNet-Ubuntu / ProCUA subset, each
   through the dialect converter and the same pipeline filters. Measures
   value-per-sample. Precedented (MolmoWeb human-vs-synthetic, OpenWebRL
   0.4K-vs-1.9K). Declared confound: conversion quality — mitigate by passing
   our own data through the same converter. This is arm C generalised.
2. **Intrinsic: transferable rulers applied to everyone.** Our judge-free
   trajectory metrics (repeat, revisitation, tail runs, screen-change) run
   unchanged on their trajectories; plus instruction-embedding dispersion and
   app coverage. Fair because the ruler belongs to no dataset.
3. **Categorical: axes with no competitor.** Grader form (compiled probe vs
   judge vs human), grader-validated (positive/negative control) — unique,
   teacher-pass-rate difficulty scale — unique, contamination-by-construction
   status. The narrative axis is "the corpus knows its own reliability", not
   volume.

Paper shape: main = the transplant table (3 rows suffice); support = the
metric table (doubles as innovation #3); positioning = the categorical table.
None of the three requires datasets to be commensurable — only the rulers.

## Why OpenWebRL's 0.4K "worked" — the decomposition (2026-08-15)

The 0.4K did not produce the 67%; it is the ignition, RL on 2.2K verifiable
tasks is the engine. Evidence: their own framing (warm start for exploration),
the 1.9K-SFT-worse-after-RL result (if SFT were the engine, more would help;
it reduced plasticity instead), and our own SFT-only arms not beating base at
similar scale. Warm start has exactly three small-data jobs: format
compliance, lifting RL-task success into the learnable band (the 1–7/8
window Qwen-CUA formalises), and not ossifying the base — the third argues
for LESS data. Amplifiers: 7.5-step tasks, a base VLM that already grounds,
curation maximising format-signal per sample.

Corollaries for us: (1) calibrate arm A/B expectations — beating base with
healthier behaviour is already the recipe's ceiling for pure SFT; (2) the
scarce asset in their pipeline was the 2.2K verifiable RL task pool, and our
generator IS the desktop version of that machine, difficulty scale included;
(3) the v11 corpus's endgame may be warm-start + RL pool rather than
pure-SFT product — to be decided by the A/B numbers.
