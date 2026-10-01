# Action Reward Model on desktop CUA: inference-time selection vs. LoRA distillation (2026-10-01)

**Actor:** a2 = Qwen3.5-9B full SFT on r5 (`img10-9b/checkpoint-306`, served as `9b-full-r5--train20260822--s306`).
**Judge:** GPT-6.1-sol, `reasoning_effort=high`.
**Benchmark:** OSWorld-Verified non-proxy panels `verified_eval50_nonproxy` / `verified_eval100_nonproxy`, compared task by task with the a2 baseline run `eval50-a2-20260823` (which actually covers all 100 eval100 tasks).

## TL;DR

| Arm | What changes vs. a2 | Panel | Pass | a2 pass | Δ |
|---|---|---|---|---|---|
| **B: selection ARM at inference** | every step: sample K=5 actions, GPT-6.1-sol picks one | eval50 | **39/50 (78.0%)** | 34/50 (68.0%) | **+5 (+10 pp)** |
| **only-changed LoRA** | LoRA on the 1,191 r5 states where the judge's pick ≠ a2's most common action | eval100 | 57/100 (57.0%) | 61/100 (61.0%) | **−4** |
| **full LoRA (step-600 snapshot)** | LoRA on all 6,253 kept r5 states (upstream "option A" recipe) | eval100 | 56/100 (56.0%) | 61/100 (61.0%) | **−5** |

- **Inference-time selection helps**, mostly on feasible GUI tasks (+4 of the +5).
- **Both distilled actors are worse than a2 on feasible tasks (−8 each, 49/87 vs 57/87).** They gain only on infeasible tasks (+4 / +3), by ending with `terminate(failure)` instead of a2's habitual `terminate(success)`.
- The full arm keeps a2's own most common action as the target in 81% of states, yet loses as much as only-changed. That points at **"LoRA on a2's own temperature-1.0 samples"** as the source of the damage, not at the judge's selections. A random-candidate control arm, as in upstream `distill_rand`, is needed to confirm this.
- None of the differences is statistically significant on its own: sign-test p = 0.12 / 0.52 / 0.38. The direction of the two LoRA arms on feasible tasks is consistent, though.

Scoring convention: as in `sft/docs/RESULTS.md` §5.30, a task passes only when its score == 1. "Feasible" means the 87 eval100 tasks whose evaluator is not `infeasible`.

---

## 1. Setup

### 1.1 Common to every arm (identical to the a2 baseline run)

- **Runner:** OSWorld native `run_multienv_qwen.py` from the `OSWorld-armsel` worktree, commit `a8b2448`, which is `b7dce12` plus one hook.
  - Runner args are taken item by item from the baseline's `args.json`: 20/10 image window (`image_max 20`, `fold_size 10`), temperature 1.0, top_p 0.95, max_tokens 81920, `history_n 100`, `max_steps 50`, `sleep_after_execution 3`, thinking + preserve_thinking, relative coordinates, docker 1920×1080.
  - Harness env: `OSTG_NO_RECORD=1`, `OSTG_TYPE_NO_SPLIT=1`.
  - Against the baseline `args.json`, only model name, `base_url` and paths differ.
- **Serving:** vLLM with the baseline's non-default args: `max_model_len 262144`, fp8 KV cache, `reasoning-parser qwen3`, image limit 20, and `--override-generation-config` = temperature 1.0, top_p 0.95, top_k 20, min_p 0, presence_penalty 0, repetition_penalty 1.0, max_new_tokens 81920.
  - Replicas ran on Klone A40 / A100 / L40S behind a least-busy proxy (`cua-arm/cua/rr_proxy.py`) that only forwards requests.
- **Task files:** the eval100 panel and all 100 task JSONs were checked by md5 on both eval machines against the baseline tree.
- **The hook** (`mm_agents/qwen/main.py`, `OSTG_ARM_SELECT`):
  - `0` = the original single `call_llm`, i.e. byte-identical behaviour to the baseline. Both LoRA arms use this.
  - `N ≥ 2` = N parallel samples, then the selection ARM picks the executed response.

