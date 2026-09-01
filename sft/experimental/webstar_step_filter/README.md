# WebSTAR filter v1 for CUA SFT

**Primary policy:** `webstar-official-revised-desktop-v1`

**Status:** `IMPLEMENTED / CALIBRATION PENDING`

**Branch:** `exp/webstar-step-filter-v1`

**Base corpus:** MixB, 866 trajectories and 18,576 current target rows

## Scope

This arm tests one variable: whether a current SFT target is retained according
to a minimally adapted copy of WebSTAR's official released step-judge prompt.

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
Therefore the complete official text is not vendored in Git. At runtime,
`adapt_official_prompt.py` extracts `GPT_STEP_JUDGE_REVISED` verbatim from a
user-supplied checkout, verifies its official SHA-256, and applies five
asserted desktop substitutions. The generated full prompt, provenance report,
and unified official-to-desktop diff live with the run artifacts.

## What is faithful to WebSTAR

The grader receives:

1. the user task;
2. the complete previous executed-action text history;
3. up to three chronological **pre-action** screenshots;
4. action annotations on those screenshots;
5. a 200x200 crop around the current coordinate target when available;
6. the actual ordered action bundle executed by the harness, in screenshot
   pixel coordinates;
7. the official released prompt's eight-stage procedure and output format;
8. its `one or more` alternatives rule, simulated outcomes, `<=6` penalty for
   a strictly better alternative, and final 0-10 expected value.

The official code accumulates `previous_actions` without truncation. Only its
visual `sliding_window` is capped at three screenshots. This adapter mirrors
that behavior: full previous action text, three latest annotated screenshots,
and the current action separately.

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
| `policy_official_revised.json` | Primary official-code-aligned method and hashes |
| `policy_official_equal_budget.json` | Experimental same-or-lower action-budget variant |
| `adapt_official_prompt.py` | Hash-verified official extraction, base adapter, and opt-in equal-budget adapter |
| `policy_v1.json` | Historical paper-four-stage profile |
| `prompt.py` | Historical paper-four-stage prompt used only for comparison |
| `common.py` | Stable identity, source indexing, action/terminal parsing, hashes |
| `visuals.py` | Green action label, red coordinate markers/arrows, 200px crop |
| `sample_calibration.py` | Deterministic 200-step calibration panel |
| `grade_steps.py` | Resumable multimodal grading, strict four-stage validation, and append-only raw scores |
| `decide_steps.py` | Score manifests to keep/drop/review decisions |
| `make_flip_review.py` | Paired score-manifest flip derivation and static review site |
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

> **Version boundary:** The corrected model comparisons and the 307-row
> retention result below used prompt hash
> `46a359cca3c14a65f792f2d2f5f1c3226c43ca7ecc140b41580cf274a391af4c`.
> They remain an audit trail but are superseded by the stricter paper-four-stage
> prompt v2 and must not be reported as the current retention estimate.

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

### Primary official-revised desktop adapter

The primary runtime prompt is generated from the full official
`GPT_STEP_JUDGE_REVISED` constant at the pinned commit. The adapter first
requires this exact official hash:

```text
240c77aca3c08b4f862c48d91f35a8a3a22303554eb5f3d584a2df39cb2f7906
```

It then applies exactly five asserted substitutions:

1. allow the proposed step to contain an ordered desktop action bundle;
2. replace the browser action-space block with the pyautogui desktop space;
3. remove the WebVoyager-only URL/back/sign-in restriction;
4. adapt `final_answer` to explicit DONE/terminate;
5. rename `web element` to `UI element`.

Everything else remains official: all eight stages, `one or more`
alternatives, simulation, the `<=6` strictly-better-alternative rule, 0/5/10
anchors, and the final score format. The adapted runtime hash is:

```text
3cd1d4350f1f6b59f69f0b9fc44ad220b8b72beb34ec711eae5293d40768ee69
```

The complete generated diff contains 55 lines, mostly the action-space block.
The provenance report and diff are produced beside the runtime prompt and are
required audit artifacts rather than hand-written documentation.

Luna completed an initial official-adapter smoke with no API, image, or score
parsing failures. Three positive controls all scored `8`. Eight selected risky
steps scored:

