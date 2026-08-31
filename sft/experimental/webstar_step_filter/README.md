# WebSTAR-style step-filtered SFT: experiment protocol

**Protocol version:** `webstar-step-filter-v1.0-draft`

**Status:** `DESIGN REVIEW` — documentation only; no production code, source
dataset, shipped dataset, checkpoint, or sbatch has been changed.

**Git branch:** `exp/webstar-step-filter-v1`

**Base commit:** `5d1cfe25bcf2ac26f29f0a332eeda7b054ab562f`

## 1. The question this experiment answers

The current MixB corpus admits successful trajectories, expands each retained
trajectory into one target row per step-prefix, and trains the final assistant
turn of every retained row. The experiment asks one narrow question:

> Does preventing low-quality intermediate steps from contributing SFT loss
> improve closed-loop CUA performance, while keeping their actions and
> observations available in later prefixes as recovery context?

This is a step-quality experiment. It is **not** a learning-rate, optimizer,
batch-size, epoch, trajectory-length-normalization, prefix-cap, image-window,
thought-length, or teacher-mixture experiment.

The direct literature precedent is WebSTAR (ACL 2026): it retains complete
trajectory context but computes SFT loss only on high-scoring steps. WebSTAR
reported 39.6 average performance from 46K correct steps versus 29.9 from 97K
all steps inside successful trajectories. We reproduce only that selective
supervision principle. We do not claim to reproduce its data generator,
post-hoc thought augmentation, StepRM, or web-only benchmark.

Primary source:
<https://aclanthology.org/2026.acl-long.21/>

## 2. Frozen baseline

The source corpus is the exact current MixB data used by `mixB-4b.sbatch` and
`mixB-9b.sbatch`:

| Source family | Trajectories | Current target rows |
|---|---:|---:|
| v16 (`v16-main` + `v16-pilot`) | 554 | 13,372 |
| v11 new (`v11new-500` + `v11new-all`) | 312 | 5,204 |
| **MixB total** | **866** | **18,576** |

These counts are preflight invariants, not numbers to approximate. A build
must abort if the source snapshot does not reproduce them.

For the first model experiment, the recommended baseline is the existing 4B
MixB recipe because it is cheaper and is the model whose weak closed-loop
result motivated this investigation. Freeze the following against the actual
baseline `args.json`, not merely the current sbatch text:

- base model revision;
- `global_batch=64`;
- `learning_rate=3e-6`;
- `num_train_epochs=3`;
- `weight_decay=0.0`;
- `adam_beta2=0.999`;
- warmup, precision, DeepSpeed, seed, max length, image-token budget,
  `last_round` loss mask, and trainer/ms-swift revisions;
- the existing img10/fold1 message representation.

The existing 4B run can be used as an early-screen baseline only if its
`args.json`, code commit, source hashes, and evaluation configuration match.
Otherwise rerun the all-step baseline before making a causal claim.

## 3. Representation: keep context, suppress only the target

The corpus already stores one row for the prefix ending at step `k`, with loss
on that row's final assistant response. Therefore the WebSTAR behavior maps to
the current representation without rewriting conversation history:

```text
trajectory: step1 -> step2_bad -> step3_recovery -> step4_DONE

drop step2_bad as a target row
keep step3_recovery as a target row
step3_recovery's prefix still contains step2_bad in its history
```

The implementation must filter a **copy** of the current rows. It must not
remove the bad step from later prefixes, regenerate images, rewrite teacher
responses, or modify `sft/build.py` in the first experiment.

This gives the desired distinction:

- bad action as a label: suppressed;
- bad action as part of the state that a recovery step must handle: retained.

## 4. Two-stage, versioned pipeline

### Stage A — grade raw steps into an immutable manifest

Grade the target steps corresponding to the 18,576 current MixB rows. The
grader must use the raw trajectory because the current target row contains the
pre-action observation but not the post-action evidence.

For each step, provide:

1. task instruction;
2. stable identity: source build, run, domain, task id, and step number;
3. recent action history;
4. screenshot immediately before the action;
5. the teacher's current reasoning and executed action;
6. screenshot immediately after the action;
7. whether this is the built trajectory's final step.

The post-action screenshot is privileged curation evidence, not a policy input.
It is allowed here because this is offline data selection.

The teacher reasoning is shown only so the grader can detect unsupported or
contradictory claims. Fluent prose is not evidence that an action is correct.

### Stage B — filter exact source copies

Join the frozen manifest to each neutral `samples.jsonl` row by the complete
key below. Copy only accepted rows into a new dataset directory, then perform
the normal mechanical Swift conversion and absolute-path ship.

Never join by `task_id` alone. The same task id can exist under multiple runs.

```text
(source_build, run, domain, task_id, step)
```

Kept Swift rows must be byte-equivalent in messages, target response, image
order, and channel to the source row after the expected path absolutization.

## 5. Grading schema

One JSONL row per source target step:

