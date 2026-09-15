# CUA Inspection Pipeline — Minimum Working Version

Updated: 2026-09-15 (handoff; implementation scope unchanged). **Plan only; implementation has not started.**

## 0. Checkout note for the implementing agent

This plan-only branch is based on GitHub `main` at `b7b91013a6`. The Mac's local `reorg-20260909` branch and subsequent uncommitted directory reorganization are not included. Paths in this plan describe that intended layout; first inspect the checkout you actually have.

| Reference | Available on this branch / required source |
|---|---|
| `docs/OPS.md`, `docs/NAMING.md` | The main checkout has [OPS.md](../../OPS.md) and an older [NAMING.md](../../NAMING.md) at the repository root. The updated naming specification remains in the Mac checkout. |
| `sft/data/traj.py` | Existing helper is [sft/traj.py](../traj.py). |
| `sft/armname.py` | Existing generator is in the Mac checkout; it is not in this plan-only branch. Obtain it together with its matching naming specification before integrating canonical names; do not create a replacement registry. |
| Existing report viewer | `computeragent/cua-experiment-report/site/` is a separate sibling project on the Mac, outside this Git repository. Obtain that source before extending the viewer; do not silently build a duplicate. |
| `sft/analysis/visual_signals.py` | Proposed new entry point, not an existing implementation. |

The source handoff for the naming generator and viewer is a prerequisite for the complete pipeline, not evidence that those files are already deployed. Keep screenshots and saved results in Windows/WSL. Verify live harness files there before any logging changes. This document does not authorize launching training/evaluation jobs or deploying a website.

## 1. Implementation rule

**Build the smallest end-to-end tool that works. Reuse existing code and files; add a feature only when a concrete missing field or inspection need requires it.** This is the user's explicit preference for this project and applies to later implementation as well.

The tool displays original trajectories and visual-signal data. It generates no LLM summaries, explanations, failure diagnoses, judgments or improvement suggestions. Original CUA reasoning is source data and remains visible unchanged.

## 2. The whole pipeline

```text
Existing Windows/WSL result folders
    -> one small export script
    -> generated index + existing viewer
    -> click action -> screenshots, raw response and available visual signals
```

Use one `CUA/sft/analysis/visual_signals.py` entry point and extend the existing viewer. Read existing result folders directly. Screenshots stay in their existing directories on the Windows machines (including WSL); the tool references them without relocation. Storage and remote-hosting design are deferred. Running the exporter again updates the generated files. Initially run it manually on saved results; an existing evaluation-completion hook can call the same command later.

The first milestone is one usable experiment viewer. The next is a simple index listing multiple runs. Neither needs a model call, a new benchmark run, or manual correct-history labels.

## 3. Reuse naming and metadata

- Use the existing `sft/armname.py` and its matching `docs/NAMING.md` (source handoff described above) for model/corpus labels and legacy aliases. Do not create another naming registry or parser.
- Read model/checkpoint, corpus, dataset-version and evaluation settings from existing `args.json`, `MODEL_BOUNDARY.json` and version files where present. Keep absent values unknown; do not invent metadata.
- Keep each existing source/result-directory combination as a separate run. A source label plus relative run path is sufficient for the first viewer; do not merge runs because their canonical model names match.
- Keep original task/episode/model-step/action indices. An action selection includes its source/run as well as task and step.
- Use existing checkpoint/data version identifiers; do not build a new version registry, hash all training weights, generate UUID infrastructure or rename old directories.

For example, the existing generator resolves `mixbtf9b` to `9b-full-mixbtf`, and corpus `mixbtf` to `v11n+v16.tf`. Those labels help navigation; the original run path and recorded configuration identify the result being viewed.

The generated index needs only canonical/legacy name, checkpoint, corpus/version when available, evaluation settings/date/outcome, source path and viewer link. One small generated JSON file is enough. The viewer may load task-level files separately if they are already available. No manually maintained duplicate catalog is needed.

## 4. One connected viewer

| Part | Minimum behavior |
|---|---|
| Action graph | An ordered node per recorded action; group by recorded app where known. Click a node to select that occurrence. Unknown apps stay unknown. |
| Action pictures | Before/after screenshots with existing click/drag markers or literal type/key/wait/termination labels. Preserve original image files. |
| Raw trajectory | Original command, model response/thinking, timestamp, tool reply and recorded evaluator result. |
| Visual-signal panel | Actual request-image heatmap, history-image thumbnails, original attention weights, token probabilities/counts and defined numerical fields, where available. |
| Navigation | Previous/next action, select a retained-history image, select an available layer/head/query, and open raw data. |
| Experiment index | A generated list of existing runs; selecting one opens its viewer. |