```text
0, 1, 1, 2, 2, 3, 6, 6
paper threshold: drop 6, keep 2
```

This proves the complete official prompt can run on the local desktop data;
the full rerun below establishes its local single-pass retention rate. The old
307-row result used a different prompt hash and remains superseded.

The full local 307-row pilot was subsequently rerun with this exact official
adapter and Luna. The run stopped once at 193 completed rows because six PPAPI
connections remained in a long timeout; the append-only manifest was resumed
with the same pass id and completed the remaining 114 rows without duplication.

Integrity checks:

```text
rows: 307
unique step keys: 307
prompt profile: official-revised-adapted-d5c2a34 (307/307)
prompt sha256: 3cd1d4350f1f6b59f69f0b9fc44ad220b8b72beb34ec711eae5293d40768ee69 (307/307)
grader model: gpt-5.6-luna (307/307)
API/image/path/score failures: 0
```

Raw official threshold result:

```text
score > 5:  241 keep
score <= 5:  66 drop
single-pass retention: 78.50%
```

By domain:

```text
Chrome: 213 / 270 keep = 78.89%
GIMP:    28 /  37 keep = 75.68%
```

Score distribution:

```text
0: 0   1: 13   2: 10   3: 7   4: 14   5: 22
6: 47  7: 35   8: 123  9: 30  10: 6
```

Applying the terminal safety policy to the same single pass gives:

```text
keep:    239 / 307 = 77.85%
drop:     66 / 307 = 21.50%
review:    2 / 307 =  0.65%
```

All twelve terminal rows scored above 5. Ten explicit terminate/DONE targets
are auto-kept; the two implicit endings become review. Three of the fifteen
source trajectories have no terminal target row at all, an existing corpus
defect outside step scoring. Per-trajectory raw retention ranges from 58.5% to
100%, with a median of 77.8%.

Temporary artifact hashes:

```text
scores:    ed2ba8570a595ce3bd057f4e626739460fa6e9f396bf106f7b1d2761fc355aab
decisions: 86546fcdfb4d27188b3cc6faf62679df6f4153b64c1564edd590e69ab27bb818
```

This 78.50% replaces the superseded 80.46% only for this old, imbalanced local
pilot. It is still a single-pass engineering estimate, not the expected MixB
retention rate or the final two-pass keep rate.

Paired by the complete step key, 38/307 rows (12.38%) cross the `score > 5`
threshold between the old simplified prompt and the official-adapted prompt:

```text
keep -> drop: 22
drop -> keep: 16
same keep:    225
same drop:     44
```

The net keep change is only `-6`, so comparing 80.46% with 78.50% hides much
larger bidirectional churn. The two terminal rows that were below threshold
under the old prompt move above it under the official prompt; no terminal moves
from keep to drop. Because these are two independent Luna calls as well as two
different prompts, the 38 flips cannot all be causally attributed to the
prompt. A prompt-effect estimate would require repeated paired calls under both
profiles.

The complete flip CSV is a temporary audit artifact with SHA-256:

```text
c951620247dec4c2056cf28447a8cfc80e049d69b9af9dfc1dbee3b93c49b070
```

`make_flip_review.py` turns those paired flips into a static human-review site.
Each card shows the task, actual action bundle, the judge's three annotated
pre-action screenshots and current crop, old/new scores and reasoning, and the
original teacher target. The page supports transition filters, free-text
search, delta sorting, anchors, and a full reset.

The current local report contains 38 cards and 128 compressed image assets:

```text
http://127.0.0.1:8765/reports/webstar-step-flips/
```

Browser QA verified the 22/16 transition counts, GIMP search, absolute-delta
sorting, and reset behavior. Generated HTML/JPEG reports stay outside Git;
only the deterministic generator is versioned.

### Experimental equal-action-budget variant

The official-adapted profile above remains byte-for-byte unchanged. A separate
opt-in profile, `official-revised-equal-budget-v1`, tests the observed failure
mode where the judge compares one correct atomic step with a longer future
plan. It is an experimental desktop correction, not a claim of exact WebSTAR
reproduction.

For each target, `grade_steps.py --equal-action-budget` adds:

```text
CURRENT_ACTION_BUDGET: N primitive action(s)
```

