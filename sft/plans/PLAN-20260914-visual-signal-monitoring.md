# Standalone CUA Trajectory Debugger

Updated: 2026-09-15. The user's latest instruction supersedes the earlier integration with the research-report website: **this is an independent tool, with graph and evidence on the same page.**

## 1. Scope and current status

Implemented and tested on 2026-09-15: real client request/response capture, original image bytes and hashes, every returned action screenshot, evaluator inputs/results, and vLLM attention plus full-vocabulary entropy at configured output positions. Initial low-resolution smoke tests yielded 18 attention rows and 18 entropy rows. A subsequent full-resolution run of the same real Verified and V2 tasks retained **1920×1088 model inputs / 2,040 vision tokens per image**, with **289 attention rows and 289 entropy rows covering every generated position across six decisions**, at decoder layer 23/head 0. Both runs used an isolated Qwen3.5-0.8B diagnostic service. These are infrastructure tests, not new 9B/27B experiment results.

The rollout/post-processing split is now implemented and validated. The rollout saves raw data and publishes a durable ready record. A separate `process-pending` worker validates files and generates the website. Both real tasks were processed through this worker; a second pass did no work, and hashes of native trajectories, scores and saved signals stayed unchanged. The two integrity reports passed; all 11 referenced image files decoded and their HTTP bytes matched the original files.

The new code is deployed to the isolated workstation tool at `/home/yanji/cua-signal-diagnostic-20260915/tool`, with pages on the workstation WSL host exposed through the private local link `http://127.0.0.1:8794/index.html`. The older 500-task historical viewer remains a separate source export; the later unified catalog on Mac port 8793 combines its formal results with OSWorld2 and keeps feature diagnostics in a separate section. See the [current pipeline guide](../docs/TRAJECTORY_PIPELINE.md) for ports and availability. Those historical runs did not record these model internals. The paused formal campaigns were not resumed by these tests. Future runs must select the recorded client and instrumented server configuration; an ordinary vLLM endpoint does not provide attention automatically.

Keep code clean and small. Use the Python standard library and native browser HTML/SVG/JavaScript. No LLM-generated summaries, diagnoses, state labels or judgments. Screenshots remain in their existing Windows/WSL directories. No Vercel, storage-platform work, training changes or extra services are required.

## 2. Reusable pipeline

```text
Rollout continuously saves raw requests, signals, actions and evaluator evidence
  -> task completion publishes a ready record
  -> independent process-pending worker
  -> read that task's saved trajectory and available signals
  -> construct grouped graphs while retaining every execution occurrence
  -> generate an independent task HTML + raw JSON
  -> atomically update the task index and original-file manifest
  -> open the task: graph on the left, selected evidence on the right
```

When enabled, the callback publishes a ready record after **each task**. Processing is deferred by default; a separate worker can run later, or use `--watch` to process completed tasks automatically without entering the rollout call stack. `render-run` backfills an existing complete evaluation through the same `render_task` function; it does not call a model or rerun tasks.

| Source | Responsibility |
|---|---|
| [after_task.py](../scripts/eval/after_task.py) | One-time hook installer, task-completion callback, complete-panel backfill, artifact/index writing and standalone serve command |
| [visual_signals.py](../analysis/visual_signals.py) | Shared raw-record parsing, model/data naming, screenshot references and signal alignment checks |
| [trajectory_viewer.py](../analysis/trajectory_viewer.py) | Graph construction, standalone page generation and allowlisted HTTP serving |
| [trajectory_viewer.html](../analysis/trajectory_viewer.html) | Reusable independent UI template; no React/report-app dependency |
| [trajectory_index.html](../analysis/trajectory_index.html) | Collapsible run directory, shared search and source-backed filters |
| [test_visual_signals.py](../tests/test_visual_signals.py) | Synthetic regression tests and reproducible loop fixture |

All required viewer source is inside the CUA repository. The pipeline does not import, rebuild, update, or navigate to `cua-experiment-report/site`. Legacy `viewer_url`, `snapshot`, `build_command` and external `asset_base` configuration fields are ignored by this standalone pipeline.

## 3. Graph semantics

The viewer offers three explicit modes:

| Mode | Node identity | Preserved information |
|---|---|---|
| Same action + recorded app (default) | Python AST-normalized executed command, including all argument values, plus recorded app | Every occurrence retains its own source row, screenshots, response and signal selection |
| Identical screenshot + recorded app | SHA-256 of the saved before-image file plus recorded app | Different actions at the same saved image remain individually selectable |
| Every execution | One node per recorded action occurrence | The uncollapsed chronological path |

Repeated transitions point back to existing nodes. Consecutive repetitions produce self-loops. Edges retain the actual adjacent occurrence pairs and their counts. Node counts refer to recorded occurrences, not unique successful behaviors. Graphs never merge tasks, runs or episodes.

The full chronological execution strip remains available in every mode. Clicking a repeated node reveals buttons for each visit, such as actions 2, 4, 6 and 7; choosing a visit loads that exact occurrence's evidence. Previous/next controls traverse execution order, not node order.

Same command does not prove the same UI control or environment state. Screenshot hashing is exact file matching, not semantic or approximate screen clustering. Unknown apps stay unknown; missing image hashes produce separate state nodes. No model is used to guess page/element identity.

## 4. Same-page evidence

Every selected occurrence shows:

- The complete task instruction and recorded model/run metadata.
- Before/after screenshots; markers on the before-image for literal executed click/move/drag coordinates.
- Original model step, within-step action, source JSONL row and timestamp.
- Exact executed action, original thinking extracted from recorded think fields/tags, and the complete original prediction/response.
- The original action record and available tool reply, reward, done and evaluator fields.
- Available model-input pictures, attention query rows and heatmaps, plus raw token counts/probabilities and complete signal JSON.

A graph-node click changes the detail panel on this page. It never opens the old research website. Image enlargement is a same-page dialog. Raw JSON and an SVG of the currently displayed graph can be downloaded explicitly.

Missing screenshots, predictions or signals remain visibly unavailable; the viewer does not manufacture content. Original response text is never translated or summarized. Known credential fields are omitted from structured exports. The tool is intended for local inspection.

### Final evaluation evidence

The **Final evaluation / last action** button selects the last recorded occurrence and opens its evaluator panel. Only the latest episode receives `result.txt` and final evaluation evidence. The panel includes original `evaluator.func`, `expected`, `result`, `options`, `postconfig`, the recorded final action and score, and links to the original runtime log and result file.

Historical backfill reads the current benchmark configuration and current `DesktopEnv.evaluate` source without executing them; their paths and SHA-256 hashes are attached, explicitly labelled as current sources rather than historical run snapshots. For the recorded `infeasible` branch, the viewer displays the expected `FAIL` marker against the actual terminal action, a literal diff and whether that branch's result agrees with the saved score. For other tasks ending in `FAIL`, it shows the script's early-return rule.

