# WebSTAR filter v1 for CUA SFT

**Policy:** `webstar-filter-v1`

**Status:** `IMPLEMENTED / CALIBRATION PENDING`

**Branch:** `exp/webstar-step-filter-v1`

**Base corpus:** MixB, 866 trajectories and 18,576 current target rows

## Scope

This arm tests one variable: whether a current SFT target is retained according
to a WebSTAR-style step score.

```text
score > 5  -> keep the current target row
score <= 5 -> drop the current target row
```

It preserves the original teacher `<think>`, target response, later history,
images, model, optimizer, learning rate, batch, epoch count, and prefix
construction. It does not use thought augmentation, trajectory normalization,
exposure matching, or post-action grading.

Dropping step 2 as a target does not remove it from step 3's context:

```text
step1 -> step2_bad -> step3_recovery -> step4_DONE
          no loss       keep; history still contains step2_bad
```

## Paper and code provenance

- Paper: <https://aclanthology.org/2026.acl-long.21/>
- Official repository: <https://github.com/yifei-he/WebSTAR>
- Pinned reference commit:
  `d5c2a34cb7ff193a85c144fdd91f48a0e716da86`
- Relevant reference files:
  - `step_eval/gpt_prompts.py`
  - `step_eval/data_visualization_full.py`
  - `step_eval/generate_thought_and_process_no_ss.py`

The pinned repository did not contain `LICENSE`, `COPYING`, or `NOTICE`.
Therefore this directory is an attributed clean-room adaptation of the
published procedure, not a verbatim vendor copy. The prompt structure, visual
interface, o4-mini grader, 0-10 score, and `score > 5` threshold follow the
reference. Local I/O, action parsing, manifest handling, and failure gates are
new code.

## What is faithful to WebSTAR

The grader receives:

1. the user task;
2. recent executed actions;
3. up to three chronological **pre-action** screenshots;
4. action annotations on those screenshots;
5. a 200x200 crop around the current coordinate target when available;
6. the actual ordered action bundle executed by the harness, in screenshot
   pixel coordinates;
7. an instruction to compare viable alternatives and assign expected value
   from 0 through 10.

The current action has not executed in the judge input. The grader does not see
the post-action screenshot. The original teacher think is excluded from the
judge input and preserved unchanged in training. This keeps thought
augmentation out of v1.

## Necessary desktop adaptations

| Official WebSTAR | This arm |
|---|---|
| Browser-only actions | Hermes desktop `computer_use` actions |
| One action per step | One ordered action bundle per model step |
| Web-only restrictions | Removed |
| `final_answer` | Explicit `terminate` / DONE |
| Folder-local result JSON | Collision-proof global step manifest |
| Loose path/action assumptions | Fail-closed source hashes and identity |

The teacher target expresses pointer coordinates on a relative 0-999 grid,
while screenshots and executed pyautogui actions use screen pixels. The judge
receives the executed pixel-coordinate action bundle so its textual action,
red marker, and screenshot share one coordinate frame. The original relative
target remains unchanged in the SFT data and its hash remains the provenance
anchor.

The unique identity of every target is:

```text
(source_build, run, domain, task_id, step)
```

Joining on `task_id` alone is forbidden because the same id can occur under
multiple runs.

## Implemented modules

| File | Responsibility |
|---|---|
| `policy_v1.json` | Frozen method and reference provenance |
| `prompt.py` | Attributed desktop adaptation of the step-value procedure |
| `common.py` | Stable identity, source indexing, action/terminal parsing, hashes |
| `visuals.py` | Green action label, red coordinate markers/arrows, 200px crop |
| `sample_calibration.py` | Deterministic 200-step calibration panel |
| `grade_steps.py` | Resumable o4-mini grading and append-only raw scores |
| `decide_steps.py` | Score manifests to keep/drop/review decisions |
| `audit_report.py` | Before/after source, domain, action, length, terminal, recovery and token tables |
| `filter_copy.py` | Filtered Swift JSONL copies with existing remote image roots |
| `test_webstar_filter.py` | Offline unit and integration tests; no API calls |

