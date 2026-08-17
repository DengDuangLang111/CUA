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
| **The initial observation is history for EVERY sample, not just step 1's input.** Step k's context contains screenshot 1 = `initial_state.png`; without it the whole trajectory is unbuildable. New runs save it (patched 2026-08-13). For older runs `--initial-fallback mp4` takes recording frame 0 — between `_get_obs()` and `start_recording()` nothing touches the VM, so the gap is ambient-only; the approximation is flagged in `meta.initial_from`. Needs ffmpeg; degrades to dropping the trajectory when absent. | builder test on v11: 0 samples buildable without it (75/75 steps dropped) |
| **Take only the last episode in a file.** `traj.jsonl` opens in append mode: a healed/re-run task stacks episodes. Boundary = step_num decrease OR same step_num with a changed `response` (multi-action lines are byte-identical, so a changed response at the same number is a restart). | mode `"a"` in source; the second signal exists because the smoke test caught a single-step re-run being merged into its successor |

## 2 Filtering steps and trajectories

| rule | receipt |
|---|---|
| **Keep only `score == 1.0` exactly.** `conj:"and"` can emit partial scores. | v11 held only 0.0/1.0 — defensive, zero cost |
| **Drop hallucination steps everywhere, not just trailing.** A step whose `response` calls an undeclared action (`answer`, `screenshot`) trains the model to hallucinate — the executed WAIT is not what the label says. They are NOT all trailing: 7 v11 tasks had real actions after one, including 2 PASSED trajectories (writer/16118294, vs_code/14d0a2c2). Detect with `<parameter=action>\nanswer` (newline inside the tag — adjacency-assuming grep finds nothing). Since 2026-08-13 `actions.py` logs `unhandled action` warnings, so runtime.log lists them. | byte-level scan 2026-08-13 |
| **Truncate degenerate tails.** Passing trajectories can end in a loop the evaluator never sees (43× Ctrl+S, 43× WAIT hit the v11 cap and still scored 1.0). The WAIT breaker (≥10) bounds WAIT tails in new runs; click/key tails still need the truncation pass. | v11: 4 cap-hitting passes, tails confirmed junk |
| **Cap-hitting passes need review even after truncation** — mid-episode flailing (opened wrong menus, recovered) is a judgment call: robustness data vs noise. Current default: keep recovery sequences, cut pure oscillation. | v11 inspection |

## 3 Rendering the training context

The full context anatomy — message layout, folding, wrapper strings,
knob values — lives in [sft/CONTEXT.md](sft/CONTEXT.md); it is the
builder's specification. The rules below are the summary.

| rule | receipt |
|---|---|
| **Labels come from `response`, never from `action`.** The model emits relative 0–999 coordinates; `action` holds pyautogui code already scaled to 1920×1080 (`[180,257]` → `doubleClick(345,277)`). Training on `action` shifts the coordinate distribution ~2×. | cross-checked v11 rows |
| **History must be rendered by the model's own chat template with the same kwargs the campaign sent.** The client does NOT strip thinking (`ensure_empty_think_prefix` only prepends an empty block when missing) and under `nopreserve` it sends `chat_template_kwargs={"enable_thinking": true}` — no `preserve_thinking` key at all. The template (chat_template.jinja, 7764 B) then strips `<think>` from every assistant turn at or before the last user query: `{%- if (preserve_thinking is defined and preserve_thinking is true) or (loop.index0 > ns.last_query_index) %}` keeps thinking, else drops it. So: render history through `apply_chat_template` with the campaign's kwargs — hand-stripping in the builder duplicates template logic and WILL drift. | template read from Tillicum model dir 2026-08-13; client code `mm_agents/qwen/main.py:278-284`, `history.py:90-94` |
| The current step's target keeps its full `<think>` block — that is what the model emitted under `enable_thinking` and what generation-time distribution looks like. | — |

## 4 The builder (test version, 2026-08-13)

`ostg/sft/traj.py` (rules 1–2) + `ostg/sft/build.py` (rule 3):

