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
| `history_n` | 100 | `start_step` is always 1 — history never truncates, "Previous actions" is always `None`. Measured activation threshold: the prose action list first appears at `total_steps >= history_n + 2` = 102, so at `max_steps 50` it never does (verified 2026-08-19 across all 100 cached payloads: `{'None': 100}`) |
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
  `preserve_thinking` key** — and **on this harness's message shape the server
  template does NOT strip history `<think>`**. The template's last-query rule
  (`loop.index0 > ns.last_query_index`) would strip it, but the backward scan
  that computes `last_query_index` skips user turns wrapped in
  `<tool_response>`, and `history.py:27-32,55-72` wraps every non-first user
  turn — so the index is pinned at 1 and the keep branch fires for every
  historical assistant turn. On generic multi-turn chat the same template DOES
  strip: that is a real measurement taken on hand-made messages, and it is what
  the old version of this bullet reported as if it applied to us.
- ⇒ render history through the model's own chat template with the same kwargs
  (never hand-strip — that duplicates template logic and WILL drift); the full
  `<think>` survives on history turns AND on the target turn
- **evaluation-side `preserve_thinking`/`enable_thinking` are no-ops** (the
  jinja has no such variable); the identically-named **training-side** ms-swift
  flag is real and does strip history think in swift's own encoder
  (`template/base.py:1254-1266`). Same name, different layer — see
  `sft/RESULTS.md` §5.7

- **the server strips think before we ever see it** — the eval server runs
  `--reasoning-parser qwen3`, so `content` arrives WITHOUT think;
  `client.py:merge_reasoning_content` splices `reasoning_content` back into
  `<think>…</think>\n\n` and `main.py:183` stores THAT verbatim. 786/786
  responses of the running eval match the splice format exactly. This bridge
  has failed once before (official-361: 7,906 steps, 0 `<think>`) — both
  directions of the field are explained in `RUNBOOK.md` "Qwen3.8's chat
  template, read at source"; serve-side flags live in `OPS.md` §4
- ⚠️ **this all hangs on two string boundaries.** The template keeps history
  think only because `content.startswith("<tool_response>") and
  content.endswith("</tool_response>")` holds for every non-first user turn.
  Append one stray character to the wrapper and 50 think blocks vanish, the
  prompt drops 88% (61,850 → 7,132 tokens), and **nothing warns you** — the
  failure is indistinguishable from normal operation. Also: an EMPTY think
  block is dropped whole by the template (`:68`), so a merge failure would
  shrink the context silently too. Before touching `wrap_tool_response`, the
  observation format, or anything that adds a prefix/suffix inside the
  wrapper, read `sft/RESULTS.md` §5.7

> Verified 2026-08-19 by three independent routes (live `/render` on the
> running eval server, offline `apply_chat_template` on two tokenizers, and a
> third pass that pulled the deployed jinja and the vllm launch command), each
> with its own sensitivity control. Numbers, probes and the deployed template
> excerpt: `sft/RESULTS.md` §5.7. The mechanism was first recorded there on
> 2026-08-18; THIS section was not updated then, and it misled two sessions on
> 2026-08-19 before the re-measurement.

## 5 Free verification source

Every step the client dumps its payload — **text verbatim, image base64
truncated** — to `OSWorld/draft/message_cache/qwen_messages_step_{i}.json`.
The directory is shared by all concurrent envs and keyed only by step index,
so files overwrite each other: it is a rolling sample of real payloads, not a
per-task archive. Sufficient to byte-diff the builder's rendering; not
sufficient to reconstruct a specific task's context.

Two traps when reading it (2026-08-19):
- **stale files from older runs sit next to live ones.** On 2026-08-19 the
  directory held 100 files of which only `step_0..49` were from the running
  eval; `step_50..99` were left over from a 2026-08-14 run. Always filter by
  mtime before aggregating, or you will mix two experiments.
- **adjacent `step_N` files come from different tasks** (3 env workers share
  the directory, keyed only by step index), so they cannot be read as one
  trajectory. For per-trajectory truth use `traj.jsonl` under `result_dir`.

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