Production `sft/build.py`, `sft/traj.py`, `sft/to_swift.py`, source datasets,
and existing sbatches are untouched.

## Pipeline

### 1. Index the exact MixB source snapshot

The neutral `samples.jsonl` files, not the shipped Swift files, are the
canonical join source because the latter no longer contain run/task/step meta.
The grader prefers the latest model-visible processed images from each neutral
sample; raw trajectory screenshots are a strict fallback. This keeps grading
on the pixels the student context actually contains while retaining raw action
bundles and collision-proof provenance.

Required source invariants:

| Source family | Trajectories | Rows |
|---|---:|---:|
| v16 (`v16-main` + `v16-pilot`) | 554 | 13,372 |
| v11 new (`v11new-500` + `v11new-all`) | 312 | 5,204 |
| **Total** | **866** | **18,576** |

### 2. Generate the calibration panel

`sample_calibration.py` selects 200 unique targets with a recorded seed:

- 100 balanced random targets;
- 25 terminal targets;
- 25 recovery-like targets;
- 25 longest-think targets;
- 25 repeated or otherwise risky targets.

Source builds are round-robin balanced within each stratum when candidates are
available. The output records source hashes and the reason each key was chosen.

### 3. Grade calibration twice

`grade_steps.py` requires `--targets` unless the operator explicitly supplies
`--all`. This prevents an accidental 18,576-call launch.

Each raw score row records:

- the full step key;
- integer score;
- full judge analysis;
- model and pass id;
- adapted prompt SHA-256;
- source response SHA-256;
- raw trajectory path and action bundle;
- hashes of judge input images.

The output is append-only and resumable. Failed calls do not create a completed
row, so the next invocation retries them. API keys are read from
`OPENAI_API_KEY` and are never written to output.

### 4. Produce decisions

`decide_steps.py` applies only the paper threshold:

```text
all passes score > 5   -> keep
all passes score <= 5  -> drop
passes disagree        -> review
```

Terminal exceptions are stricter:

- a terminal target without an explicit tool action `terminate`/DONE becomes
  `review`;
- a terminal target scoring 5 or lower becomes `review`, not a silently
  missing ending;
- manual resolution is append-only in a separate override manifest with
  reviewer and reason.

### 5. Create filtered copies

`filter_copy.py` requires one final decision for every source row and rejects
all unresolved `review` entries. It converts kept neutral samples through the
existing mechanical Swift converter and remaps images to the supplied existing
GPFS source roots. It neither copies nor re-encodes images.

The output directory must be new and empty. Swift files are first written under
temporary names and atomically renamed only after all source, path, hash, and
terminal checks pass; a failed build cannot masquerade as a trainable partial
dataset.

The output contains:

```text
mixB-webstar-filter-v1/
  DATA_VERSION.json
  SOURCE_FILES.sha256
  FILTER_POLICY.json
  step_decisions.final.jsonl
  retention_report.json
  v16-main_train_swift_abs.jsonl
  v16-pilot_train_swift_abs.jsonl
  v11new-500_train_swift_abs.jsonl
  v11new-all_train_swift_abs.jsonl
```

`DATA_VERSION.json` stores the code commit, policy hash, decision-manifest
hash, source hashes, output hashes, and before/after counts.

## Hard failure gates

The pipeline stops before ship when any of the following occurs:

- source rows are not the expected 18,576;
- a source or decision key is missing or duplicated;
- source response changed after grading;
- score is absent or outside 0-10;
- grader output lacks its final expected-value line after retries;
- a `review` remains unresolved;
- a retained trajectory loses its terminal target;
- the terminal target lacks an explicit tool-call stop signal;
- a source image is missing;
- an absolute image path cannot be safely mapped under its declared source;
- source, prompt, policy, decision, or output hashes disagree.

## Retention audit

The generated report compares before/keep/drop/review and estimated target and
think token mass by:

- source build;
- domain;
- target action signature;
- trajectory-length bucket;
- terminal versus nonterminal;
- recovery-like versus ordinary.

This exposes whether filtering disproportionately removes v16, `multi_apps`,
rare actions, terminal supervision, or recovery behavior. The first arm does
not correct imbalances through resampling because that would add another
experimental variable.