These 200 historical tasks did not retain the actual `result_getter` / `expected_getter` return values or file copies in their result directories. The UI exposes the standard-answer file URL and comparison rules when present, but marks the actual inputs and content diff unavailable. A VM result-file path is a getter configuration, not a recovered historical output. Screenshots and model claims are not substituted for evaluator inputs. This paragraph records the historical backfill limitation. The later native recorder now captures actual evaluator inputs/returns for supported new runs; it cannot recover those missing historical values.

## 5. Alignment and identity

Use the existing [armname.py](../armname.py) naming registry. Prefer recorded run metadata (`args.json`, `MODEL_BOUNDARY.json`, `version.json`) and actual callback arguments; absent fields remain unknown. The callback also accepts the original task example when the result directory has no `task.json`.

A run identity includes source plus absolute run path, using a short deterministic digest for navigation. Task/episode identities retain run, task-relative path and episode index. A canonical model name is never used as a run's identity. Old directories are not renamed.

Preserve every action and restart boundary. One response may produce several actions; thinking/token cost belongs to the parent model decision. `result.txt` supplies the latest appended episode score only, not a score for every historical episode.

Native runs may store the initial observation only in `initial_state.png`, without an initial JSONL row. Use that file before the first action and preserve the original row numbers. If appended episodes make the shared initial file's identity ambiguous, leave the old episode's initial image unavailable instead of assigning an unverified screenshot.

Execution screenshots and model-input images are separate. Attention is shown only on a recorded model-input image. The current click is never copied onto a historical input image. Executed pixel coordinates are mapped once using recorded PNG dimensions; missing or non-literal coordinates are not guessed.

## 6. Recorded visual signals

The rollout recorder writes `<task>/visual_signals.jsonl`; the separate exporter consumes it. The opt-in vLLM collector supplies actual sampled attention rows and token entropy. Legacy trajectories can still be inspected without these signals.

Each signal object must include matching `episode`, `step_num`, `checkpoint`, `request_id`, `request_sha256` and `response_sha256`. Request ID/hash must also be present on the corresponding action record. The response hash is SHA-256 of the exact recorded UTF-8 response. `origin` distinguishes original-run capture, replay and fixture provenance.

Each ordered `images` occurrence supplies a unique `id`, task-relative `path`, byte `sha256`, `source_step`, `token_count` and original attention `key_indices`. Repeated use of one image file still has separate occurrence IDs. Optional `patch_boxes` are normalized `[x0,y0,x1,y1]` boxes in the same order as those indices. Without that recorded mapping, no spatial heatmap is invented.

Heatmap colors use blue for low weight, white for the middle of the displayed range and red for the highest weight. The default display uses `log1p(w / m) / log1p(max / m)`, where `m` is the median nonzero image-key weight across all input images in the selected row/overview. An explicit linear option retains `w / max`. All input images share one scale, including when only one is visible; changing the selected output/decision recalculates its display range, so colors alone are not absolute comparisons across decisions. The legend shows original-weight values at zero, the transformed midpoint and maximum. No clipping or second softmax is applied.

Opacity increases with displayed intensity, with an adjustable maximum (default 80%); zero weights are transparent. Patch grid lines are optional and hidden by default. This keeps screenshot text visible while retaining every real patch, with no smoothing or invented resolution. Hover exposes the original weight and model-input patch center. URL fields `scale`, `grid` and `opacity` retain the view. The image-mass card uses all attention keys as its denominator; the per-image share column uses only the summed image mass. Both are displayed as percentages, and raw values remain inspectable.

The display change was motivated by real pilot task 011, decision 3: its maximum image-key weight was 1,007 times the median and 99.15% of patches were below 10% of that maximum. Linear colors plus opaque blue fill and white grid lines hid most variation. Its whole-output overview covers 659 tokens (131 thinking); executed action `DONE` and raw prediction `call_user` remain unmodified. This one layer/head overview does not identify which UI control the complete model understood or why the task failed. Display verification covered monotonic mapping, inverse legend values, zero/empty/uniform data, unchanged raw weights, the same color for a patch in single/all-image views, grid/scale controls and URL refresh restoration. Browser checks on task 011 loaded all three 1920×1088 images and retained 2,040 patches per image; image mass stayed 17.53% across display changes. The two completed pages were regenerated with seven protected task/raw/score files unchanged.

The viewer also offers **Whole output / mean heatmap**, the default when opening a task without an explicit token selection. For each model decision and each layer/head separately, `attention_overviews()` averages the original attention weight for every fixed image key across the recorded output positions. All recorded token types are included (formatting, action, and thinking where present). Missing positions are not filled with zeros; missing or duplicate output identities make that group's overview unavailable. The UI shows `recorded / total` coverage and labels partial captures explicitly. The 48-position full-resolution decisions therefore use 48/48, whereas the older sparse runs use 3/48 rather than claiming a complete output.

Image mass, image share and spatial/image entropy are recalculated from the mean weights, using the existing `attention_rows()` implementation. Per-token image shares or heatmap colors are not averaged. Different layers, heads, model decisions and screenshots are not merged. All images in an overview retain one common color scale. Averaging preserves the overall distribution but can dilute brief local peaks, so the single-token mode remains available. `attention=mean` / `attention=token` in the URL preserves the view; existing links with an explicit `output` but no mode retain their single-token behavior.

This is deterministic post-processing in `task_html()`: it derives the overview during normal page generation and leaves saved requests, raw attention, evaluation outputs and source images unchanged. Regenerating the page from an existing task bundle is sufficient; no model call or new rollout is needed. Raw overview weights and covered positions are inspectable in the page's disclosure panel. Unit coverage checks raw-weight averaging before normalization, unequal decoder key lengths, head/layer separation, zero mass, incomplete/ambiguous coverage and preservation of the original bundle.

Aggregate-view acceptance on 2026-09-15: all 23 viewer/signal tests passed. All four existing diagnostic task pages were regenerated through `task_html()`; per-patch means matched independent arithmetic, served HTML matched generated bytes, and all 18 protected raw/task/score files retained their hashes. Browser checks confirmed full-resolution Verified 48/48, full-resolution V2 49/49, sparse Verified 3/48 with an explicit partial-coverage label, loaded images and working mean/single-token switching. The evidence is `/home/yanji/cua-signal-diagnostic-20260915/aggregate-heatmap-acceptance.json`.

The viewer provides a top-level heatmap shortcut, side-by-side history/current input images, a raw-image/overlay toggle, actual predicted-token labels, and a record-coverage inventory. In the initial low-resolution Verified test, the second decision had 1,510 input tokens and 48 output tokens; all 48 output logprob entries were retained, but attention and full-vocabulary entropy covered only output indices 0, 1 and 4 (`<tool_call>`, newline, `=`), at layer 23/head 0. Those are format-token diagnostics, with 60 visual tokens per image (model-side 320×192). The later full-resolution runs below collect coordinate tokens too. The UI labels client and model-processed dimensions separately, and `&output=29` in the URL selects zero-based output position 29. Large raw JSON panels are formatted only when opened.