```
PYTHONPATH=.:/mnt/d/research/OSWorld python -m ostg.sft.build RESULT_DIR \
    --tasks TASKS_DIR --out OUT [--limit N] [--tail-run 5] [--initial-fallback mp4]
```

Emits `samples.jsonl` (messages ending at step k's user turn; `response` =
verbatim target; `meta` = provenance), `images/` (screenshots re-encoded with
the agent's own `process_image`, so disk pixels = seen pixels), and
`report.json` (kept/dropped counts per rule — the audit trail).

Design points worth keeping when this graduates from test version:

- **The message structure is assembled by the agent's own code** —
  `build_messages`, the tools def, the system prompt, `update_folding_state`
  imported from `mm_agents.qwen` — so it cannot drift from the rollout.
  Verified against live `message_cache` payloads: system text, tool_response
  wrappers, and turn shape identical.
- **Hallucinated steps are dropped as TARGETS but kept in HISTORY**: the
  model really saw them in its context, so removing them from history would
  itself be a train/inference mismatch.
- Collapsed screenshots are never copied (lazy image writing).

First real output: 3 passed ms100 tasks → 43 samples, 14 MB images.

**Dialect (decided 2026-08-14): ms-swift, student Qwen3.5-4B** (natively
multimodal; inference stays on our harness, so relative-0–999 coordinates
carry over). `ostg/sft/export.py` reshapes samples.jsonl into swift's
messages+images JSONL next to the images dir; 43/43 converted, one `<image>`
marker per path, order-aligned. Qwen3.5-4B's chat template was fetched and
checked: it strips history `<think>` by the same last-query rule as the
teacher's serving template and has no preserve_thinking kwarg — the student's
default rendering equals the teacher's rollout distribution. Train with loss
on the final round only; verify the exact ms-swift flag at install time.

## 5 Final verification before training

No replay needed — the client already dumps every step's payload (text
verbatim, image base64 truncated) to
`OSWorld/draft/message_cache/qwen_messages_step_{i}.json` (see
[sft/CONTEXT.md](sft/CONTEXT.md) §5). Byte-diff the builder's rendered text
against a handful of those dumps and rule 3.2 is measured, not derived. The
dir is shared across envs and keyed by step index only, so treat it as a
rolling sample, not an archive.

## 6 Provenance to record per sample

run id (`v11-500-ms100-think-nopreserve-20260813`), task slug + id, step_num,
screen size (1920×1080), coordinate convention (`relative 0–999`), template
kwargs used for rendering, and whether the trajectory was truncated/filtered
and why. A sample that cannot answer "which run, which step, what did the
model actually see" is not auditable.

## B 语料 target-token 分布 vs OpenWebRL(2026-08-17,tokenizer 对齐实测)

同一把 Qwen3.5 tokenizer 重算双方(他们的 1.71GB 原始 jsonl 拉到 Tillicum
重数;卡片 max 1,324 vs 我们数出 1,325,口径可比成立)。

| | B 语料 | OpenWebRL 0.4K |
|---|---:|---:|
| N / 总 target | 5,659 / 1,809,926 | 3,085 / 1,030,942 |
| p50 / p90 / p99 / max | 146 / 675 / 2,770 / **9,712** | 314 / 469 / 773 / **1,325** |
| top-1% / 5% token 份额 | **13.4% / 33.5%** | 2.7% / 10.4% |
| >2048 样本/token | 1.7% / **18.3%** | 0 / 0 |
| >4096 | 28 个 / 8.2% | 0 |
| think 占比 | 68.7% | **0%(无 think 标签,推理裸文本 85.7%)** |
| action 占比(≤512 → >4096) | 29.8% → **2.3%** | 11.4%(无长桶) |

判决:双峰分布——典型步比他们短一半,尾巴重一个量级;action 随长度
崩塌 = 超长样本几乎纯教推理不教动手。**待办**:① 审计 28 个 >4k 样本
(固化为 census 长度分层报告);② 核实 swift loss 分母(token 级 vs
样本级,决定尾巴权重 60× 还是 1×);③ 清尾消融四臂(token 配平)见
IDEAS.md。在飞三臂不动。原始文件:Tillicum tmp_owrl/(审计后可删)。