## Tests

Run from the repository root:

```bash
python3 -m compileall -q sft/experimental/webstar_step_filter
python3 -W error::ResourceWarning -m unittest -v \
  sft.experimental.webstar_step_filter.test_webstar_filter
```

The current test suite verifies:

- deterministic, unique calibration sampling;
- exact WebSTAR threshold behavior;
- low-scoring terminal steps become review;
- dropping an intermediate target does not remove it from later context;
- teacher think is absent from judge input;
- judge receives only pre-action screenshots;
- action annotation and crop dimensions;
- missing decisions, unresolved terminal loss, path errors, and response-hash
  drift fail closed;
- filtered output hashes and counts are recorded.

## Current execution boundary

Completed:

- official paper/code inspection and pinned provenance;
- filter-only prompt and policy adaptation;
- calibration sampler;
- visual annotations;
- o4-mini client and resumable raw manifest;
- decision and manual-override layer;
- filtered-copy builder and retention audit;
- offline tests.
- local PPAPI multimodal compatibility smokes on an older 307-row /
  15-trajectory pilot, including corrected `gpt-5.6-luna`, `gpt-5.6-sol`, and
  `gpt-4o-mini` judge runs.

Not yet executed:

- resolving the four real neutral-build, raw-result, and task-set paths on the
  data host;
- generating the real 200-step panel;
- any o4-mini call (`o4-mini` is not offered by the tested PPAPI model list);
- manual calibration review;
- full 18,576-step grading;
- filtered dataset ship;
- new 4B sbatch or GPU training.

The next allowed operation is the 200-step calibration. Full grading remains
blocked until its judge agreement, false-keep behavior, terminal cases, and
per-domain retention have been inspected.

## Local PPAPI compatibility smoke (2026-08-31)

This smoke is an engineering check, not MixB evidence. It used the local
`v11-500-partial-snap-pilot2` snapshot:

```text
source rows: 307
trajectories: 15
samples.jsonl sha256: c8c56690e3bcf3632b1dbcec34d0c8c45e4bd6c05d90c324378e4a0942176486
corrected grader: PPAPI gpt-5.6-luna
```

The PPAPI endpoint authenticated and listed 132 models. It did not offer
`o4-mini`; it offered `gpt-4o`, `gpt-4o-mini`, and `gpt-5.6-luna`. The
credential remained in the ignored local environment file and was not written
to any manifest, prompt, report, or Git file.

Offline construction joined the neutral rows to the exact raw run and task
set. Initial `gpt-4o` and `gpt-4o-mini` requests proved API, image, parsing,
resume, and decision compatibility. Their quality scores are superseded: the
judge text contained the teacher's relative 0-999 coordinate while the red
marker and screenshot used 1920x1088 pixels. Some judges compared those values
directly and penalized or rewarded a mismatched location.

The implementation was corrected to give the judge the actual ordered
pyautogui action bundle in screenshot pixel coordinates. The original target
remains unchanged in training and remains the hashed provenance anchor. Tests
now require the executed pixel action in the judge input and reject leakage of
the relative target coordinate.

With the corrected input, `gpt-5.6-luna` scored three ordinary/positive
controls as:

```text
ordinary first step: 6
useful navigation/recovery: 9
terminal completion: 10
```

The same corrected grader scored eight deliberately risky repeated-WAIT,
repeated-click, off-target, or redundant-action steps as:

```text
scores: 1, 1, 1, 1, 2, 3, 3, 4
paper threshold: drop 8, keep 0
```

The explanations were grounded in the screenshots and executed pixels: for
example, already-focused fields were clicked again, loading links were clicked
twice, empty-state waits were repeated, and some actions targeted blank space.
The three positive controls rule out a model that simply assigns low scores to
everything.

Four risky targets were independently rescored:

```text
3 -> 4  drop
2 -> 2  drop
1 -> 0  drop
1 -> 1  drop
```

All 4/4 remained on the same side of `score > 5`, and `decide_steps.py`
produced four drops with no review. This is a small, risk-enriched smoke, not a
population accuracy estimate.