Reuse `trace_catalog`, `trace_steps`, screenshots and marker rendering from the existing report builder at `computeragent/cua-experiment-report/site/src/content/dashboard/research_content.py` (sibling project outside CUA). Add the graph and signal panel to that viewer, not a second viewer. Keep the existing styling and language controls.

Use literal parsed actions; do not call another model to label a click as Save or infer app/intent. Optional repeated-action counts must link to the actual occurrences and state the counting rule; no interpretation is generated.

## 5. Alignment rules that cannot be simplified away

- Preserve episode boundaries and every executed action. [sft/traj.py](../traj.py) (reorganized path: `sft/data/traj.py`) has useful helpers, but `load_steps` retains only the last episode and last screenshot per model step; use raw action rows when those losses matter.
- One model response can contain several actions. Show separate action nodes, but count thinking/token cost once for their parent model decision.
- An action's before-image can differ from the image originally sent to the model earlier in that response. The action panel shows execution screenshots; the signal panel shows actual model-input images. Never put attention on a screen the model had not received.
- Match signals to their source run, checkpoint, input, decision and image occurrence using available metadata. If the match cannot be established, show unavailable/unverified rather than attaching another result.
- Apply the existing coordinate conversion once. Do not guess missing click locations or put the current click onto an old history frame.

## 6. Signals: preserve data and show the definition

For a fixed attention layer/head/query, keep the original weights and image-token mapping:

- `frame_mass[j] = sum(attention weights belonging to image j)`.
- `image_mass = sum(frame_mass)`.
- `frame_share[j] = frame_mass[j] / image_mass` is optional image-only normalization.
- Show image-token counts and optional mean weight per token separately; differently sized pictures remain distinguishable.

The original model weights are already normalized across visible keys. Do not apply another softmax. Keep total image mass visible so an image-only percentage does not hide a small original weight. Flag undefined denominators. Individual layer/head/query values remain accessible when a plot uses an aggregate.

Use actual request images and available processor counts, not the configured maximum as an observed count. Preserve exact versus reconstructed versus estimated token-count labels; the existing `chars / 3.5` thinking estimate may be displayed as an estimate. Top-k logprobs are not full-vocabulary entropy. Spatial entropy and output-token entropy are different quantities and must be named accordingly.

The build and viewer read existing signal files only. Missing signals do not prevent trajectory viewing. Obtaining new attention requires an explicitly separate measurement of the evaluated model with fixed weights; it is not an LLM analyst and is not triggered by opening the page. Save selected query rows rather than full long-context S-by-S matrices, preserve the collected dtype/coverage, and verify replay alignment before calling it original-run data.

## 7. Only patch missing logging after the viewer works

First inspect live WSL code and existing records; the Mac OSWorld copy is old. See [CLAUDE.root.md](../../CLAUDE.root.md) and [OPS.md](../../OPS.md) (reorganized path: `docs/OPS.md`). If needed, limit the initial collection change to the existing client, agent and runner:

| Existing file | Missing information it may need to preserve |
|---|---|
| `mm_agents/qwen/client.py` | Original API response and supported logprobs before text conversion |
| `mm_agents/qwen/main.py` | Actual request, image/source-step order and parent decision metadata |
| `lib_run_single.py` | One saved record per model call, linked to existing action/observation records |

Use fewer changes where the records already exist. One optional recording flag, off by default, is sufficient. Preserve prompts, sampling, history, image processing, retries, return values, parsing, actions and evaluator behavior. Logging failure must not trigger another generation/action or change termination. Do not save credentials.

Training changes, automated source-selection/perturbation experiments, LLM-based analysis and automatic deployments are outside this tool.

## 8. Finish criteria

1. One saved run produces an action graph; clicking a node opens the correct original pictures and response.
2. Available signal files appear for that same decision/image/query; unavailable files are explicit.
3. Adding a second result folder and rebuilding adds a separate index entry using existing canonical naming.
4. Rebuilding references the existing Windows/WSL screenshots without moving or modifying them.
5. A few existing fixtures verify multi-action alignment, separate runs with the same name, unknown app context, image scaling and missing signals. Reuse existing checks or one small self-check; do not add a test framework.

Stop expanding the design once these work. Add infrastructure only when a measured limitation prevents a requested inspection task.

## 9. Current status

The repository check on 2026-09-14 found remote `main` (no `master`). Fetch/pull returned `Already up to date`; local `reorg-20260909` was 11 commits ahead and 0 behind. This does not verify the running WSL/serving versions.

Storage-design content has been removed at the user's request; screenshots remain on the Windows machines for now. Only the plan changed in this update; no code or image files were moved or modified.

<!-- REPO NAV -->
[Repository map](../../README.md)
<!-- /REPO NAV -->