```json
{
  "schema_version": 1,
  "policy_version": "webstar-step-filter-v1",
  "source_build": "v16-main",
  "run": "<run id from sample meta>",
  "domain": "multi_apps",
  "task_id": "<uuid>",
  "step": 12,
  "n_steps": 27,
  "scores": {
    "action_quality": 8,
    "reasoning_grounded": 2,
    "outcome_progress": 2
  },
  "flags": {
    "redundant": false,
    "invalid_or_hallucinated_action": false,
    "unsupported_state_claim": false,
    "recovery": true,
    "terminal": false,
    "terminal_valid": null
  },
  "decision": "keep",
  "decision_source": "judge",
  "reason": "The action corrects the prior misclick and advances the task.",
  "grader_model": "<exact model and revision>",
  "prompt_sha256": "<sha256>",
  "source_response_sha256": "<sha256>"
}
```

Rubric:

- `action_quality` (`0..10`): WebSTAR-style correctness and usefulness of the
  proposed action; `5` is partially correct or suboptimal.
- `reasoning_grounded` (`0..2`): whether the target reasoning is supported by
  the task and visible state. This is separate because the current loss target
  includes both `<think>` and action tokens.
- `outcome_progress` (`0..2`): whether post-action evidence shows the intended
  effect or meaningful progress.
- `recovery`: the step repairs an earlier error or unproductive state. Recovery
  is valuable supervision and must not be confused with the bad step that made
  it necessary.
- `redundant`: repetition, no-op exploration, or verification with no new
  information.
- `unsupported_state_claim`: reasoning asserts a file, app state, citation,
  save result, or completion state that the available evidence does not support.

The grader response is append-only. Manual overrides must create a new row or
separate override manifest with reviewer, timestamp, and reason; never edit a
judge row in place.

## 6. Proposed v1 decision policy

This policy is a recommendation to review, not yet a frozen implementation.

### Hard decisions

- hard drop a target that names an undeclared/hallucinated action;
- hard drop repeated members already identified as pathological loop targets;
- hard drop a target with a critical unsupported state/completion claim;
- hard keep a valid explicit final `DONE` target;
- never synthesize or rewrite a target in this arm.

### Judge decision

Recommended automatic keep condition:

```text
action_quality > 5
and reasoning_grounded >= 1
and not invalid_or_hallucinated_action
and not unsupported_state_claim
```

`outcome_progress` is evidence and an audit dimension, not a strict gate:
opening a menu, changing focus, waiting for a real load, and other setup steps
can be correct without visible task completion in that single frame.

Send to manual review instead of auto-dropping when any of these hold:

- `action_quality == 5`;
- the step is a recovery;
- the step is terminal;
- two deterministic judge passes disagree on keep/drop;
- screenshots cannot establish whether the action took effect;
- a file-system or application-internal state is required but unavailable.

### Terminal invariant

The final built step of every included trajectory must:

1. remain present as a target;
2. contain the explicit executed `DONE` signal expected by the harness;
3. have a valid terminal decision in the manifest.

If the current 866-trajectory snapshot violates this invariant, dataset build
must stop and print the exact trajectories. Do not silently delete the terminal
row, silently delete the whole trajectory, or manufacture a replacement.
Resolve each exception explicitly before freezing v1.

## 7. Calibration before full grading

Do not spend a full pass on 18,576 steps before testing the rubric.

Build a deterministic 200-step calibration panel, stratified across both v16
and v11 and across domains:

- 100 uniform random retained targets;
- 25 terminal targets;
- 25 recovery targets;
- 25 long-reasoning targets;
- 25 repeated, low-progress, or otherwise risky targets.

Strata may overlap, but the final panel must contain 200 unique keys. Record
the sampling seed and source hashes.

Run the grader twice at temperature zero and manually inspect at least 100
examples, deliberately including disagreements and every auto-drop category.
Before freezing the policy, report:

- keep/drop agreement between the two judge passes;
- manual false-keep rate and false-drop rate;
- confusion by v11/v16, domain, terminal/recovery, and score band;
- concrete examples for every rejection reason.

False keeps are the more damaging error for this experiment, but excessive
false drops can erase rare applications and recovery behavior. Thresholds are
frozen only after this panel; they are not tuned against downstream eval.

## 8. Coverage and sparsity guardrails

The user's existing concern is that broader trajectories may make each app's
operations sparse. Step filtering can worsen that, so every filtered build must
publish before/after tables for:

- v11 versus v16;
- domain and application combination;
- primitive action and normalized semantic operation;
- task difficulty;
- terminal targets;
- recovery targets;
- trajectory-length decile;
- target-token and reasoning-token mass.

Required hard invariants:

- all four source builds are represented;
- every input target has exactly one final decision;
- no duplicate manifest keys;
- no unresolved `review` rows at build time;
- every included trajectory retains its terminal target;
- every referenced image still exists;
- no source file is modified;
- the output report accounts for every one of the 18,576 source rows as
  `keep`, `drop`, or explicitly resolved exception.