### 1.2 B arm: selection ARM at inference (David An's setup, adapted to desktop)

- Every step samples K=5 responses from a2 with the eval sampling params.
- `cua/select_candidates.select_live` calls the upstream `selection_prompt.catts_vision_select_v2`:
  - all 5 candidates are shown together, in a per-state deterministic shuffle;
  - the judge returns `{"selection": N}`;
  - the chosen response is executed and kept in history.
- CUA-minimal prompt edits, registered in `cua-arm/PROVENANCE.md`:
  - "web automation" → "desktop automation";
  - the URL block is dropped;
  - "visible element on the current page" → "visible UI element on the current screen";
  - a coordinate-convention line is added.
- One upstream patch (`ea609ed`): `gpt-6*` is treated as a reasoning model (`max_completion_tokens` and `reasoning_effort`). Without it, upstream silently falls back to the first shown candidate.
- **864 selections over 50 tasks, 0 failed calls (`ok=false` 0), 0 fallbacks.**
  - In 30.8% of steps all 5 candidate actions were identical.
  - The executed action differed from a2's plurality action in **38.5% of all steps (55.7% of steps with any disagreement)**.

### 1.3 Training data: PRM scoring of a2's own candidates on r5 (upstream "option A")

| Stage | What was done |
|---|---|
| States | All 6,474 rows of the r5 SFT corpus (`r5-v16save143-tf/train_swift_abs.jsonl`, first 6,474 rows): one row = one state, with teacher-forced history. |
| Candidates | a2 samples n=5 per state with offline vLLM, exactly the eval sampling params (`cua/sample_candidates.py`). |
| Scoring | GPT-6.1-sol scores **each candidate separately** on a 0–1 scale, using the upstream single-candidate prompt + `prm2_templates.json` + the same CUA edits (`cua/score_candidates.py`). 32,370 calls, 0 failures. |
| Selection | Upstream `build_distill_selections.py`, `THRESH=0.7`: argmax score; ties → a2's plurality action; drop the state if the best score is < 0.7. **Kept 6,253 / 6,474 (96.6%).** |
| SFT rows | Upstream `build_onpolicy_sft.py` → `cua/to_swift.py`. Each row keeps the corpus row's messages and images byte-identical and replaces only the final assistant turn with the selected raw candidate (think + action). |

Score distribution:
- 80.6% of candidates scored ≥ 0.9;
- 85.3% of kept states have a best score of exactly 1.0. GPT-5.5 upstream: 35.8%; its p10 / median of best score were 0.80 / 0.95, ours are 0.94 / 1.00.

**The selected target differs from a2's plurality action in 19.0% of kept states (1,191).** That is half the rate of the live selection ARM (38.5%), because per-candidate scoring produces many ties that resolve to the plurality action.

The two arms' data:
- **full:** all 6,253 rows; sha256 `0f41c8e5…`.
- **only-changed:** upstream `--only-changed`, 1,191 rows; sha256 `9cef5cad…`. This is not the upstream-validated recipe; it was an extra variant.

Composition of the only-changed targets (a2 plurality → judge pick):

| Change type | Share |
|---|---|
| Same action type, different parameters (click coordinates / typed text / keys) | 51% |
| Observe (screenshot / wait / mouse_move) → act | ~16% |
| Act → `terminate(success)` | 5% |
| Other type swaps | ~28% |

`terminate(failure)` appears **0 times** in the r5 labels, in the full targets and in the only-changed targets.

### 1.4 LoRA recipe (upstream stage D, on ms-swift)

- Initialised from a2 (`global_step 306` asserted).
- LoRA r16 / alpha 32 / dropout 0.05 on all linear layers; ViT and aligner frozen.
- lr 1e-4, linear schedule, warmup 0.03, weight decay 0.
- Global batch 8 (2×H200 × bs1 × accum4), 1 epoch, `max_length 65536`, loss on the last round only, preserve_thinking.
- Merged to full weights with `swift export --merge_lora`, published to Klone, checked file by file with sha256.
- Non-weight files are identical to a2: chat template, tokenizer, processor configs, generation config. Tensor names are identical (760). The only `config.json` difference is a2's leftover `use_cache: false`.

