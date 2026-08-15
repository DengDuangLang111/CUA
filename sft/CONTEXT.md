# What the agent actually saw — context anatomy for SFT

Read from `mm_agents/qwen/{main,history,images,prompts}.py` (WSL OSWorld,
`091f5ef1` + local mods) and cross-checked against live payload dumps on
2026-08-13. Training samples must reproduce THIS, not a guessed format —
every deviation is train/inference mismatch.

## 1 Message anatomy for step k

```
system     : system prompt embedding the XML tools definition
             (rebuilt each step from processed image W×H — constant in practice)
user  (1)  : [screenshot_1] + "\nPlease generate the next move according to the
             UI screenshot, instruction and previous actions.\n\n
             Instruction: {task}\n\nPrevious actions:\nNone"
assistant  : response_1  (verbatim, <think> included — see §4)
user  (j)  : "<tool_response>\n" [screenshot_j] "\n</tool_response>"
assistant  : response_j
...
user  (k)  : "<tool_response>\n" [screenshot_k] "\n</tool_response>"
             → the model generates response_k; that is the training target
```

Wrapper strings are exact (`history.wrap_tool_response`,
`prompts.build_instruction_prompt`); replicate byte-for-byte.

## 2 Campaign knob values (runner defaults, none overridden)

| knob | value | consequence |
|---|---|---|
| `history_n` | 100 | `start_step` is always 1 at ms100 — history never truncates, "Previous actions" is always `None` |
| `image_max` | 20 | at most 20 real screenshots in context |
| `fold_size` | 10 | past 20 screenshots, the oldest 10 (then 20, 30…) collapse to the text `This screenshot has been collapsed.` inside their tool_response — the images drop out |

**Folding is step-dependent.** At step 25, screenshots 1–10 are collapsed; at
step 15 they were not. The same historical turn renders differently depending
on which step you are building — see §6.

## 3 Images and coordinates

- `process_image`: `smart_resize(factor=32, max_pixels≈13.1M)` — 1920×1080
  only rounds to **1920×1088**, no real downscale
- the model emits **relative 0–999** coordinates; `adjust_coordinates` maps to
  original pixels as `x·W/999, y·H/999` — the `response` field is the training
  label, never the scaled `action`

## 4 Thinking

- the client NEVER strips `<think>` from history (`ensure_empty_think_prefix`
  only prepends an empty block when one is missing)
- the campaign sends `chat_template_kwargs={"enable_thinking": true}` — **no
  `preserve_thinking` key** — and the server template strips `<think>` from
  every assistant turn at/before the last user message (verified in
  `chat_template.jinja` on the serving node)
- ⇒ render history through the model's own chat template with the same
  kwargs; keep the full `<think>` only on the final (target) turn

## 5 Free verification source

Every step the client dumps its payload — **text verbatim, image base64
truncated** — to `OSWorld/draft/message_cache/qwen_messages_step_{i}.json`.
The directory is shared by all concurrent envs and keyed only by step index,
so files overwrite each other: it is a rolling sample of real payloads, not a
per-task archive. Sufficient to byte-diff the builder's rendering; not
sufficient to reconstruct a specific task's context.

## 6 Consequences for the builder

1. **One sample per step, loss on the final assistant turn only.** The
   context for step k is turns 1..k rendered with the folding state *as of
   step k*.
2. **Packing a whole trajectory into one multi-turn sample and training all
   assistant turns is NOT equivalent.** As originally written this had two
   legs; one fell on 2026-08-14 and the other got numbers.
   ~~(a) history turns must lose their `<think>` while every target needs its
   own kept~~ — **premise wrong**: history turns KEEP their think everywhere we
   have since measured (teacher rollout: our own message dumps show 49/49
   replayed turns with real think, RUNBOOK; training render: swift runs with
   `--preserve_thinking true`). With think kept on both sides, a packed
   sequence would present each turn identically to its per-turn sample.
   (b) **folding rewrites past turns' content as the step index advances** —
   still true and now the sole, sufficient reason. At step k>20 old screenshots
   are collapsed to text; in a packed sequence they would sit there as real
   images. Only episodes ≤ `image_max` steps are prefix-stable and packable
   losslessly.
   **And the measurement kills the idea anyway** (v11 corpus, 39 successful
   trajectories, median 21 steps): full packing would cut image encodings
   12.9× (12,236 → 946 per epoch) but is only lossless for the 19 episodes
   ≤ 20 steps — and packing just those saves **1.1×**, because per-turn cost
   is dominated by exactly the long episodes that folding makes unpackable.
   The benefit lives only where the equivalence fails. Rejection stands.
3. **Cost of exactness**: a late-step sample carries up to 20 images at
   1920×1088 (~2.6k visual tokens each) ≈ 50k+ tokens. Per-step samples also
   re-pay the shared prefix. If this dominates training cost, the lever is a
   smaller `image_max` — but that is a ROLLOUT config change for the next
   campaign, never a builder-side shortcut (changing it only in training
   reintroduces the mismatch this document exists to prevent).