Domain/action retention changes are reported, not silently corrected through
oversampling. If a rare operation is erased, revise the grading policy or data
collection; do not hide it by changing sampling in the same arm.

## 9. Experimental arms and fair comparison

### Primary arm

| Field | All-step baseline | Step-filtered v1 |
|---|---|---|
| Source trajectories | MixB 866 | Same MixB snapshot |
| Prefix construction | Current | Unchanged |
| History context | Current | Unchanged, including rejected past steps |
| Target supervision | All current rows | Manifest-kept rows only |
| Length normalization | No | No |
| Model/optimizer/LR/batch | Frozen | Identical |
| Epochs | 3 | 3 |

Using the same epoch count is the primary, practical WebSTAR-style comparison.
It intentionally gives the filtered arm fewer optimizer updates. A performance
gain despite fewer updates is strong evidence for data quality. A loss is
ambiguous because it could reflect either useful removed supervision or lower
training exposure.

### Conditional secondary arm

Only if the primary result is negative or within evaluation noise, add a
separately named exposure-matched arm that resamples **kept** targets to match
the baseline's optimizer updates or supervised target-token mass. Do not fold
this into v1: resampling changes target weights and answers a different
question.

Trajectory-length normalization and fixed-K prefix sampling remain separate
future ablations. They must not be combined with step filtering in the first
run.

## 10. Evaluation contract

Evaluate the 4B step-filtered arm with the exact same harness, template,
image/history policy, task list, seed policy, max steps, and evaluator used for
the existing MixB-4B result.

Primary outcome:

- closed-loop task success, overall and by domain, with `multi_apps` called out.

Required behavioral diagnostics:

- explicit valid `DONE` rate;
- 50-step cap-hit rate;
- average/median interaction steps on successful tasks;
- invalid action rate;
- repeated/no-op action rate;
- recovery after an observable mistake;
- hallucinated state/completion claims from a fixed manual failure sample;
- per-epoch checkpoints, not training loss alone.

Do not select the grading threshold or checkpoint on the same eval-50 used to
report the result. The 200-step calibration panel selects the data policy;
held-out closed-loop evaluation measures it.

## 11. Output layout and provenance

Large datasets and screenshots stay outside Git. The output directory must be
self-describing:

```text
mixB-stepfilter-v1/
  DATA_VERSION.json
  SOURCE_FILES.sha256
  GRADER_CONFIG.json
  FILTER_POLICY.json
  step_scores.raw.jsonl
  step_decisions.final.jsonl
  manual_overrides.jsonl
  retention_report.json
  v16-main_train_swift_abs.jsonl
  v16-pilot_train_swift_abs.jsonl
  v11new-500_train_swift_abs.jsonl
  v11new-all_train_swift_abs.jsonl
```

`DATA_VERSION.json` records:

- experiment and schema version;
- code commit;
- all source path labels, row counts, and SHA-256 hashes;
- grader model/revision, generation parameters, prompt hash, and run dates;
- filter-policy hash;
- counts before/after by source;
- exact output-file hashes.

The training sbatch copies `DATA_VERSION.json`, `FILTER_POLICY.json`, and the
retention report into its independent output directory before launching.
Preflight aborts on a hash mismatch or unexpected row count.

## 12. Git and rollback plan

Work is isolated in a separate worktree and branch:

```text
branch:   exp/webstar-step-filter-v1
worktree: /Users/knight/uw/computeragent/.worktrees/cua-webstar-step-filter-v1
```

The dirty sbatch edits in the original `main` worktree are not part of this
branch. Proposed commit sequence:

1. `docs: freeze WebSTAR-style step-filter experiment protocol`
2. `feat: add immutable step grading manifest`
3. `feat: filter copied SFT rows from a frozen manifest`
4. `test: enforce provenance, terminal, coverage, and byte-identity gates`
5. `sbatch: add isolated MixB-4B step-filter arm`

Production `sft/build.py`, existing data directories, and existing sbatches
remain untouched. Rollback is deleting the experimental output directory and
stopping use of this branch; source data and prior checkpoints require no
restoration.

## 13. Decisions to confirm before implementation

Recommended defaults are shown first:

1. **Run 4B first**, then promote to 9B only if the behavioral result is
   positive or diagnostic evidence is compelling.
2. **Grade both v16 and v11**, rather than filtering only the new data; otherwise
   source family and filtering policy become confounded.
3. **Use `action_quality > 5` plus a reasoning-grounding gate**, calibrated on
   the 200-step panel; do not judge only the action because the target includes
   teacher reasoning tokens.
4. **Require and retain an explicit valid final `DONE`** for every trajectory;
   stop for manual resolution on any exception.
5. **Use the same three epochs for the primary arm**; add exposure matching only
   as a named secondary experiment if needed.
6. **Do not combine length normalization, prefix caps, thought rewriting, or
   teacher balancing with v1.**

Once these six choices are accepted or edited, change status from
`DESIGN REVIEW` to `FROZEN`, commit the protocol, and implement only what the
frozen document specifies.