Each selected `attention` row supplies `layer`, `head`, `query`, `dtype`, `key_count` and original nonnegative `weights`. Keep selected query rows rather than full long-context matrices. The consumer computes:

- `frame_mass[j]`: sum of the original weights belonging to image occurrence j.
- `image_mass`: sum over the image occurrences.
- `frame_share[j]`: frame mass / image mass; zero denominator remains undefined.
- Mean weight per visual token, alongside image token counts.
- Within-image spatial entropy `-sum(p * ln(p))`, in nats.

No second softmax is applied. Heatmap opacity uses one shared display scale across images of the selected attention row; numerical weights remain unchanged. Spatial entropy is not output-token entropy. Optional `counts` and `output_tokens` are displayed as recorded; top-k logprobs are not treated as full-vocabulary entropy. The existing thinking estimate is explicitly labelled characters / 3.5.

Checkpoint/request/response/image mismatches produce an unverified state. Raw signal files can be read explicitly inside the same page, but unverified heatmaps are not attached to a decision.

### Benchmark compatibility: verified on 2026-09-15

Both current native benchmark runners were tested with the same environment-gated `capture_runtime/sitecustomize.py` hook; neither benchmark source file needed editing for the smoke tests. The existing V2 entry wrapper is also supported, and `wrap_task` is idempotent. New runs require the shared tool path and `CUA_INSPECTION_CONFIG` in their worker environment.

- **Verified:** task `28cc3b7e-b194-4bc9-8353-d04c0f4d56d2`, three decisions/actions, score 1.0, nine attention rows and nine entropy rows. `result_getter`, `expected_getter` and the real metric call were recorded.
- **V2:** task `006`, three decisions/actions, score 0.0, nine attention rows and nine entropy rows. The task's actual source, shared getter/metric calls, expected file list and actual directory listing were recorded. Calc's setup command logged a timeout while its GUI stayed open; the real screenshot was visually checked. This test is not a task-performance measurement.
- Both exported trajectories have every before/after image. The collector saves screenshot bytes already returned by `env.step`, including V2 intermediate batched actions. Native benchmark scores and logs are unchanged.
- Qwen3.5-0.8B / BF16 / vLLM 0.25.1 / TP1 / eager / FlashAttention was exercised live. Tensor-parallel mapping has numerical/unit coverage; a full 9B/27B campaign and physical TP2 collector acceptance have not been run here.

The initial attention configuration sampled decoder layer 23, head 0, output indices 0, 1 and 4. The later configuration below covers every generated position within its 256-token output limit, still at one layer/head. Other layers/heads, full vocabulary logits, pixel-value tensors and hidden states are not saved. A missing field remains unavailable; historical screenshots cannot recover original-run attention.

### Full-resolution acceptance: 2026-09-15

The same two native runners were rerun in new result directories, with three decisions per task, at most two input images, and `max_tokens=256`. Their raw data was saved first; the independent worker subsequently processed both completed tasks with `failed=0` and `invalid=0`.

| Setting / result | Initial smoke test | Full-resolution test |
|---|---|---|
| Model-side image dimensions | 320×192 | 1920×1088 |
| Grid per image | 10×6 | 60×34 |
| Vision tokens per image | 60 | 2,040 |
| Decoder layer / head | 23 / 0 | 23 / 0 |
| Configured output indices | 0, 1, 4 | 0–255, covering the complete generated responses here |
| Verified generated positions per decision | 48, 48, 48 | 48, 48, 48; all attention/entropy rows saved |
| V2 generated positions per decision | Selected-position capture only | 48, 48, 49; all attention/entropy rows saved |

Original environment screenshots are 1920×1080; the client prepares 1920×1088 inputs, which the full-resolution model processor retains. Each heatmap cell therefore corresponds to a real merged visual token spanning 32×32 input pixels. The grid is not interpolated into invented finer measurements.

The isolated server uses Qwen3.5-0.8B, BF16, vLLM 0.25.1, TP1, eager FlashAttention, `max_model_len=8192`, `max_pixels=2088960`, `min_pixels=4096`, a 192 MiB KV cache, and at most two images. Prefix caching, asynchronous scheduling and multimodal processor caching are disabled for this diagnostic protocol. `validate_kernel=true` checks captured rows against the actual attention output. The collector implementation is unchanged; only its capture configuration and serving image/context budgets changed. Main teacher service and paused formal campaigns are separate.