Runs:

| Arm | Slurm job | Steps | Outcome |
|---|---|---|---|
| only-changed | 339130 | 149 | trained to the end (checkpoint-149) |
| full | 339127 | 635 of 782 | **died of CUDA OOM** (rank 1 asked for 26.6 GiB with 22 GiB free; most likely one of the longest r5 rows, ~36–39k text tokens + 10 images, still under `max_length`) |

The evaluated full model is **checkpoint-600**: 77% of the epoch, with lr already decayed to about ¼ of peak. It was merged by debug-QOS job 339232 and served as `9b-full-r5-armg61--train20261001--s600`.

---

## 2. Results

### 2.1 Overall (paired with the a2 baseline on the same tasks)

| Arm | Panel | n | Arm pass | a2 pass | Δ | Arm mean | a2 mean | arm-only / a2-only | sign test p | feasible (arm vs a2) | infeasible (arm vs a2) | mean steps on success (arm vs a2) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B: a2 + selection ARM (GPT-6.1-sol high, K=5) | eval50 | 50 | 39 (78.0%) | 34 (68.0%) | +5 | 79.8 | 69.8 | 6 / 1 | 0.12 | 36/45 vs 32/45 | 3/5 vs 2/5 | 12.4 vs 14.6 |
| only-changed LoRA | eval100 | 100 | 57 (57.0%) | 61 (61.0%) | −4 | 59.8 | 62.9 | 9 / 13 | 0.52 | 49/87 vs 57/87 | 8/13 vs 4/13 | 13.1 vs 15.6 |
| full LoRA (step-600 snapshot) | eval100 | 100 | 56 (56.0%) | 61 (61.0%) | −5 | 56.9 | 62.9 | 8 / 13 | 0.38 | 49/87 vs 57/87 | 7/13 vs 4/13 | 15.6 vs 15.6 |

The baseline numbers reproduce RESULTS exactly: a2 eval100 = 61.0% pass, 65.5% on the 87 feasible tasks, mean 62.9.

### 2.2 Per app (n: arm pass / a2 pass)

| App | B (eval50) | only-changed (eval100) | full s600 (eval100) |
|---|---|---|---|
| calc | 7: 4 / 5 | 15: 9 / 11 | 15: 8 / 11 |
| chrome | 3: 3 / 3 | 6: 5 / 4 | 6: 5 / 4 |
| gimp | 4: 4 / 2 | 8: 5 / 3 | 8: 5 / 3 |
| impress | 7: 5 / 3 | 15: 8 / 9 | 15: 8 / 9 |
| multi_apps | 12: 9 / 9 | 24: 11 / 15 | 24: 14 / 15 |
| os | 4: 3 / 3 | 8: 4 / 5 | 8: 4 / 5 |
| thunderbird | 3: 3 / 2 | 5: 4 / 4 | 5: 4 / 4 |
| vlc | 3: 3 / 2 | 5: 4 / 2 | 5: 2 / 2 |
| vs_code | 4: 2 / 2 | 7: 3 / 4 | 7: 3 / 4 |
| writer | 3: 3 / 3 | 7: 4 / 4 | 7: 3 / 4 |

### 2.3 Flipped tasks (`*` = infeasible task)

- **B:**
  - arm-only: gimp/2a729ded, gimp/62f7fd55\*, impress/05dd4c1d, impress/5d901039, thunderbird/7b1e1ff9, vlc/5ac2891a
  - a2-only: calc/04d9aeaf. All 5 candidates at the final step were `terminate(success)`, so the judge had no alternative.
- **only-changed:**
  - arm-only: calc/2bd59342\*, chrome/ae78f875\*, gimp/62f7fd55\*, gimp/e19bd559\*, impress/05dd4c1d, impress/9ec204e4, vlc/5ac2891a, vlc/d06f0d4d, writer/e246f6d8
  - a2-only: calc/4188d3a4, calc/4de54231, calc/abed40dc, impress/04578141, impress/a434992a, impress/bf4e9888, multi_apps/48d05431, multi_apps/7f35355e, multi_apps/b337d106, multi_apps/f918266a, os/3ce045a0, vs_code/ec71221e, writer/adf5e2c3