Consequences:

- the input, multimodal API, score parser, append-only manifest, and two-pass
  decision path work end to end;
- the judge must receive one coordinate frame; earlier `gpt-4o` and
  `gpt-4o-mini` scores are compatibility evidence only and cannot be compared
  with the corrected Luna scores;
- corrected PPAPI `gpt-5.6-luna` showed useful positive/negative separation and
  stable threshold decisions on the four repeated risky cases;
- the real calibration must keep two independent passes and manual review of
  all threshold disagreements;
- these results do not replace the planned MixB calibration and do not justify
  full-corpus grading or training.

### Corrected `gpt-5.6-sol` comparison

With the same pixel-coordinate input, `gpt-5.6-sol` scored the eight risky
targets as:

```text
scores: 1, 1, 1, 2, 3, 4, 5, 7
paper threshold: drop 7, keep 1
```

The only kept risky target was a second WAIT on a blank GIMP Preferences
dialog. Sol considered one more low-risk wait a reasonable recovery; Luna
considered it a redundant retry (`7` versus `3`). This case is genuinely
ambiguous and belongs in a recovery-focused manual audit.

The three positive controls received:

```text
ordinary first step: 10
navigation to the required lowercase ~/documents folder: 3
terminal completion: 9
```

The navigation score is a concrete Sol false negative in this sample. Sol
mistook the visible lowercase `documents` folder for the wrong location and
preferred the desktop's standard `Documents` folder, while the task trajectory
and successful completion specifically use `~/documents/induction_pack`.
Luna correctly scored that step `9`.

The four-target Sol repeat panel produced:

```text
5 -> 6  review
3 -> 3  drop
1 -> 2  drop
1 -> 2  drop
```

Thus 3/4 repeat cases stayed on the same threshold side and one became review.
Across the shared eleven corrected first-pass targets, Luna and Sol agreed on
the threshold side for 9/11. The two disagreements were the lowercase-folder
false negative above and the ambiguous recovery WAIT.

On this tiny smoke, Luna better matches the known task evidence and separates
all three positive controls from all eight selected risky steps. Sol is more
permissive about recovery but introduces one clear false negative. This does
not establish model-wide superiority; it makes Luna the better current
candidate for the registered 200-step calibration, with Sol useful as an
independent disagreement judge on recovery and borderline cases.

### Corrected `gpt-4o-mini` comparison

The same pixel-coordinate input was also rerun with `gpt-4o-mini`; none of its
pre-fix scores were reused. The eight risky targets received:

```text
scores: 1, 1, 1, 2, 2, 3, 3, 4
paper threshold: drop 8, keep 0
```

However, all three positive controls were also rejected:

```text
ordinary first step: 3
navigation to the required lowercase ~/documents folder: 3
terminal completion: 2
```

Its terminal explanation claimed that the merge had not occurred and that the
agent was ending prematurely, despite the successful trajectory and final
completion evidence. In this three-frame prompt regime, `gpt-4o-mini` is too
conservative and does not reliably reconstruct accumulated task progress.

The four-target repeat panel produced:

```text
2 -> 2  drop
3 -> 8  review
1 -> 2  drop
3 -> 2  drop
```

Thus 3/4 remained on the same threshold side and one became review. The model
is useful for rejecting obvious bad actions but fails the minimum positive
control requirement, so it is not a viable primary judge for the 200-step
calibration under the current WebSTAR-compatible input.

Corrected smoke summary:

| Judge | Positive kept | Risky dropped | Repeat threshold-stable |
|---|---:|---:|---:|
| `gpt-5.6-luna` | **3/3** | **8/8** | **4/4** |
| `gpt-5.6-sol` | 2/3 | 7/8 | 3/4 |
| `gpt-4o-mini` | 0/3 | **8/8** | 3/4 |

This tiny, selected smoke is not a performance benchmark, but Luna is the only
candidate that clears all three local sanity conditions simultaneously. The
registered 200-step calibration should therefore start with Luna; Sol can
audit recovery disagreements, while 4o-mini should remain out of the main
filter unless a different context/prompt design is tested as a separate arm.