Here `N` is the exact number of executed pyautogui actions in the current
bundle. The prompt requires every proposed alternative to:

1. contain at most `N` primitive actions;
2. execute immediately from the current visible state;
3. use no intermediate screenshot, observation, branch, or later policy step;
4. count as strictly better only when it dominates at that same step
   granularity.

A correct necessary intermediate action cannot be penalized merely because
future work remains. Invalid longer plans do not trigger the official `<=6`
cap. All other official stages, score anchors, output parsing, and the
`score > 5` keep threshold remain unchanged.

Generation and grading are both explicit opt-ins:

```text
adapt_official_prompt.py --equal-budget ...
grade_steps.py --equal-action-budget \
  --prompt-profile official-revised-equal-budget-v1 \
  --response-contract official-revised ...
```

The grader fails closed if the runtime prompt contains this contract but the
action-budget flag is absent, or if the flag is present with a different
prompt.

The generated runtime prompt hash is:

```text
5590a47a9d6fe057dfa1a0077f844f0bd545cd4cc69fdae10dc7607b84b6d454
```

The unmodified official-adapted artifact regenerated to its prior hash and was
byte-identical to the earlier artifact. A targeted Luna smoke then compared
independent calls under the original official adapter and the equal-budget
variant:

| Check | Original official adapter | Equal-budget variant |
|---|---:|---:|
| Click visible Save button, intermediate export | 5 | 8 |
| Press Enter to commit docket cell | 5 | 8 |
| Press Enter to commit first `DONE` cell | 5 | 8 |
| Three positive controls | 8, 8, 8 | 9, 8, 9 |
| Eight risky controls, sorted | 0, 1, 1, 2, 2, 3, 6, 6 | 2, 2, 2, 2, 2, 3, 7, 9 |

All three targeted responses explicitly enforced the one-action comparison
budget and rejected longer alternatives. Six of eight risky controls still
scored at or below 5; the same two ambiguous risky controls that the original
adapter kept also remained above threshold. Because these are stochastic,
independent judge calls and the controls are not human gold labels, this smoke
checks mechanism and regressions only. It is not a new retention estimate.

Temporary smoke manifest hashes:

```text
targeted intermediate cases: f51efdc9d3d685bd77e9f6cbeabf181e84044a99dc9c60c9113b640e173a1b41
positive controls:           9491a2db97c840c0231a2b256ab73b29a3a8c106d4a2605dd9d4149ebddef076
risky controls:              467315300e177c38b39482900bc96f1613d6cb0f24c6cd079321249bd06e8cf1
```

The complete 307-row pilot was then graded once with this exact equal-budget
profile and Luna. All rows completed with no API, image, path, or score-parser
failure:

```text
rows / unique keys: 307 / 307
prompt profile: official-revised-equal-budget-v1 (307/307)
prompt sha256: 5590a47a9d6fe057dfa1a0077f844f0bd545cd4cc69fdae10dc7607b84b6d454
grader model: gpt-5.6-luna (307/307)
equal-action-budget: enabled (307/307)
action budgets: 300 one-action rows, 7 two-action rows
```

Raw threshold result:

```text
score > 5:  254 keep
score <= 5:  53 drop
single-pass retention: 82.74%

Chrome: 223 / 270 keep = 82.59%
GIMP:    31 /  37 keep = 83.78%
```

Applying the terminal-target safety policy gives:

```text
keep:   252 / 307 = 82.08%
drop:    53 / 307 = 17.26%
review:   2 / 307 =  0.65%
```

The two reviews are unchanged source-target defects: the raw runner executes
DONE, but the corresponding SFT target response lacks an explicit
`terminate`/DONE tool call.

Paired against the original official-adapted Luna pass, the new prompt keeps
13 additional rows net, moving raw retention from 78.50% to 82.74%:

```text
drop -> drop: 44
drop -> keep: 22
keep -> drop:  9
keep -> keep: 232
threshold flips: 31 / 307 = 10.10%
```

The three targeted intermediate-action false negatives remain above threshold
in the complete pass: visible Save `5 -> 8`, docket-cell Enter `5 -> 7`, and
DONE-cell Enter `5 -> 9`. Across all rows, 158 scores rise, 124 stay equal,
and 25 fall; the mean score change is +0.71. Thus the contract fixes the known
cases but also shifts the distribution broadly enough that the 31 threshold
flips require human inspection. Independent stochastic calls also mean these
flips cannot all be causally attributed to the prompt.