- **full s600:**
  - arm-only: chrome/480bcfea\*, chrome/ae78f875\*, gimp/2a729ded, gimp/e19bd559\*, impress/841b50aa, impress/9ec204e4, os/b3d4a89c\*, writer/e246f6d8
  - a2-only: calc/4de54231, calc/535364ea, calc/6e99a1ad, chrome/030eeff7, impress/a434992a, impress/a669ef01, impress/bf4e9888, multi_apps/81c425f5, os/3ce045a0, os/a462a795\*, vs_code/c6bf789c, writer/0b17a146, writer/adf5e2c3

Runs ending with `FAIL` (`terminate(failure)`): B 3/50, only-changed 10/100, full 10/100.

---

## 3. Analysis

**Where B's gain comes from.** Mostly single-app GUI tasks where a2 wanders or slips:
- finding a setting: thunderbird and vlc, where a2 hit the 50-step cap;
- multi-step precise edits: gimp background removal, impress alignment and stretching;
- one infeasible task.

On tasks that both B and a2 solve, B uses fewer steps (12.4 vs 14.6 on all successes). This is the same order of magnitude as upstream's inference-time best-of-5 (+7.2 pp) and David's Slack number (+8.2 pp).

**Where the LoRA arms' gain comes from: end-of-episode status, not competence.** On infeasible tasks the a2 baseline often wrote in its own reasoning that the task cannot be done, and then still called `terminate(status=success)`, which is scored 0. r5 contains no failure terminations, so a2 learned "end = success". Both LoRA arms end those episodes with `terminate(failure)` (10/100 runs each, vs. 3/50 for B).

This was never a training target (0 failure targets), so it is an indirect effect of the LoRA update. One possibility is that the update loosens a2's SFT-induced habit. This is a hypothesis and has not been verified.

**Where the LoRA arms lose: feasible office tasks, through over-confident completion.** All 13 a2-only tasks of only-changed are runs where the arm ended with `terminate(success)` and the checker disagreed. Reading the final reasoning suggests:
- unverified saves ("no Keep-format dialog appeared, so the file is saved");
- an off-by-one freeze range;
- hand-typed hex colours where named standard colours were required;
- re-installing Miniconda instead of activating the existing conda;
- stopping after "finding a tutorial" instead of applying it.

These are inferred from the trajectories, not yet checked against the evaluators.

For only-changed, this fits its target mix: observe → act (~16%) and act → terminate (5%) teach "stop verifying, finish earlier".

**Why distillation did not transfer B's gain (hypotheses, ranked by evidence).**

1. **Self-training on a2's own temp-1.0 samples hurts by itself.** The full arm changes a2's action in only 19% of states and still loses −8 on feasible tasks, the same as only-changed. Candidates that could matter:
   - LoRA at lr 1e-4 on top of an already full-SFT'd model;
   - noisier sampled reasoning text replacing the r5 teacher's;
   - re-fitting states a2 was trained on.

   *Test:* a random-candidate control arm (upstream `distill_rand`), with the same recipe and states but a random candidate as target. If it also drops by about 5, the selection signal is not the problem.
2. **A different judge from B's.** Per-candidate PRM scoring with plurality tie-breaking moves only 19% of targets, while B's comparative selection moves 38.5%. The training data does not encode B's behaviour.

   *Test:* relabel the same r5 candidates with the B-arm selector (`cua/select_candidates.py` offline mode, about 6.5k calls, ≈ $120).
3. **Distribution shift.** Training states are r5 generated tasks with teacher-forced history (up to 10 images). B selects on live OSWorld states with a2's own 20/10 history.
4. **Scale.** Upstream's +8.7 pp used about 39k states. Here: 6,253 (full) or 1,191 (only-changed).

The full arm being a step-600 snapshot (lr already ≈ ¼ of peak) is unlikely to flip the sign.

---

## 4. Caveats