- Verified: run `verified-fullres-qwen-smoke`, task `28cc3b7e-b194-4bc9-8353-d04c0f4d56d2`, native score 1.0. [Second decision, first x-coordinate token](http://127.0.0.1:8794/task-b5458b07b1289ff37efca6c107d34aba.html#episode=0&occurrence=1&group=action&panel=signals&output=29).
- V2: run `v2-fullres-qwen-smoke`, task `006`, native score 0.0. [Second decision, first x-coordinate token](http://127.0.0.1:8794/task-1361c761f3a1e35da9f64b21d9bf8bc0.html#episode=0&occurrence=1&group=action&panel=signals&output=29).
- Both integrity reports passed with zero errors/warnings, seven decoded images and three verified signal decisions each. Each step retained all generated attention/entropy positions; all input-image occurrences have 2,040 tokens. Browser inspection confirms coordinate-token selection, both history/current grids and loaded full-resolution images.
- Workstation evidence: `/home/yanji/cua-signal-diagnostic-20260915/fullres-acceptance.json`, `fullres-http-acceptance.json`, both `*-fullres-launch.json` / `*-fullres-inspection.json`, native result directories and `pages/validation/*.json`.
- Serving provenance: `/gscratch/cse/jy050706/cua-signal-diagnostic-20260915/fullres-serving.json` and `capture-fullres.json`. Collector SHA-256: `26533794848e8065c43c3633153742f3dbe41a6f370f3410876a1078f2aca90f`.

These are six short, real rollout decisions; they do not establish full-campaign performance or capture overhead. Retaining dense rows for every output position increases page size to approximately 46–48 MB per three-step task. Raw JSON formatting is deferred in the UI; this acceptance does not claim all-layer/head capture or scalable all-position export for a full 100-task campaign.

### All-output-token storage and eight-task pilot (2026-09-15)

The user requested all output positions, followed by an **eight-task OSWorld-V2 test only**, split as 2 VMs on the older Windows host and 6 VMs on the workstation. The larger paused campaign is not authorized to resume automatically. The planned pilot tasks are 003/005 on the older host and 007–012 on the workstation. Both use the existing shared benchmark commit `d552441917f302fab410a1991cc705d7bf585d14`, Qwen3.8-27B BF16 TP2, thinking enabled, preserve_thinking disabled, 10 images/fold 1, history 100, 100 steps, and maximum output 81920. Model HTTP timeout is 1800 seconds for this capture pilot.

Full-output capture uses `output_indices: "all"` and `attention_storage: "binary"`, with the actual model's last full-attention layer (63) and head 0. It still does not collect all layers/heads. Each attention row is stored losslessly as little-endian float32, independently compressed with zlib. The JSON records the byte offset, compressed length, shape and chunk SHA-256. The server returns descriptors; its API-key-protected `/v1/cua-attention/` route streams the file. The client streams to a temporary file on the evaluation host, verifies the complete byte count/SHA-256, flushes/fsyncs and atomically renames it before executing the next action. Failed downloads retry up to three times and remain capture errors/unverified evidence if unsuccessful; no substitute heatmap is created.

The shared [attention_store.py](../analysis/attention_store.py) reads one row at a time. Export calculates per-token statistics and the complete-output mean from the original weights without loading the entire tensor history into memory. Binary rows stay out of task HTML and normalized JSON; each decision's signal JSON loads only when selected. The browser obtains a selected row through a checked HTTP byte range, verifies its SHA-256 and decompresses it using the native browser API. Existing inline JSON captures remain supported. The independent worker and standalone server are still the normal pipeline; scores and evaluator logic are unchanged.

An isolated capture teacher was submitted as Klone job `40190392` on `g3112` (2×L40S, 24-hour limit). The prior teacher job `40178215` on `g3104` remains intact. The pilot uses eager FlashAttention, no prefix/processor caching, context 262144, at most 8 scheduled sequences and 1920×1088 maximum processed screenshot dimensions. Both hosts use loopback-only port 8102 SSH tunnels; the older Windows tunnel connects through the workstation loopback. The tool/profiles/evidence live under each host's `~/cua-v2-pilot-20260915/`; the server files are under `/gscratch/cse/jy050706/cua-v2-pilot-20260915/`. Source hashes are recorded per file.

Status at preparation: host tests passed on both machines; seven numerical/storage tests passed inside the pinned vLLM container. The real TP2/think/all-token probes are a required launch gate; no benchmark task starts merely because `/v1/models` is healthy. The capture checks require every output position exactly once per configured layer/head, complete entropy positions, causal query alignment, actual sampled-token identity, successful lossless downloads and a protected artifact endpoint. Pilot progress and acceptance are recorded in `probe-acceptance.json` and each run's `launch.json`, raw files, validation reports and monitor outputs.

Pilot launch update: the workstation passed a real 768-output-token TP2 thinking probe, retaining 768 attention rows and 768 entropy records plus a 7,296,719-byte verified artifact. The six-task runner is PID 54604, postprocessor 54605, viewer 54606 and monitor 54607. Task 011 completed with original score 0.0 and a passed integrity report. Task 012 ended with a native screenshot timeout / NoneType error; it has no final score, and its generated page correctly fails integrity checks for missing after-image and native/captured action mismatch. Four tasks were still running at this check. The older Windows machine has been unreachable since 17:30 PDT; its two tasks have not started. The user explicitly asked to proceed with the workstation first. The pilot viewer is exposed locally on port 8796. Local final regression checks: 43 passed, including repository-layout checks.

### Capture inventory and implementation

Status: core collection and independent post-processing are implemented, with the live acceptance above. The table below defines the intended raw-evidence contract; fields available only from a particular backend/check remain explicitly qualified. Attention and full-vocabulary output entropy follow the recorded output-position configuration; the full-resolution diagnostic covers all generated positions at one layer/head, not all layers/heads.

#### Required raw evidence

| Evidence | What to retain | Capture point |
|---|---|---|
| Identity and protocol | Benchmark/version, source host, run/task/episode/phase, model decision and retry attempt IDs, checkpoint revision, tokenizer/processor/chat-template identity, sampling and history policy | Task start and each model request |
| Actual image context | The images actually sent after history selection/compression, their order, source steps, ages, byte hashes and sent dimensions; retain the original observation reference separately | Final client request construction |
| Model-side image representation | Actual processed dimensions, `image_grid_thw`, merge/crop mapping, per-image token counts and sequence key spans/indices | Server processor / model input preparation |
| Request and raw API response | Losslessly reconstructable logical request (image references replace duplicate base64 only in saved records), full response metadata, reasoning/content, IDs, finish/stop reason and errors | Around the existing API call, before response-to-string conversion |
| Generated token stream | Engine-returned output IDs, boundaries for reasoning/action/control tokens, selected-token logprobs and top-k alternatives when supported | Response or backend generation output |
| Selected decoder attention rows | Layer, head, query position, the output token being predicted, key mapping and original attention weights; include dtype/backend and capture origin | Model forward / generation, sampled requests only initially |
| Action and environment evidence | Every executed action and coordinates, available before/after screenshots, reward/done/tool feedback and user-simulator response | Existing task loop: persist initial observations and existing `env.step` screenshot bytes, including V2's non-final batched actions; additional screenshot API calls require a separately recorded diagnostic option |
| Evaluator evidence | Original criteria/code identity, actual evaluator return including rich `result.json`, per-check expected/actual values when exposed, and task-scoped copies/hashes of comparison files before reset | The existing evaluator/getter calls, without evaluating a second time |
| Timing and termination | Client end-to-end request latency, retries, truncation/stop reason; server queue/prefill/decode/cache measurements only where actually available | Client and supported server request metrics |

Capture records belong to a **model decision**, not every PyAutoGUI action emitted by that decision. Retries and V2 phases must retain separate identities. The final request is the authority for image order; a requested `image_max` or original screenshot resolution is not proof of what reached the model.

#### Required derived outputs

For one recorded layer/head/query, let `a[k]` be its attention weight to key `k`, `K[j]` the key positions of image occurrence `j`, and `N[j] = |K[j]|`.

| Output | Definition / source | Qualification |
|---|---|---|
| Per-image attention mass | `m[j] = sum(a[k] for k in K[j])` | Preserve original weights; no second softmax |
| Total image attention | `M = sum(m[j])` | Shows how much of this row's attention is assigned to the recorded visual keys |
| Share across images | `s[j] = m[j] / M` | Conditional on visual attention; undefined if `M=0` |
| Mean attention per visual token | `m[j] / N[j]` | Display next to token counts and shares to reveal budget-size effects |
| Image-selection entropy | `-sum(s[j] * ln(s[j]))`; also `/ ln(number_of_images)` when that number exceeds 1 | Measures dispersion across images; retain `M` so high conditional focus with almost no visual mass is not misleading |
| Within-image spatial entropy | Normalize that image's weights by `m[j]`, then compute `H[j] = -sum(p[k] * ln(p[k]))` | In nats; undefined when image mass is zero |
| Normalized spatial entropy | `H[j] / ln(N[j])` for `N[j] > 1` | Helps expose the trivial dependence on token count; does not make different resolutions semantically identical |
| Output-token entropy | `-sum(p[v] * ln(p[v]))` over the full vocabulary at selected output positions | Requires full logits at that stage; compute the scalar on device, rather than saving the full vocabulary for every token |
| Token budgets and ratios | Actual per-image/input/reasoning/output counts; vision-budget and thinking-length comparisons | Engine counts, processor counts, re-tokenized text and character estimates must have different provenance labels |
| Raw probability comparisons | Selected output-token logprobs / top-k alternatives aligned with their text/ID positions | Top-k probabilities alone do not define full-vocabulary entropy or the probability that an entire coordinate/action is correct |

Raw model-logit entropy (before temperature/top-p) and sampling-distribution entropy must not be conflated. Zero denominators, one-element normalization cases, missing counts and unsupported layers remain explicitly unavailable. Sampling only some layers/heads cannot be presented as the whole model's attention. No automatic claim of "correct history image" or "failure cause" is derived from entropy or attention alone.

#### Minimal implementation sequence

1. **Shared request recorder.** Add one small common writer with thin benchmark adapters. The Verified insertion point is `/mnt/d/research/OSWorld/mm_agents/qwen/client.py:call_openai_compatible`; the shared V2 agent inherits `Qwen35VLAgent.call_llm` in `mm_agents/qwen35vl_agent.py`. Both currently extract message text/reasoning and discard other response fields. Record the request/response before that conversion while keeping the existing return string and action parser unchanged. Include task-scoped decision/attempt IDs in the native action records or an explicitly verified row mapping. Persist V2's already-returned intermediate `obs['screenshot']` before adding any new screenshot requests; distinguish these environment observations from images actually supplied to the model. Do not rely on the current shared `draft/message_cache` filename scheme as a per-task archive.
2. **Exact token and image mapping.** Probe the pinned vLLM API for `request_id`, `return_token_ids`, usage and logprob support; verify returned fields rather than assuming that a successful request means they were honored. Add a small model-input preparation hook for per-image visual key spans/grid data that the API does not return. Reasoning token counts come from the actual generated IDs and reasoning boundaries; re-tokenizing the formatted client response is a fallback labelled as such. Preserve actual multimodal preprocessing rather than calculating counts from the original PNG alone.
3. **Sampled attention diagnostics.** First validate a small set of real requests in a separate diagnostic run. Read the actual checkpoint's `layer_types`; target decoder `full_attention` layers. The official Qwen3.5-9B configuration has 32 layers with 8 full-attention layers, and Qwen3.8-27B has 64 layers with 16 full-attention layers; the other layers are linear-attention layers and must not be given invented dense attention matrices. For a selected output token, capture the query row that predicts it (respecting the causal one-token shift), the image-key mapping and the selected weights. If the kernel does not expose weights, reconstruct only those rows from the actual post-RoPE Q/K using the model's scale, GQA head mapping, masks and KV positions, leaving the main attention computation intact. Validate this against a small reference attention computation first. Paged KV caches, tensor parallelism and CUDA Graph replay make a generic Python forward hook insufficient; the pinned hook is implemented in `analysis/vllm_capture.py`; only its documented backend modes are supported.
4. **Reuse the current viewer.** Emit matched records into the existing signal schema, extend its derived metrics for image-selection/normalized/output entropy, and use the existing per-task completion callback to regenerate the table, curves and heatmaps. Keep raw arrays and source identifiers inspectable. Basic request evidence may be shown without attention; heatmaps still require verified checkpoint/request/response/image/patch alignment. Both benchmarks use the same metric/rendering code; only task/request/evaluator adapters differ. V2 currently vendors a renderer copy, so schema changes require an explicit version sync.
5. **Capture evaluator detail at the real check.** For Verified, intercept the existing getter/metric return values; for V2, retain the rich evaluator result and capture shared evaluation-helper inputs where possible. Arbitrary custom `Task.evaluate` methods may need explicit check-recording calls; no universal Python-local-variable extractor is planned. Preserve comparator inputs before VM reset/cache overwrite. Do not infer an actual result from a screenshot or rerun the evaluator just to obtain a diff.

For fused-attention backends, avoid requesting all layers' full `T x T` matrices. Use an explicit task/step/layer/head/query sampling configuration, measure capture overhead and increase coverage only after validation. Any backend/cache/attention-mode changes belong to the diagnostic run's recorded protocol. Offline teacher-forced replay of saved requests/original output prefixes is an additional route, clearly labelled `replay`; it is not original-run attention, and a different inference backend may change numerical results.

The relevant API and model references checked for this design are [vLLM 0.25.1 API](https://docs.vllm.ai/en/v0.25.1/serving/online_serving/openai_compatible_server/), [Qwen3.5-9B config](https://huggingface.co/Qwen/Qwen3.5-9B/blob/main/config.json) and [Qwen3.8-27B config](https://huggingface.co/Qwen/Qwen3.8-27B/blob/main/config.json). Deployed checkpoint files remain authoritative when implementing.

#### Optional controlled intervention

Region occlusion/blur and history-image removal/replacement are separate diagnostic experiments. Hold the request context, model/protocol and original observation fixed, record the exact intervention and compare raw output probabilities/actions. Use baseline/control perturbations; do not call any resulting attention or prediction difference a task-success explanation by itself. Counterfactual actions are not executed in the original eval and their results are not merged into its score.

#### Acceptance before expanding capture

- Reconstruct the same logical request and verify image-byte/order hashes and retry/phase linkage; logging must not silently change prompt content or sampling settings.
- Reconcile processor image-token spans with actual model input positions; handle repeated image occurrences separately.
- Validate attention weights, image mass/shares, raw and normalized entropies on a small reference; explicitly test missing data and zero denominators.
- Verify the prediction/query one-token alignment, GQA/RoPE/masking and original-run versus diagnostic/replay provenance.
- Show real model-produced evidence from at least one Verified task and one current shared V2 task, then confirm the post-task pages appear automatically. Synthetic heatmap fixtures alone do not pass this acceptance.
- Record logging latency/memory impact and preserve existing scores and evaluator behavior. Until these checks pass, keep live attention collection marked incomplete.

### Real collection flow and configuration

The model is still called only by the benchmark agent. There is no additional LLM that explains or labels a trajectory.

1. **Worker startup:** `scripts/eval/capture_runtime/sitecustomize.py` attaches the existing `after_task.wrap_task` callback in both the parent and spawned workers. The wrapper is idempotent, including the existing V2 entry point.
2. **Task/model decision:** `analysis/capture.py` creates a task-scoped recorder. It saves the exact client request, ordered image occurrences and byte hashes, raw API reply, retry identities and timing. Image preprocessing hooks preserve source-step lineage when it is unambiguous.
3. **Actual model forward:** `analysis/vllm_capture.py`, enabled on the model server, reads the actual processor grids and visual key positions. For selected decoder full-attention layers/heads/output positions it reads the post-RoPE query and paged KV cache. Only one attention row per selection is reconstructed. Logit entropy is computed over the full vocabulary before temperature, penalties or top-p. The original sampler's chosen token supplies its exact raw logprob.
4. **Action and evaluation:** the existing `agent.predict`, `env.step` and `env.evaluate` results are returned unchanged. Already-returned screenshot bytes are saved after every action, including V2's intermediate actions. Getter/metric inputs, returns and referenced files are captured at the real evaluation call. V2 shared helpers/controller calls and phase evaluators are covered; custom checks can explicitly call `capture_check` to expose their individual values.
5. **After each task:** publish `<output>/pending/<id>.json` only. The independent `process-pending` worker verifies identities, reconstructs requests, decodes every image, checks native action order and token alignment, then builds graphs, tables and HTML. The image manifest is published before pages can reference it. Failed processing can be retried without running a model. Heatmaps are SVG overlays generated from saved weights and patch boxes when the page is viewed.

Task-local outputs:

```text
<task>/
  traj.jsonl                    # Original benchmark log, unchanged
  result.txt / result.json      # Original benchmark result, unchanged
  visual_signals.jsonl          # One matched record per model decision
  capture/
    trajectory.jsonl            # All observed actions and already-returned screenshots
    events.jsonl                # Decisions, user replies, evaluator calls, errors and timing
    task.json                  # Task metadata snapshot (older captures can use events)
    manifest.json              # Preserved native prefix and resume identity
    requests/<request-id>.json   # Reconstructable request + raw API metadata
    assets/<sha256>.*            # Exact sent images, observations, API bodies, evaluator inputs
    interventions.jsonl         # Optional counterfactual requests; actions are never executed
```

Post-processing is independent of rollout:

```bash
# Process all completed ready records once, after or between rollouts.
python3 sft/scripts/eval/after_task.py process-pending --config /path/to/inspection.json
# Optional: one separate worker follows future completed tasks automatically.
python3 sft/scripts/eval/after_task.py process-pending --config /path/to/inspection.json --watch
# Retry processing failures after repairing their cause; no model is called.
python3 sft/scripts/eval/after_task.py process-pending --config /path/to/inspection.json --retry-failed
```

JSON snapshots and images use temporary files, flush/fsync and atomic replacement. JSONL writes are locked and flushed/fsynced per record. These controls prevent partial replacement and concurrent-line interleaving; hardware or filesystem failure can still interrupt a capture and must not be reported as successful. Each generated task has `<output>/validation/<task-id>.json`. Pending-job versions prevent an older processing completion from erasing a newer ready task.

Enable client recording in the normal inspection configuration:

```json
"capture": {"enabled": true, "backend": "vllm", "attention_every": 1, "top_logprobs": 5}
```

`backend: "vllm"` requests token IDs/logprobs and sends the capture flag. It does not change message content, temperature, top-p or output budget. Other backends may use raw client capture without this setting; unsupported server signals stay unavailable.

For either native benchmark runner, set `CUA_INSPECTION_CONFIG` as before and prepend these paths to `PYTHONPATH` before starting Python:

```bash
export PYTHONPATH="$CUA_ROOT/sft/scripts/eval/capture_runtime:$CUA_ROOT:$HARNESS_ROOT:$HARNESS_ROOT/scripts/python${PYTHONPATH:+:$PYTHONPATH}"
# Run the normal benchmark command, using a new result directory for diagnostics.
```

The server-side JSON contains, for example:

```json
{"directory":"/path/to/task-signal-spool","layers":[31],"heads":[0],"output_indices":[0,16,64],"top_k":5,"validate_kernel":true}
```

Omitting `layers` selects the actual model configuration's last full-attention layer. Output indices are zero-based generated-token positions; the corresponding query predicts that token. `validate_kernel` checks that the captured row multiplied by cached values agrees with the live attention kernel output. It is useful for acceptance, and costs additional work.

Enable the pinned vLLM collector before starting the model server:

```bash
export CUA_VLLM_CAPTURE_CONFIG=/path/to/server-capture.json
export PYTHONPATH="$CUA_ROOT/sft/scripts/serve/visual_capture:$CUA_ROOT${PYTHONPATH:+:$PYTHONPATH}"
# Add to the existing vLLM 0.25.1 serving command:
# --enforce-eager --attention-backend FLASH_ATTN --kv-cache-dtype auto
# --no-enable-prefix-caching --mm-processor-cache-gb 0 --no-async-scheduling
```

This is an explicit diagnostic serving protocol: eager execution changes performance relative to a CUDA-graph service. The collector records it. It supports tensor parallelism, not speculative decoding, pipeline/context parallelism, quantized KV caches, sliding-window/ALiBi attention or arbitrary attention backends. Unsupported modes must not produce plausible-looking heatmaps. Existing historical trajectories cannot gain original-run attention retroactively.

Optional intervention commands use an archived request and an explicit JSON list such as `[{"operation":"occlude","image_index":0,"box":[0.2,0.3,0.4,0.5]}]`. A fresh unchanged baseline is included. Supported operations are `occlude`, `blur`, `remove` and `replace`.

```bash
python3 -m sft.analysis.intervene /path/to/task/capture/requests/<id>.json \
  --spec /path/to/interventions.json --base-url http://localhost:8000/v1 \
  --inspection-config /path/to/inspection.json --run-dir /path/to/run
```

Only the diagnostic model requests are run; resulting actions are saved as text, never applied to the VM. The original task score stays unchanged. Request/response comparison is raw evidence, not a generated explanation of failure.

## 7. One-time setup and normal use

Current commands and deployment details are maintained in the [trajectory pipeline guide](../docs/TRAJECTORY_PIPELINE.md). It is the single operational reference for native startup hooks, client/server capture configuration, the independent postprocessor, render/backfill, and the unified catalog.

New/resumed evaluations use that workflow by default. Real evals, including the eight-task OSWorld2 run, belong to `collection: "eval"`; feature-development diagnostics belong to `collection: "test"`. Reuse registered output directories so new tasks/runs appear automatically at the same entrance.

### Recover local viewer access

See [viewer access](../../docs/OPS.md#trajectory-viewer-access). Mac port 8793 now serves the unified catalog. The old Windows viewer is an upstream on Mac port 18793; do not replace the catalog with the old direct 8793 tunnel. As of 2026-09-16, automatic SSH reconnect is disabled at the user’s request. Reuse authenticated sessions, establish forwards once, and stop on authentication failure; no recursive login loop.

`render` / `render-run` regenerate captured tasks from their saved raw evidence. Legacy `refresh` / `refresh-pages` use current static JSON task configs and must not be used as generic refreshes for captured V2 Python-class tasks.

## 8. Outputs and operational behavior

```text
cua-trajectory-debugger/
  index.html                 # Independent task directory
  index.json                 # Run/task/episode metadata and local page links
  manifest.json              # Allowlist of original screenshot/raw files
  task-<stable-id>.html       # One independent page with all episodes of a task
  tasks/<stable-id>.json      # Raw export and action/state/expanded graph structures
```

The callback reads only the finished task. A local file lock serializes shared updates from parallel workers. JSON/HTML replacement is atomic. Repeated callbacks replace the same entries without deleting other tasks. Original results and screenshots are not copied or modified. The server binds to loopback and serves only generated tool files and explicitly referenced original files; no directory browsing or arbitrary path access.

The source index is updated by the postprocessor. The unified catalog periodically reads registered source indexes and updates the visible formal/test section, preserving browser state. It caches only catalog metadata; raw assets are streamed on demand. There is no background LLM or automatic public publication.

Each run is a native `details` group, initially collapsed; runs remain separate even when their canonical model names match. Group headers show dataset, registered backbone and training method, recorded inference parameters, precision, task counts and whole-run scores. The directory supports expand/collapse all, search, combined filters and reset. Filters include canonical model, dataset, benchmark domain, original related apps, score category, backbone/parameter scale, training method, image window, fold size, step cap, temperature and original evaluator function. The original benchmark has no separate intent/category labels, so no semantic task labels are inferred. Filters and open groups are retained within the browser session; filtering opens matching groups, while **Collapse all** remains available at any time. Run-level summary scores retain their full-run denominator while matching task counts change.

### Return position and task navigation

The index stores search/filter values, expanded run groups, advanced-filter expansion and scroll position in `sessionStorage`. Opening a task additionally records the clicked row and its viewport offset. **Return to list** restores those settings and brings the most recently viewed task back to that position; browser Back is supported through `pageshow` restoration as well. Storage is scoped to the current browser tab/session, with no server-side user-state database.

Task pages have **Back**, **Return to list**, **Previous task** and **Next task** controls, separate from the existing previous/next action controls. When entering from the index, task navigation uses the filtered task order within the clicked source run and does not jump into another model/run. Multiple episodes of one task count as one task in that navigation list. Direct task links load `index.json` and use the full source-run order instead. The first/last navigation buttons are disabled at the boundaries. Navigation context only accepts task pages on the same origin; raw task instructions are labels, never navigation commands.

The completion callback publishes a durable ready record after the task function returns or raises. Graph generation and validation run in a separate postprocessor by default; explicit inline mode remains available for compatibility. Errors are logged and preserve the original evaluation return/exception. They do not retry model calls, actions or evaluations. Setup failures with no trajectory produce no invented graph. Malformed trajectories report errors rather than silently discarding actions.

## 9. Validation and remaining work

Unified-catalog acceptance (2026-09-15): 26 catalog/viewer/signal tests passed, including live addition of another run, explicit formal/test classification, offline metadata cache/recovery, source namespaces, unchanged asset bytes, HTTP Range and path rejection. Browser checks on the actual 27B OSWorld2 task011 loaded the original 1920px screenshots and its 2040-patch mean heatmap, preserved next-task/back-to-list navigation, and retained independent formal/test expansion state. The six historical Windows runs are registered but their source was unreachable during this acceptance; this is not a claim that all500 historical pages were verified online again. Current operational details are in the [pipeline guide](../docs/TRAJECTORY_PIPELINE.md).

Run `python3 sft/tests/test_visual_signals.py` for the focused synthetic checks. They cover all occurrences in a 200-action path, collapsed return edges/self-loops, separate apps/runs/episodes, unknown states, exact image matching, HTML script escaping, same-source serving and traversal rejection, parallel/idempotent callbacks, source immutability, and attention alignment/calculations.

A reproducible cyclic UI fixture is available via `python3 sft/tests/test_visual_signals.py --write-loop-fixture /new/temporary/results`. It is explicitly synthetic, not evidence of model performance.

Local validation on 2026-09-15: 20 focused tests and 7 existing repository checks passed. Regressions cover separately saved initial screenshots, complete-panel backfill, index metadata refresh across separate runs sharing a model, run-scoped naming aliases with unchanged original args/checkpoints, script escaping, and evaluator backfill preserving original actions/scores and episode scope without executing evaluator code. Synthetic browser checks verified return edges/self-loops, four separately selectable visits to one repeated action, correct per-visit screenshot/thinking/prediction, action markers, input-image heatmaps without action markers, attention-row switching, zero denominators, all three grouping modes, retained selection after reload, and narrow/wide layout. Graph selection stayed on the same independent task page.

### Real-data acceptance: 2026-09-15

| Saved evaluation | Registered model | Tasks / episodes | Recorded actions | Original PNGs | Full-pass tasks | Mean score |
|---|---|---:|---:|---:|---:|---:|
| Old-v11 9B SFT: `eval50-a2-20260823` | `9b-full-r5@20f10` (`a2`) | 100 / 100 | 2,730 | 2,830 | 61 / 100 | 62.9010% |
| V16-only 9B SFT: `eval50-mixc9b-20260901` | `9b-full-mixc` (`mixc9b`) | 100 / 100 | 2,637 | 2,737 | 60 / 100 | 60.9030% |

Both runs exactly match the same frozen 100-task panel, with no missing or extra task IDs. Backfill reported zero errors. All 5,367 exported actions match the original action order, JSONL row, command, response and after-image filename. Every graph mode retains every action occurrence. All before/after references exist; the initial manifest references 5,767 original files, including 5,567 PNGs whose headers all report 1920×1080. The final-evaluation update additionally references the 200 original score files and 200 runtime logs. Mean scores above are recomputed from the original `result.txt` files, including partial credit.

Browser validation opened both real Bluetooth task pages, loaded original before/after images, switched between repeated visits on the same page, checked raw thinking/full prediction and enlarged screenshots with action markers. These historical runs have no recorded visual-signal sidecars; their attention panels correctly show unavailable. The previous synthetic preview address redirects to the real index.

Current runtime locations on **`osworld-windows` → WSL (`daniel_yan`)**:

- Original runs: `/mnt/d/research/OSWorld/results_generated/qwen35-9b-sft/`, followed by the run directory in the table.
- Panel: `/mnt/d/research/OSWorld/evaluation_examples/verified_eval100_nonproxy.json`; task configurations: `/mnt/d/research/OSWorld/evaluation_examples/examples`.
- Isolated viewer source: `/home/daniel_yan/cua-trajectory-tool-20260915`; all ten runtime files, including the new index template, were verified against local MD5 hashes after transfer.
- Configuration: `/home/daniel_yan/cua-trajectory-config.json`, with `results_root=/mnt/d/research/OSWorld/results_generated`, `source=osworld-windows / WSL` and the output directory below.
- Generated pages/index and acceptance JSON: `/home/daniel_yan/cua-trajectory-output` (`acceptance.json`, `import-a2.log`, `import-mixc9b.log`). Original screenshots remain in the results tree.
- Viewer: WSL loopback port 8793. Mac loopback port 8793 uses a dedicated background SSH forward to `osworld-windows` (see local access recovery above). Open `http://127.0.0.1:8793/index.html` while the viewer and tunnel are running.

The run parameters remain visible as recorded: `a2` used `image_max=20, fold_size=10`; `mixc9b` used `image_max=10, fold_size=1`. Both used `max_steps=50`. This import validates the viewer; it is not a controlled data-only comparison. Multiple actions from one model decision remain separate occurrences and may exceed 50 actions per task.

The WSL configuration also contains the original task-config directory and evaluator source path above. To regenerate the entire existing viewer on WSL:

```bash
python3 /home/daniel_yan/cua-trajectory-tool-20260915/sft/scripts/eval/after_task.py refresh \
  --config /home/daniel_yan/cua-trajectory-config.json
```

Source-backed final panels cover all 200 tasks. There are 26 `infeasible` terminal-marker checks and 5 non-infeasible `FAIL` early returns; all agree with their original recorded scores. All 6,167 referenced original files exist. Repeated unified generation is checked for identical output hashes; the acceptance JSON records the result.

### Teacher image10 import and navigation acceptance: 2026-09-15

The requested Qwen3.8-27B image10 eval100 is stored in two source batches under `/mnt/d/research/OSWorld/results_generated/qwen38-27b-local/`:

| Source run | Imported panel | Provider | Tasks | Actions | PNG files in task directories | Full-pass tasks |
|---|---|---|---:|---:|---:|---:|
| `eval50-t38i10-20260829` | `verified_eval50_nonproxy.json` | Docker | 50 | 980 | 1,030 | 40 |
| `osworld311-i10x-20260830` | `verified_eval50b_nonproxy.json` only, selected from the 311-task run | AWS | 50 | 989 | 1,039 | 36 |

The panels are disjoint and their union exactly equals `verified_eval100_nonproxy.json`. Both saved args record `image_max=10`, `fold_size=1`, `max_steps=50`, temperature 1 and served model `qwen38-27b-local`. The source groups remain separate in the index because they are different runs/providers. Selecting `27b-base@10f1` shows all 100 teacher tasks across both groups. This is not labelled as a single controlled run or as a locally SFT-trained model.

The first batch records the teacher checkpoint in `MODEL_BOUNDARY.json`. The AWS batch only has `args.json` and no checkpoint boundary file; its checkpoint stays unknown. Its registered display name is set explicitly in the host configuration, without changing the original run:

```json
"run_aliases": {
  "qwen38-27b-local/osworld311-i10x-20260830": "t38i10"
}
```

`render_task` applies that alias only to the exact relative run path, retaining the original args and recording `naming_source`. This mapping is for naming, not checkpoint verification.

Both batches were imported with the existing `render-run` command, their respective original panel, the shared host config and `--expected-tasks 50`; no evaluation was rerun. Logs are `import-teacher-i10-first50.log` and `import-teacher-i10-held50.log` in the output directory. Both report 50 rendered tasks and zero errors. All 1,969 exported actions match original row numbers, actions and responses; all before/after references exist and every graph mode retains every action. Of the 2,069 PNG files present, the trajectories reference 2,067: two additional `initial_state.png` files are not referenced by their saved trajectories and are not assigned to invented steps.

The index now contains **300 tasks across four source runs**, with **7,634 referenced PNGs and 8,534 total original-file references**, all present. Teacher acceptance is recorded in `acceptance.json` under `teacher_i10_import`. Browser checks loaded real teacher screenshots, confirmed the first/last navigation boundaries, exercised task 56 → 57 → 56, and restored the filtered index around scrollY 4,767 with the selected row at its prior viewport offset. Returning after viewing the next task selects that task's row instead of jumping to the top.

### MixB and history-compression eval100 imports: 2026-09-15

Two additional completed runs were imported using the existing `render_run` / `render-run` pipeline, the shared host config, `verified_eval100_nonproxy.json`, the original task configs and `expected_tasks=100`. Original results and screenshots remain under `/mnt/d/research/OSWorld/results_generated/qwen35-9b-sft/`.

| Source run | Registered model | Data | Tasks | Recorded actions | Original PNGs | Full-pass tasks | Mean score |
|---|---|---|---:|---:|---:|---:|---:|
| `eval50-mixb9b-20260901` | `9b-full-mixb` | v11 new batch + v16 | 100 | 2,448 | 2,548 | 60 | 61.7404% |
| `eval50-histcomp-20260904` | `9b-full-mixbtf-histcomp` | mixB + terminal normalization, with graduated history-image resolution | 100 | 2,276 | 2,376 | 60 | 60.9030% |

Both runs record Qwen3.5-9B full SFT, `image_max=10`, `fold_size=1` and `max_steps=50`. Their checkpoint boundaries identify `/gscratch/cse/jy050706/sft/models/mixB-9b-e873` and `/gscratch/cse/jy050706/sft/models/mixbtf9b-histcomp-e870`, respectively. Preserve partial-credit scores; the means above are computed from the original `result.txt` files.

The user's recalled `1 / 1/4 / 1/8` experiment is the single **histcomp** arm, whose actual schedule also includes a half-resolution stage:

| Image age (0 = newest) | Relative pixel / vision-token budget |
|---|---:|
| 0–1 | 1 |
| 2–4 | 1/2 |
| 5–7 | 1/4 |
| 8+ | 1/8 |

The training source `sft/training/histcomp/sitecustomize.py` and current WSL evaluation helper `/mnt/d/research/OSWorld/mm_agents/qwen/images.py` both define max-pixel budgets `2088960 / 1044480 / 522240 / 261120`. The saved histcomp `MODEL_BOUNDARY.json` records `OSTG_HISTCOMP=1` for rollout. These are budget ratios; actual resized image token counts can differ after grid rounding. The viewer retains the original environment screenshots and does not manufacture missing model-input captures.

Both import reports record 100 rendered tasks and zero errors. Run reports are `import-mixb9b.json` and `import-histcomp.json`; detailed checks are stored under `mixb9b_import` and `histcomp_import` in `acceptance.json`. The index now includes **500 tasks across six source runs**. Existing filtering, return-position restoration, task navigation and final evaluator panels are generated by the same templates; no special pages or new evaluation runs were created for these imports.

Current remaining scope: broaden and validate the selected layer/head/token coverage for the chosen research model, validate physical TP2 collection, and explicitly instrument any custom evaluator check that does not expose its intermediate values through the shared helpers/controller calls. The shared native hook, request/image correlation, sampled real attention, rich result retention and separate post-processing have been implemented. These are inference/evaluation measurements, not training modifications.

<!-- REPO NAV -->
[Repository map](../../README.md)
<!-- /REPO NAV -->
