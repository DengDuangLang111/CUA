# Model context and trajectory records

Updated for repository layout on 2026-09-14. This is the maintained entry contract; exact runtime templates and processor behavior must be checked at the checkpoint/harness version being used.

- One training sample is a step prefix with the final assistant response as its target; a whole trajectory is not an interchangeable training row.
- One model response may generate several executed actions. Preserve every action but count the parent model decision and its thinking once.
- Preserve source run/task/episode/step identity. The [trajectory reader](../data/traj.py) intentionally selects the last episode for its training use; raw inspection must retain earlier episodes and intermediate action screenshots when needed.
- Keep actual request-image order and history folding. The configured image maximum is not the number of images in every request.
- Keep model-produced coordinates separate from the executed coordinate conversion. A screenshot after an action is not automatically the screenshot used to generate that action.
- Preserve raw reasoning/content and token-count provenance; reconstructed token sequences and character-based estimates are not original sampled IDs.

The [builder](../data/build.py) reuses the external OSWorld Qwen context/image/prompt code. [sft/docs/SFT_DATA.md](SFT_DATA.md) and the versioned [data pipeline](DATA_PIPELINE.md) record the existing data rules. The [naming contract](../../docs/NAMING.md) defines configuration labels; live args determine what actually ran.

The raw inspection feature is specified separately in the [current plan](../plans/PLAN-20260914-visual-signal-monitoring.md).

## Request layout for step k

Read from `mm_agents/qwen/{main,history,images,prompts}.py` (OSWorld `091f5ef1` plus local changes) and checked against live payload dumps on 2026-08-13. The builder imports this code; the strings below are for reading payloads, not for retyping.

- `system`: the system prompt containing the XML tools definition, rebuilt each step from the processed image size.
- First `user` turn: screenshot 1, then the instruction prompt from `prompts.build_instruction_prompt` (`Please generate the next move according to the UI screenshot, instruction and previous actions.`, `Instruction: {task}`, `Previous actions:`).
- Every later `user` turn: one screenshot wrapped by `history.wrap_tool_response` as `"<tool_response>\n"` + image + `"\n</tool_response>"`.
- Every `assistant` turn: the stored response verbatim, `<think>` included. The context for step k ends with the user turn carrying screenshot k; the response to it is the target.

| knob | meaning | 2026-08-13 campaign value (historical; read the live args) |
|---|---|---|
| `history_n` | Past steps kept as turns. "Previous actions" holds a prose action list only from `total_steps >= history_n + 2`; below that it reads `None`. | 100; the list never appeared at `max_steps 50` (100/100 cached payloads read `None`, checked 2026-08-19) |
| `image_max` | Upper bound on screenshots kept as images. | 20 |
| `fold_size` | When the screenshot count exceeds `image_max`, the oldest `fold_size` screenshots are replaced inside their tool_response by the text `This screenshot has been collapsed.` | 10, the argparse default; [RESULTS.md](RESULTS.md) §5.19 requires `--fold-size 1` when building corpora |

Folding depends on the target step. With 20/10, screenshots 1–10 are collapsed when building step 25 and are still images when building step 15, and the visible count moves between 11 and 20 (mean 15.7, RESULTS.md §5.19). This is why a packed trajectory is not equivalent to per-step samples: only episodes of at most `image_max` steps are prefix-stable. On the v11 corpus (39 successful trajectories, median 21 steps), full packing would cut image encodings 12.9× (12,236 → 946 per epoch), but packing only the 19 lossless episodes saves 1.1×.

Images and coordinates:

- `process_image` applies `smart_resize(factor=32, max_pixels≈13.1M)`: 1920×1080 becomes 1920×1088, no real downscale. A late-step sample with 20 such images (~2.6k visual tokens each) is about 50k+ tokens. To shrink it, lower `image_max` in the rollout config; changing it only in the builder creates a train/inference mismatch.
- The model emits relative 0–999 coordinates; `adjust_coordinates` maps them to pixels as `x·W/999, y·H/999`. The training label is `response`, never the scaled `action`.

Thinking in history:

- The eval server runs `--reasoning-parser qwen3`, so `content` arrives without think. `client.py:merge_reasoning_content` splices `reasoning_content` back as `<think>…</think>\n\n`, and `main.py` stores that as `response`. When this splice failed once, the trajectories had no think at all (official-361 run: 7,906 steps, 0 `<think>`). Serve flags: [OPS.md](../../docs/OPS.md) §4; template reading: [RUNBOOK.md](../../taskgen/docs/RUNBOOK.md) "Qwen3.8's chat template, read at source".
- The client never strips history `<think>`; `ensure_empty_think_prefix` only adds an empty block when one is missing. The template keeps history think only because every non-first user turn satisfies `content.startswith("<tool_response>") and content.endswith("</tool_response>")`, which pins `last_query_index` at 1 ([SFT_DATA.md](SFT_DATA.md) rule 3.2). One extra character in the wrapper drops all history think with no warning (2026-08-19: prompt 61,850 → 7,132 tokens). The template also drops an empty think block whole, so a failed splice shrinks the context silently. Read RESULTS.md §5.7 before changing `wrap_tool_response` or the observation format.
- Eval-side `preserve_thinking`/`enable_thinking` do not change rendering (the deployed jinja contains neither variable, RESULTS.md §5.7). The ms-swift training flag `--preserve_thinking` is a separate setting: it controls whether swift's own encoder (`template/base.py:1254-1266`) strips history think.

<!-- REPO NAV -->
[Repository map](../../README.md)
<!-- /REPO NAV -->
