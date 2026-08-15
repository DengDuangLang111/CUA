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