- **Single runs at temperature 1.0.** Re-running a2 alone flips several tasks, and all p-values here are > 0.1.
- **B is on eval50 only** (the panel previously used for arm selection); the LoRA arms are on the full eval100.
- **Infrastructure crashes** (VM boot timeout / empty screenshot) are scored 0 by the harness and tagged with `harness_error.json`.
  - The a2 baseline and B had 0 such crashes.
  - The LoRA arms had 4 (only-changed) and 1 (full). All were re-run automatically with the same model and settings (`cua/rerun_crashed2.sh`); the crashed attempts are kept under `_crashed/` and not counted.
- **Load balancing moved queued tasks between eval machines.** Pre-registered rule: a moved task is scored from the group it was moved to; any duplicate run on the original machine is discarded, never cherry-picked. The `NOTE*` files in the result dirs record each move.
- **Full arm = step-600 snapshot**, not the end of the epoch (see §1.4).

## 5. Cost

GPT-6.1-sol at $2/M input, $0.10/M cached, $10/M output; cache hit rate about 4% (per-candidate calls).

| Item | Calls | Input tokens | Output tokens | Cost |
|---|---|---|---|---|
| PRM scoring of r5 | 32,370 | 131.8M | 2.88M | ≈ $283 |
| B-arm selections | 598–864 | ≈ 5.5–7.9M | ≈ 0.05M | ≈ $11–16 |
| Tests | ~300 | ~1M | — | ≈ $2 |

The B-arm row is estimated; token usage was not logged for live selections.
- Every step logs one selection record (864). 598 of those steps had candidates that disagreed. Whether the 266 steps with 5 identical candidates also reach the judge was not measured, hence the range.
- Calls are costed at the measured ≈ 9.1k input / 58 output tokens per selection call.

**Total ≈ $300.**

## 6. Next steps (proposed, not started)

1. **Random-candidate control** on the full recipe. This is the cheapest decisive test of hypothesis 1; about 7 h on 2×H200, no API cost.
2. **Selection-judge relabel** of r5 (B's exact selector), then the same LoRA recipe. This tests hypothesis 2; about $120.
3. If hypothesis 1 holds: lower the LoRA lr, put loss on the action only (not on sampled reasoning), or distill on live OSWorld-like states instead of r5.
4. Finishing the full arm past step 600 needs an OOM workaround: skip the offending batch, or use sequence parallelism. It is not recommended given the results.

## 7. Provenance

| What | Where |
|---|---|
| Code | `cua-arm` (local git; upstream `piotr-teterwak/action-reward-models` + `cua/` adaptations, edits listed in `PROVENANCE.md`); OSWorld hook `OSWorld-armsel@a8b2448` |
| Scoring run | Tillicum `/gpfs/scrubbed/jy050706/arm/runs/r5-prm-gpt61-20261001/` (`scored.all.jsonl`, `selections_arm.jsonl`, `swift_arm.jsonl`, `swift_arm_oc.jsonl`) |
| Checkpoints | Tillicum `sft/out/9b-full-r5-armg61oc/` (checkpoint-149 + `merged`), `sft/out/9b-full-r5-armg61/` (checkpoint-500/600 + `merged` from 600) |
| Serving copies | Klone `/gscratch/cse/jy050706/sft/serving/<served name>/model` |
| B-arm results | workstation `~/research/OSWorld-armsel/results_generated/armsel-eval50-gpt61sol-high-20261001/{ws1,ws2a,ws2b,ws2c,ws2d}`, Windows `/mnt/d/research/OSWorld-armsel/results_generated/armsel-eval50-gpt61sol-high-20261001/{win,win2}` |
| LoRA results | `results_generated/arm-oc-eval100-20261001/{wsA,wsB1,wsB2,wsB3,wsW,wsR,win}`, `results_generated/arm-full-eval100-20261001/{ws,win}` (same roots) |
| Baseline | Windows `/mnt/d/research/OSWorld/results_generated/qwen35-9b-sft/eval50-a2-20260823` |
| Running log | `sft/plans/PLAN-20260930-qwencua-arm.md` §0 |
