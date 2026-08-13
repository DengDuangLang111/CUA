# Building SFT data from rollout trajectories

Every rule here was verified against the v11 run (100 trajectories) or the
runner source on 2026-08-13 — the "receipt" column says how. Encode them in
`sft_check.py`; do not rebuild them from memory.

The unit of data: one sample = (rendered context, step-k response). The
response is trained verbatim — thinking, tool_call syntax, coordinates as the
model wrote them.

**The on-disk format is deliberately left as the runner writes it** — one
line per pyautogui action, so a multi-action step spans several lines with
the same `step_num` and a byte-identical `response`. This is lossless
(aggregation reconstructs steps exactly; verified 200/200 groups identical),
and changing the writer mid-campaign would break the trajectory viewer, the
dashboard daemon, and comparability with v11 data. All correction happens in
the builder, governed by the rules below.

## 1 Reconstructing steps from traj.jsonl

| rule | receipt |
|---|---|
| **One line ≠ one step.** The runner writes one line per pyautogui action; a multi-action response repeats the same `step_num` with an identical `response`. Aggregate by `step_num`: one sample per step. | v11: 3770 lines / 3470 steps (8.6% inflation); all 200 multi-action groups byte-identical in `response`, 0 diverged |
| **The observation for step k is step k−1's LAST screenshot.** `screenshot_file` on a row is taken AFTER that action executes. With multi-action steps, take the final row's screenshot of the previous step — `setdefault`/first-row pairing is systematically wrong. | runner source: `obs` overwritten per action inside the step loop |
| **Step 1's observation is `initial_state.png`.** Runs before 2026-08-13 never saved it (patched since, copied from the `_human` variant). For older runs, drop step-1 samples — do NOT extract from recording.mp4: `start_recording()` fires after `_get_obs()`, so the first frame is not the step-1 observation. | source lines 27 vs 30; v11: 39 passed trajs lack it |
| **Take only the last episode in a file.** `traj.jsonl` opens in append mode: a healed/re-run task stacks episodes; cut where `step_num` resets. | mode `"a"` in source; v11 incidence: 0/100 — guard is cheap, keep it |

## 2 Filtering steps and trajectories

| rule | receipt |
|---|---|
| **Keep only `score == 1.0` exactly.** `conj:"and"` can emit partial scores. | v11 held only 0.0/1.0 — defensive, zero cost |
| **Drop hallucination steps everywhere, not just trailing.** A step whose `response` calls an undeclared action (`answer`, `screenshot`) trains the model to hallucinate — the executed WAIT is not what the label says. They are NOT all trailing: 7 v11 tasks had real actions after one, including 2 PASSED trajectories (writer/16118294, vs_code/14d0a2c2). Detect with `<parameter=action>\nanswer` (newline inside the tag — adjacency-assuming grep finds nothing). Since 2026-08-13 `actions.py` logs `unhandled action` warnings, so runtime.log lists them. | byte-level scan 2026-08-13 |
| **Truncate degenerate tails.** Passing trajectories can end in a loop the evaluator never sees (43× Ctrl+S, 43× WAIT hit the v11 cap and still scored 1.0). The WAIT breaker (≥10) bounds WAIT tails in new runs; click/key tails still need the truncation pass. | v11: 4 cap-hitting passes, tails confirmed junk |
| **Cap-hitting passes need review even after truncation** — mid-episode flailing (opened wrong menus, recovered) is a judgment call: robustness data vs noise. Current default: keep recovery sequences, cut pure oscillation. | v11 inspection |

## 3 Rendering the training context

| rule | receipt |
|---|---|
| **Labels come from `response`, never from `action`.** The model emits relative 0–999 coordinates; `action` holds pyautogui code already scaled to 1920×1080 (`[180,257]` → `doubleClick(345,277)`). Training on `action` shifts the coordinate distribution ~2×. | cross-checked v11 rows |
| **History must be rendered by the model's own chat template with the same kwargs the campaign sent.** The client does NOT strip thinking (`ensure_empty_think_prefix` only prepends an empty block when missing) and under `nopreserve` it sends `chat_template_kwargs={"enable_thinking": true}` — no `preserve_thinking` key at all. The template (chat_template.jinja, 7764 B) then strips `<think>` from every assistant turn at or before the last user query: `{%- if (preserve_thinking is defined and preserve_thinking is true) or (loop.index0 > ns.last_query_index) %}` keeps thinking, else drops it. So: render history through `apply_chat_template` with the campaign's kwargs — hand-stripping in the builder duplicates template logic and WILL drift. | template read from Tillicum model dir 2026-08-13; client code `mm_agents/qwen/main.py:278-284`, `history.py:90-94` |
| The current step's target keeps its full `<think>` block — that is what the model emitted under `enable_thinking` and what generation-time distribution looks like. | — |

## 4 Final verification before training (pending)

After the campaign: replay ONE task offline with a client patched to dump
the exact `messages` payload it sends, and byte-diff that against the
builder's rendering of the same history. This upgrades rule 3.2 from
"derived from the template source" to "measured end to end". Not done during
the campaign because each step's payload embeds base64 screenshots — dumping
all of them would exhaust the disk for no extra signal.

## 5 Provenance to record per sample

run id (`v11-500-ms100-think-nopreserve-20260813`), task slug + id, step_num,
screen size (1920×1080), coordinate convention (`relative 0–999`), template
kwargs used for rendering, and whether the trajectory was truncated/filtered
and why. A sample that cannot answer "which run, which step, what did the
model actually see" is not auditable.
