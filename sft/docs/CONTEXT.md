# Model context and trajectory records

Updated for repository layout on 2026-09-14. This is the maintained entry contract; exact runtime templates and processor behavior must be checked at the checkpoint/harness version being used.

- One training sample is a step prefix with the final assistant response as its target; a whole trajectory is not an interchangeable training row.
- One model response may generate several executed actions. Preserve every action but count the parent model decision and its thinking once.
- Preserve source run/task/episode/step identity. The [trajectory reader](../data/traj.py) intentionally selects the last episode for its training use; raw inspection must retain earlier episodes and intermediate action screenshots when needed.
- Keep actual request-image order and history folding. The configured image maximum is not the number of images in every request.
- Keep model-produced coordinates separate from the executed coordinate conversion. A screenshot after an action is not automatically the screenshot used to generate that action.
- Preserve raw reasoning/content and token-count provenance; reconstructed token sequences and character-based estimates are not original sampled IDs.

The [builder](../data/build.py) reuses the external OSWorld Qwen context/image/prompt code. [sft/docs/SFT_DATA.md](SFT_DATA.md) and the versioned [data pipeline](DATA_PIPELINE.md) record the existing data rules. The [naming contract](../../docs/NAMING.md) defines configuration labels; live args determine what actually ran.

The complete earlier campaign-specific anatomy is preserved in [SFT_CONTEXT_20260813.md](../../outdated/docs/SFT_CONTEXT_20260813.md). Its default values are historical. The raw inspection feature is specified separately in the [current plan](../plans/PLAN-20260914-visual-signal-monitoring.md).

<!-- REPO NAV -->
[Repository map](../../README.md)
<!-- /REPO NAV -->