The generalized `make_flip_review.py` can derive threshold flips directly
from any two complete score manifests, rather than requiring a hand-maintained
CSV. The current review site contains 31 cards and 106 image assets:

```text
http://127.0.0.1:8765/reports/webstar-equal-budget-flips/
```

Browser QA verified the 307/241/254 headline counts, both 9/22 transition
filters, the three-result WAIT search, absolute-delta sorting, prompt labels,
and reset behavior. Generated HTML/JPEG reports remain outside Git.

Artifact hashes:

```text
scores:    e7a58e6caa6147d64f39e2d4d7d702e62e162778236382a9a059688528896a09
decisions: f761d0cb3ca8e8e37a2ecb13a42da841106857596a529dc7f2bd0ec2a8591a64
```

### Historical paper-four-stage prompt v2

The historical paper-prose-aligned comparison profile is:

```text
version: webstar-paper-four-stage-v2
sha256: 406e2e8b6a9193a176eadbf7b3e6167850346f7aeaca6c9561a7ee92b8fdf152
```

It enforces, in code rather than by instruction alone:

1. `Screenshot analysis`;
2. `Proposed action review`;
3. `Alternative analysis` containing exactly numbered alternatives `1/2/3`,
   each with feasibility, simulated outcome, and comparison;
4. `Evaluation` with the paper's 0/5/10 anchors and final expected value.

It also mirrors the official implementation's history behavior: all previous
executed actions are provided as text, while annotated screenshots remain a
three-image sliding window. Missing/reordered sections or any alternative
count other than exactly three fail parsing and trigger a retry.

An initial Luna smoke under v2 completed with no format failures. The three
positive controls received:

```text
ordinary first step: 5
navigation to required ~/documents folder: 10
terminal completion: 4 -> terminal review
```

The eight deliberately risky controls received:

```text
scores: 1, 1, 1, 2, 2, 2, 4, 6
paper threshold: drop 7, keep 1
```

The only kept risky case was the ambiguous extra WAIT on a blank GIMP
Preferences dialog. These 11 calls prove strict prompt compliance and show
that the history/alternative changes materially affect scores. They do not
provide a new overall retention estimate; the old 80.46% must be rerun before
use.

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

### Superseded 307-row local pilot retention estimate (old prompt)

After the coordinate correction and model smoke, Luna scored all 307 target
rows in `v11-500-partial-snap-pilot2` once. All calls completed; there were no
API, image, path, or score-parsing failures.

Raw WebSTAR threshold result:

```text
score > 5:  247 keep
score <= 5:  60 drop
single-pass retention: 80.46%
```

By domain:

```text
Chrome: 217 / 270 keep = 80.37%
GIMP:    30 /  37 keep = 81.08%
```

Score distribution:

```text
0:  0   1: 20   2: 15   3: 4   4: 12   5: 9
6: 32   7: 31   8: 85   9: 84  10: 15
```

Applying the terminal safety policy to that single pass changes the operational
decisions to:

```text
keep:    245 / 307 = 79.80%
drop:     58 / 307 = 18.89%
review:    4 / 307 =  1.30%
```

The pilot contains 15 trajectories but only 12 terminal target rows. Ten of
those twelve carry an explicit tool-call stop. Among the twelve scored terminal
rows, eight are auto-kept and four become review because of low score or
implicit ending. Separately, three trajectories have no terminal target row at
all; step scoring does not repair that existing corpus defect.

Per-trajectory raw retention ranges from 33.3% to 100%, with a median of 81.1%.
This is an old, highly imbalanced pilot (270 Chrome rows and 37 GIMP rows), so
80.46% is a local engineering estimate, not the expected MixB retention rate.
The final policy still requires the representative calibration and two-pass
disagreement review.

Temporary artifact hashes:

```text
scores:    0ed01be8cbb6d96063eb18f8192562cad844b1b24aefdd602bea7cb114c851db
decisions: 7825d6498b1f4e4c0229bad0aed388722c3cafb997a8ac2581e397696f629daf
```
