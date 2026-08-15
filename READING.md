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
