# ostg operations runbook

The standard commands for every step from generation to SFT data. Everything
executes on **WSL** (the Mac copy is for editing code); the *why* behind the
design and thresholds lives in [README.md](README.md) and EXPERIMENTS.md —
this file only records *how to run*.

Conventions (every command below assumes):

```bash
TG=/mnt/d/research/os-simple-taskgen-v8      # execution repo
OW=/mnt/d/research/OSWorld
P=$OW/.venv/bin/python
R=$OW/results_generated/qwen36-27b-bf16-local
cd $TG
```

Pipeline at a glance:

    gen (shardable) -> ship (re-emit + gates) -> [cull] -> merge
      -> control (3-lane) -> rollout -> traj_html -> analysis / SFT harvest

---

## 0 Sync code Mac → WSL

After committing in the Mac-side repo:

```bash
git bundle create /tmp/ostg.bundle <last-synced-commit>..v9
cat /tmp/ostg.bundle | ssh osworld-windows 'wsl -e bash -lc "cat > /tmp/ostg.bundle && cd /mnt/d/research/ostg-v9/ostg && git fetch -q /tmp/ostg.bundle v9 && git merge --ff-only -q FETCH_HEAD && git log --oneline -1"'
```

Do NOT pipe the bundle and a heredoc script in the same ssh call — they fight
over stdin and the binary corrupts the script. Two steps, always.

## 1 Generate

**The standard invocation** (v10 onward — keep future runs consistent with
this shape; only seed, batch count and output set name change):

```bash
cd /mnt/d/research/ostg-v10         # cwd MUST be the current versioned
                                    # worktree: python -m puts cwd ahead of
                                    # PYTHONPATH, and a stale ostg/ elsewhere
                                    # silently wins
P=$OW/.venv/bin/python
for i in 0 1; do
  setsid nohup $P -m ostg.taskgen.gen --n 5 --batches 13 --seed <S> --shard $i/2 --stream     --model claude-opus-5 --env $TG/.env     --out $TG/out/runs/<set>-s$i/specs.jsonl     --avoid-corpus /mnt/d/research/cua-gym/tasks.jsonl     > $TG/logs/<set>-s$i.log 2>&1 &
done
```

Anatomy: `--n 5` specs per API call x `--batches 13` x 2 shards = 130 draws,
landing near 100 kept after gate rejections. Defaults that matter and are
deliberately NOT overridden: `--refill 2` (lost batches redraw), thinking off
(5x cheaper, dodges the gateway 504). `--start-batch N` resumes a crashed
shard with seeds aligned; `--spent-from <specs.jsonl>` seeds the quota ledger
so a top-up run overdraws whatever axis is in deficit.

**Scale shapes** (same anatomy, only the knobs change): the 500-scale campaign
shape is `--batches 29 --shard i/4` (580 draws; v500 and v11q2 both used seed
20260812). **Generator swap**: `--model <name>` — claude* speaks the Anthropic
endpoint, anything else (qwen3.8-max, ...) auto-routes to the OpenAI endpoint
via ostg/llm.py's protocol adapter; non-claude default mirrors this runbook's
regime (thinking off + forced tool call). Use `python -u` so shard logs stream
(a buffered log reads as a hang). The `[gen] args` line now prints `code=<git
hash>` — record it; it is the line that answers "which code ran this".

Batch losses are re-drawn by refill; check the tail of the log for the
closing axis summary.
## 2 Ship (accept gates)

```bash
PYTHONPATH=. $P -m ostg.taskgen.ship out/runs/<set>-s0 out/runs/<set>-s1 \
  --ref cua-gym=/mnt/d/research/cua-gym/tasks.jsonl \
  --ref osworld-361=$OW/evaluation_examples/examples
```

re-emit rebuilds every task JSON with the current emitter (older sets pick up
newer fixes), then runs the HARD/REVIEW gates (see README). **To cull
duplicates and contamination** (when accept FAILs), use the module — it is the
mechanical form of the old hand rule:

```bash
PYTHONPATH=. $P -m ostg.taskgen.cull out/runs/<set>-s0 out/runs/<set>-s1 [...] \
  --ref cua-gym=/mnt/d/research/cua-gym/tasks.jsonl [--apply]
```

Dry-run prints the full plan: hard-gate pairs walked in score order, the
later member culled (pass dirs s0 s1 s2 … — positional order is the
generation-order proxy), plus any spec ≥0.5 against a --ref corpus culled
outright. Review the plan, then `--apply` moves lines to `specs_culled.jsonl`
(append — the audit trail survives) and re-run ship; accept must come back
green. First use: v11q2 (28/488 culled, gates all green on the 460 kept).

**Grader-defect scan (before merge, v11+).** Three defect classes pass every
mechanical gate and control, then surface as fake model failures in the
rollout (EXPERIMENTS §3 has the ledger; 8/119 culled in v11):

1. *missing source data* — instruction cites content the setup never creates
   (scan: non-browser specs whose setup writes no file content but whose
   instruction references a source);
2. *rigid output naming* — the agent must create an artifact the instruction
   only describes, but the probe demands one exact filename (scan: probe
   paths absent from both setup and instruction, no glob in the probe;
   convention-derivable names — README.md, same-basename exports,
   `.vscode/tasks.json` — are fine);
3. *dated constant vs deictic time* — instruction says "this year" while the
   probe hard-codes a year.
4. *absent-key default* — a probe reading app config with
   `.get(key, default)` must default to the app's real out-of-box behavior.
   Chrome's `prompt_for_download` is absent-and-off on a fresh profile; a
   probe defaulting it to True makes the task unwinnable for an agent that
   finds the toggle already correct (scan: `.get()` calls on preference
   files, check each default against the app's factory state).
5. *headless-soffice collision* — a setup that runs `soffice --convert-to`
   leaves a headless instance that **lingers indefinitely** and swallows
   every later document open: the config's warm `open` AND the agent's own
   double-click minutes later (lock file on disk, process alive, **no
   window ever maps**). Cost v11 its whole calc domain (0/15, warm and
   cold alike) before diagnosis, and retro-explains v8's 1/33 calc. The
   emitter now auto-inserts `pkill -f soffice.bin; sleep 2` immediately
   after ANY setup containing soffice, warm or cold — the guard applies to
   every emission, so never hand-write task JSONs around the emitter.
   Control cannot catch this class (setup exits 0; an idle desktop
   correctly scores 0): when a rollout enters a new domain, eyeball one
   first-frame screenshot per domain — the bare-desktop signature is
   unmistakable. Related boundary: bare `--convert-to odp` fails
   everywhere (gate-rejected), while the filter-qualified `odp:impress8`
   works.

Cull confirmed hits like duplicates. If the set is oversized, trim to target
by largest-remainder over difficulty x ambiguity cells, dropping the
latest-generated members.

**Deck fixtures (v11.1 rule).** `soffice --convert-to` cannot produce odp or
pptx from text (txt loads into Writer; Writer has no presentation export) —
a gate now rejects such setups. When a task needs a pre-existing deck, build
it host-side and embed it:

```bash
mkdir -p /tmp/dockercfg && echo '{}' > /tmp/dockercfg/config.json   # dodge the Docker Desktop credential helper
DOCKER_CONFIG=/tmp/dockercfg docker run --rm -v /tmp/deckbuild:/data ubuntu:22.04 bash -c \
  "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends libreoffice-impress python3-pip && pip -q install python-pptx && python3 /data/build_pptx.py && cd /data && for f in *.pptx; do soffice --headless --convert-to odp \$f; done"
```

then set the spec's setup to
`mkdir -p <dir> && printf %s <base64 of the .odp> | base64 -d > <path>` (a
15–20 KB deck is ~25 KB of base64 — fine in a task JSON). Probes keep
reading content.xml as usual; the file is genuine LibreOffice output.
`tools/deck_fixtures_v11.py` holds the v11 deck contents as the worked
example.

## 3 Merge

Directory rule: **one launch = one directory** (parallel shards each write
their own; two processes appending one jsonl would interleave). **One task set
= possibly several launches** (shards, crash-resumes). The runner takes ONE
`--test_config_base_dir` + ONE manifest, and control's `--start/--limit`
sharding needs a single ordered manifest, so assembly is a standard step:

```bash
PYTHONPATH=. $P -m ostg.taskgen.merge out/runs/<set>-s0 out/runs/<set>-s1 --out out/runs/<set>-all
```

Exits loudly on **id 冲突**与 **slug 冲突**;sources 不动。任何 cull 之后要重新 merge。

> **slug 门(2026-08-17 加装,事故见 `SFT_DATA.md`)**:id 是 UUID 永不撞,
> 但 slug 由任务内容派生,**两个分片可以各自唯一、合并后同名**。merge 现在
> 直接拒绝并列出重复项(输出目录不写),要么 cull 掉一员再 merge,要么显式
> `--allow-slug-collision`。历史遗留:`v11-500-final`(3)、`-recheck`(4)、
> `-recheck2`(3)、`v500-all`(4)都带冲突,SFT 侧靠下面四道门自保。

## 4 Control (negative checks — run before every rollout)

Catches three failure classes OSWorld swallows silently: setup exiting
non-zero, a probe that crashes (the task silently leaves the denominator),
and a probe that passes without work (SFT poison). Three lanes, ceil(N/3)
each:

```bash
L=69
for i in 0 1 2; do
  setsid nohup env PYTHONPATH=.:$OW $P -m ostg.taskgen.control \
    --tasks out/runs/<set>-all --path_to_vm $OW/docker_vm_data/Ubuntu.qcow2 \
    --start $((i*L)) --limit $L --report out/runs/<set>-all/control_report_$i.jsonl \
    > logs/control-<set>-$i.log 2>&1 &
done
```

Roughly 2–4 minutes per task per lane. BAD tasks: cull as in §2, then
re-merge. **Never run control concurrently with a rollout** (see §7 memory).
Known blind spot: control skips `open` config steps, so a task whose start
state depends on `open` (deictic/a3 tasks) is not fully exercised.

**Excluding BADs without a re-merge** (the autolaunch path): the runner
manifest keys tasks by **uuid**, control reports carry **slugs** — filtering
the manifest with slugs silently removes nothing. Map slug → uuid through
`<set>-all/examples/*/*.json` (each task's `ostg.slug`), then filter.
Verify the printed task count actually dropped before launching.

## 4.5 Positive-direction checks: gold injection + audit (v8.4+)

Control only proves "no work scores 0"; these two cover the reverse direction.
Four checks divided by blind spot — each catches what the others structurally
cannot (right column: what it misses, and who covers that):

| check | catches | cannot catch (covered by) |
|---|---|---|
| control (negative) | free points, broken setup | everything positive (below) |
| gold injection | graders that can never pass: lazy-write timing, wrong paths/constants | gold whose world-beliefs are wrong (audit) |
| audit | instruction ⊄ grader coverage; wrong world assumptions in golds | anything only real execution exposes (rollout) |
| rollout | whatever slipped past all three | — most expensive, final referee |

**The audit is an LLM review**: one call per task; the judge reads the
instruction plus the grader source and returns covered / partial (instruction
demands the grader ignores) / overreach (grader demands the instruction never
made), plus world_assumptions (beliefs about the live web baked into grader
constants, checked against the judge's own world knowledge). **Use a
different model than the generator** — and prefer one fixed third-party judge
across corpora so rates stay comparable (judge severities differ measurably).

```bash
# 1) LLM coverage audit (API only, no VM, report-only)
PYTHONPATH=. $P -m ostg.taskgen.audit out/runs/<set>-s0/specs.jsonl [...] \
  --out out/runs/audit-<set>.jsonl --model claude-sonnet-4-6 --stream

# 2) gold scripts (API only; the answer key must be computed accurately)
PYTHONPATH=. $P -m ostg.taskgen.gold out/runs/<set>-s0/specs.jsonl [...] \
  --out out/runs/gold-<set>.jsonl --model claude-opus-5 --stream

# 3) gold injection (VM; control's mirror mode: must score 1.0 after injection)
PYTHONPATH=.:$OW $P -m ostg.taskgen.control --tasks out/runs/<set>-all \
  --path_to_vm $OW/docker_vm_data/Ubuntu.qcow2 --gold out/runs/gold-<set>.jsonl
```

Reading the results:

- `audit-*.jsonl`: rows with verdict != covered or non-empty
  world_assumptions go to review; the remedies are cull / fix the grader
  gold / trim the instruction promise.
- `gold_report.jsonl` rows with ok=false split two ways: `gold_rc != 0` means
  the key script itself is broken (regenerate); `gold_rc == 0` with score 0
  means **the grader can never pass — a real defect** (probe_out locates it).
- Calibration cases on record: the Chrome lazy-write class (gold injection
  catches), the dual-requirement browser class (audit catches), the
  wrong-world-belief class (audit's world_assumptions catches).

## 5 Rollout

### What the OSWorld AUTHORS run — three declared step tiers, not one config

Checked in the upstream worktree `091f5ef1` on 2026-08-14, because "the official
settings" had been used loosely in this project to mean three different things:
our own run of the official 361 tasks, the upstream defaults, and the authors'
published baseline. Only the last is what the paper numbers come from.

**The authors' paper baseline** (`README.md`, "the baseline agent used in our
paper", GPT-4o pure-screenshot):

```bash
python run.py --provider_name vmware --headless \
    --observation_type screenshot --model gpt-4o \
    --sleep_after_execution 3 --max_steps 15
```

with `run.py`'s own defaults filling the rest: **`max_trajectory_length 3`**,
`max_tokens 1500`, `temperature 1.0`, `top_p 0.9`, 1920×1080.

**Every agent then brings its own numbers.** Per-runner defaults in
`scripts/python/`:

| agent runner | max_steps | sleep | history | max_tokens | temp |
|---|---:|---:|---:|---:|---:|
| `run.py` (paper baseline) | **15** | 0.0 → **3 documented** | **3** | 1500 | 1.0 |
| claude | 15 | 0.5 | 3 | 16000 | — |
| openaicua | 15 | 0.0 | 3 | 1500 | 1.0 |
| qwen25vl | 15 | 0.0 | 3 | 1500 | 1.0 |
| qwen3vl | 15 | 0.0 | 3 | 32768 | 0 |
| gpt54 | 15 | 0.0 | 3 | — | 1.0 |
| aguvis | 15 | 2.0 | — | 1500 | 0 |
| dart_gui | 15 | 5.0 | — | 500 | 0.0 |
| os_symphony | 15 | 1.0 | 8 | — | — |
| owl | 15 | 1 | 15 | 1500 | 0 |
| autoglm | 50 | 1.0 | 3 | 4096 | 0.4 |
| gui_owl15 | 50 | 5 | **50** | — | 0 |
| mobileagent_v3 | 50 | **10.0** | **50** | 1500 | 0 |
| evocua | 50 | 5.0 | — | 32768 | 0.0 |
| **qwen (ours)** | **50** | **0.0** | **see below** | 32768 | **0.0** |
| gemini | 100 | 5.0 | — | — | — |
| kimi_k25 | 100 | 5.0 | — | 4096 | 1.0 |
| opencua | 100 | 5.0 | — | 2048 | 0 |
| m3 | 100 | 3.0 | 10 | 8192 | 0.6 |
| muse_spark | 100 | 0.0 | **100** | **131072** | — |

Ranges: **max_steps 15–100 · sleep 0–10 · history 3–100 · max_tokens 500–131072
· temperature 0–1.0**. Anyone comparing two numbers on this leaderboard is also
comparing two harnesses.

**`run_multienv_qwen.py` does not use `max_trajectory_length` at all.** It has a
different history mechanism: `history_n 100` (turns of TEXT kept) + `image_max
20` + `fold_size 10` (screenshots kept; older ones become the string "This
screenshot has been collapsed."). So on the Qwen line the model carries **every
previous response verbatim, reasoning included, with only the last ~20
screenshots**. The modal upstream setting — and the paper baseline — is
`max_trajectory_length 3`.

**Thinking is off by default on this line.** `--enable_thinking` is honoured
only when the base URL contains `dashscope`; against a local vLLM it is silently
discarded, and vLLM 0.25 additionally renamed the response field
`reasoning_content` → `reasoning` so the client read `None` and dropped it.
Both are patched locally (`main.py`, `client.py`); **without those patches an
upstream Qwen run has no reasoning at all.** Our own official-361 campaign
proves it: **7,906 steps, 0 containing `<think>`** — the responses start with
two blank lines where the discarded reasoning used to be, and that campaign's
45.2% was scored with no thinking whatsoever.

### Why the dashboard looks stale (2026-08-14)

It is not stale — it is slow. Both daemons were alive and the last push was 22
minutes old when checked. The cycle is **~70 minutes, not the 5 the daemon loop
suggests**, and the whole of it is one step:

```
[19:40] traj: staging
[20:06] traj: publishing 255 viewers     <- ~26 min
[20:17] pushed (scored=30 100 252)
```

`dash_status_daemon.sh:113` regenerates **every** trajectory viewer each round
via `ostg.traj_html`, then rsyncs the lot. At 255 viewers that is ~26 minutes of
work to republish pages that overwhelmingly did not change. It grows with the
corpus, so it will keep getting worse.

The fix is to make the regeneration incremental — skip any task whose
`traj.jsonl` mtime predates its `viewer.html`. Not applied yet.

One other thing in that log: at 17:11 the run died on
`Unable to create '/mnt/d/research/cua-dash/.git/index.lock': File exists`. The
two-clone design (`control/README.md`) is supposed to make contention impossible,
so either something else is touching `cua-dash`, or a crashed git left the lock
behind. It recovered on the next cycle; worth watching rather than chasing.

### Qwen3.8's chat template, read at source (2026-08-14)

Pulled from the served weights: `/gpfs/scrubbed/jy050706/models/Qwen3.8-27B/chat_template.jinja`
(8,952 bytes). Everything below is the template's own code, not inference.

**Where `xhigh` comes from — Qwen ships it as the default** (`:47`):

```jinja
{%- set resolved_reasoning_effort = reasoning_effort|default('xhigh') %}
{%- if resolved_reasoning_effort not in ('xhigh', 'medium', 'low') %}
    {{- raise_exception('Unexpected reasoning effort ...') }}
```

Only **three** values exist: `xhigh` (default), `medium`, `low`. **`high` is not
one of them** — that is the 400 seen earlier, a template `raise_exception`, not a
vLLM bug. `medium` is the only value that emits **no preamble at all**; `xhigh`
and `low` each prepend a sentence ahead of our system prompt. Nothing in our
stack sets it, so every request in the campaign runs at `xhigh`.

**Where the empty `<think>` block comes from** (`:111-120`):

```jinja
{%- set reasoning_content = '' %}
{%- if message.reasoning_content is string %}
    {%- set reasoning_content = message.reasoning_content %}
{%- endif %}
{%- if preserve_thinking is undefined or preserve_thinking is true
       or loop.index0 > ns.last_query_index %}
    {{- '<|im_start|>' + message.role + '\n<think>\n' + reasoning_content + '\n</think>\n\n' + content }}
{%- else %}
    {{- '<|im_start|>' + message.role + '\n' + content }}
{%- endif %}
```

The template reads reasoning from a **separate `message.reasoning_content`
field** and **always emits the `<think>` wrapper** on the preserve branch. We
never set that field — our reasoning is merged into `content` by
`client.py:51` — so the wrapper renders **empty**, and then our content, which
itself opens with `<think>real reasoning</think>`, follows it. Hence two blocks
per historical turn. The empty one is the template's structural slot standing
vacant; the real one is our text arriving through the wrong door.

**`preserve_thinking` is retired** (user decision, 2026-08-14) — it is not a
lever here in any case: `undefined` takes the same branch as `true`, and `false`
only strips the `reasoning_content` slot, never text living inside `content`.
Verified against the live server: production shape, `false`, `medium`, and
`medium`+`false` all keep the reasoning in every turn (131 / 119 / 89 / 77
tokens). **The server-side lever does not reach our thinking.** Any hide-thinking
experiment must be client-side, in `QwenAgent._response_transform`
(`main.py:265`) — the same hook `ensure_empty_think_prefix` already occupies.

**The two directions, stated once** — this pair of facts reads as a
contradiction until the direction is attached. *Response* (server → us):
`--reasoning-parser qwen3` splits generated text and thinking arrives in the
response's `reasoning_content`/`reasoning` field — the field works. *Request*
(us → server): vLLM drops `reasoning_content` on input assistant messages — the
field is dead. So "thinking is replayed into history" and "thinking cannot ride
in `reasoning_content`" are both true: the harness's merge (`client.py:51`) is
the bridge, catching the field on the way out and re-embedding the text in
`content` on the way back in. Without that bridge thinking is lost entirely —
the official-361 run's 7,906 steps with zero `<think>` is what the broken bridge
looks like. **Keep thinking in `content`; there is nothing to change.**

**Does thinking go back into history? — every reasoning model in the authors'
Verified archive, from code + archive evidence** (2026-08-14). Method per row:
archive `args.json` fingerprinted to its runner (exact or subset key match),
then that agent's history-construction code read; trajectory samples where they
add anything.

| Verified run | thinking exists? | replayed into history? | mechanism | text history | images |
|---|---|---|---|---|---|
| **claude**-3-7 / 4 / 4-5 (15/50/100 steps each) | yes — API thinking blocks (`no_thinking: false`) | **yes, verbatim + signature** | native `thinking` blocks; non-text blocks replayed via `model_dump()` (`anthropic/utils.py:528`); the API *requires* them back when tool use + thinking are on | **full episode** | last 10 |
| **o3** (15/50/100) | hidden reasoning: yes; **API never returns it** | internal: **never** · prompted visible "Thought:" **yes** | `parse_thought_from_planner_response` regexes the *visible* text; replayed as user-role text `Thought:\n…\nAction:…` (`o3_agent.py:98-107`) | full episode | last 5 |
| **doubao**-1.5-thinking (runner = `uitars15_v2`, archive keys ⊂ its argparse) | yes — prompted inline `<think>` in `content` (`"thinking":{"type":"enabled"}` sent; only `content` read) | **yes, inline text, verbatim** | `history_responses` replayed untouched as assistant content (`uitars15_v2.py:832`) | full episode | last 5 |
| **kimi**-k2.5 (`thinking: true`) | yes — API `reasoning_content` field | **yes, as text in Kimi's own markers** | history template `◁think▷{thought}◁/think▷## Action:\n{action}` (`kimi_agent.py:51`), thought = `response['reasoning_content']` (`:63`) | full episode | last 3 |
| qwen3.7 / 3.5-RL / 2.5-vl | no (all nothink) | n/a | — | full / h100 / 3 turns | 20 / ? / 3 |

(Current-tree `seed_agent.py` — a newer Doubao runner, not the archived run —
goes further still: it splits reasoning out on a sentinel and sends it back as a
`reasoning_content` **field** on input assistant messages (`seed_agent.py:647-651`),
which Volcengine's API accepts. Our vLLM drops that field; theirs doesn't.)

**The pattern is unanimous: every model whose reasoning is *accessible* replays
it into history, full-length.** Claude ships it back as signed blocks because
the API demands it; Doubao inlines it in content; Kimi re-wraps it in its own
think markers; the newer Seed runner passes it as a field; qwen3.6-on-V2 inlines
it. The single exception, o3, is not a design choice — the API physically
withholds the reasoning, and the agent compensates by replaying the *prompted*
visible Thought text instead. Nobody strips accessible reasoning from history.

**Correction to the per-agent config table above:** its claude `hist=3` row is
wrong in effect. `run_multienv_claude.py:276` passes `max_trajectory_length=3`,
but `AnthropicAgent.__init__` has no such parameter — it vanishes into
`**kwargs`, unused. The Claude runs keep the **full** message history and cap
only images (10). The argparse-default column in that table records what runners
*declare*, not always what agents *do*.

**OpenWebRL cross-check** — the closest published 4B-student pipeline ships
`hide_thinking`/`action_only` compression knobs and then defaults every released
script to `full` with the reasoning window off; their headline numbers train on
full thinking in history with **1–3 screenshots** in context. Details and the
delta table: `sft/TRAINING.md`, "How OpenWebRL handles thinking".

**Design consequence for us:** replaying full thinking in history is not our
eccentricity — it is the norm across the authors' own Verified runs for every
model that allows it. The open question (does a reasoning-saturated context
help or hurt a 27B student?) remains open, but "the authors don't do this" is
now off the table as an argument either way.

**Every Qwen run in the authors' Verified archive, and what each model actually
received** (2026-08-14; all read from the archives themselves — args.json
fingerprints, sampled trajectories, and, where they exist, the dumped messages).

| archive | tasks | runner (by exact argparse-key match) | steps | temp | history | thinking in responses | model input recorded? |
|---|---|---|---|---|---|---|---|
| qwen2.5-vl-**32b** ×2 (15/100 step) | Verified `test_all` | `run_multienv_qwen25vl.py` (24/24 keys) | 15 / 100 | 1.0 | `max_trajectory_length` **3** | none (non-reasoning line) | no |
| qwen2.5-vl-**72b** ×2 (15/100 step) | same | same | 15 / 100 | 1.0 | 3 | none | no |
| **qwen3.5-plus** nothink (OSWorld-RL, `testall_h100`) | Verified task set | OSWorld-RL pipeline (no args.json; `messages.json` per task) | 100 | — | h100 | none | **yes — 1,326 message dumps** |
| **qwen3.7-plus** (100 steps) | Verified 361 `test_nogdrive` | **`run_multienv_qwen.py` (33/33 keys — ours)** | 100 | 0.6 | `history_n` 100 | **none — 0/323 sampled steps** | no |
| *(dataset-root `args.json`, model "mano", qwen25vl mode)* | Verified `test_nogdrive` | mano agent | 100 | 0.0 | 3 (+5 images) | — | no |
| qwen3.6-cua think / nothink | **V2 (102) — not Verified** | V2 `run_multienv.py` | 300 | 0.6 | 300 | think run: yes | no |

**Direct answer to "did their history carry the extra think block":**

- **qwen3.5 — no, observed directly.** The only Verified archive with message
  dumps. 5/5 sampled tasks: every assistant turn in the sent history starts
  `Action: ` — **zero `<think>` of any kind, real or empty**. The RL harness
  replays bare `Action: … <tool_call>…` strings.
- **qwen3.7 — not recorded.** The archive has no message dumps, so what its
  model received cannot be read from data. What IS known: its responses carry no
  thinking (0/323), and — code-fact about the shared runner, not their data —
  `ensure_empty_think_prefix` prepends an empty `<think>` to each replayed turn
  client-side. Whatever their serve's template then did at render time is their
  template's business and is not knowable from the archive.
- **qwen2.5-vl — no think concept at all**; 3-turn history, non-reasoning line.
- **ours, for contrast — observed directly** in our own dumps
  (`draft/message_cache/qwen_messages_step_*.json`, live 3.8 run): 49/49
  assistant turns carry exactly **one, real** think block merged in `content`;
  the doubled empty slot appears only at server-side template render (proved via
  `/tokenize`), never in the sent messages. Caveat: that dump dir is shared
  across the 3 envs and overwritten per step index — fine for shape checks,
  useless for per-task attribution.

Reading order for the confusion this table retires: the authors have published
**no Verified Qwen run that feeds thinking through history at all** — every
Verified Qwen number of theirs (2.5-vl, 3.5-RL, 3.7) is nothink. The only
author run with thinking in history is qwen3.6 on **V2**. We are the first
Verified-harness run in this comparison set that replays real thinking.

**Why the `answer` hallucination vanished in 3.8 — paired-task evidence
(2026-08-15).** All 106 of 3.6's `answer` emissions came from three tasks
(44×, 19×, 43× — the parser has no branch, so each became WAIT and the model
re-tried into the same screenshot). The same three tasks under 3.8:

| task | 3.6 | 3.8 |
|---|---|---|
| 9d933275 | 0.0 — 44 `answer` spins | **1.0 in 4 steps**, prose close |
| a4b791c4 | 1.0 — 19 spins after the work was done | **1.0 in 14 steps**, prose close |
| 64d9fd2c | 1.0 — 43 spins after the work was done | **1.0 in 8 steps**, prose close |

The behavioural slot is identical — "I have the result, I want to say it and
stop" — and `answer` is exactly the tool the BASE dialect provides for that
(the Qwen team's own RL tools_def declares it). Under the internal dialect the
tool does not exist; 3.6 reached for it anyway (its training prior), while 3.8
expresses the same intent schema-legally: state the result in prose, emit no
tool call, which upstream's DONE fallback turns into a clean scored stop. The
hallucination did not so much disappear as find its legal channel.

**Two harnesses — keep them apart** (clarified 2026-08-14 after conflating
them). The authors' archives mix runs from two different codebases, and evidence
from one does not transfer to the other:

| | OSWorld (**Verified**) — what we run | OSWorld-V2 — not what we run |
|---|---|---|
| runner | `run_multienv_qwen.py` | V2's `run_multienv.py` (has `eval_version`) |
| agent | `mm_agents/qwen/` (`QwenAgent`) | V2's `qwen_internal_agent.py` |
| authors' runs in the archive | qwen3.7-plus, 361 tasks | qwen3.6 think + nothink, 102 tasks |

**Verified side.** The qwen3.7-plus `args.json` keys match
`run_multienv_qwen.py`'s argparse **exactly — 33 keys, zero diff in either
direction** — so the authors' only published Verified Qwen run used literally
our runner. And it ran **nothink: 0 of 323 sampled steps contain `</think>`**
(model name `qwen37_plus-nothink-can` agrees). Their 0.690 / 66.6%-exact on
Verified was achieved with no thinking at all. So on Verified the authors never
exercised thinking-through-history; when **we** enable it, the in-content merge
is upstream's own code path (`client.py:51`), but running with thinking on this
benchmark is our choice, not a reproduction of theirs.

**V2 side** (evidence stays, scope corrected — this is where the 337/337 finding
belongs). V2's `qwen35vl_agent.py:655` reads only `choices[0].message.content`
and `qwen_internal_agent.py:240` replays it verbatim; their serve ran no
reasoning parser — responses open mid-thought with no `<think>` yet 337/337
sampled steps carry the reasoning. So on V2, thinking rides in `content` by
never being split. Same one-blob destination as our Verified path, different
route, **different benchmark** — it demonstrates the convention works, not what
the authors do on Verified.

**Why one blob is legible to the model:** the three segments carry trained
delimiters — `<think>…</think>` are special tokens in the Qwen3 vocabulary, and
`<tool_call><function=…>` is the function-calling grammar the template itself
renders structured `tool_calls` into (`:121-132`). Structured fields and a
pre-rendered blob therefore reach the model as essentially the same token
stream; there is no hidden "more structured" view to lose. The V2 system prompt
additionally pins position ("reasoning … BEFORE the function call, but NOT
after"). Empirically: 1399/1399 live-3.8 steps have well-formed think blocks and
parseable calls.

**What the standard shape would be.** The template wants:

```json
{"role": "assistant", "reasoning_content": "...", "content": "...", "tool_calls": [...]}
```

with tool calls in their own field — the template renders them into
`<tool_call>\n<function=...>` itself (`:121-132`). Our harness instead sends one
text blob carrying `<think>`, prose, and `<tool_call>` markup together. That is
the OSWorld-Qwen convention and the authors' own runs do the same (their
`messages.json` shows assistant turns as plain strings), but it predates 3.8's
template.

**It is not fixable by just moving the field, though**: vLLM **drops
`reasoning_content` from input messages** — passing it renders an empty `<think>`
and the text never appears (verified, same endpoint). So on this vLLM version the
in-content convention is the only one that reaches the model at all, and the
doubled block is its unavoidable cost. Leave it.

**Measured against the live Qwen3.8 server, 2026-08-14** — `POST /tokenize`
renders the real chat template, so this is what the model actually receives, not
an inference from code. Three assistant turns, each carrying a distinct marker
inside `<think>`:

| chat_template_kwargs | tokens | thinking surviving |
|---|---:|---|
| *(none)* | 140 | turns 1, 2, 3 |
| `enable_thinking: true` | 140 | turns 1, 2, 3 |
| `+ preserve_thinking: true` | 140 | turns 1, 2, 3 |

**Qwen3.8's template does not strip historical reasoning, and `preserve_thinking`
changes nothing — all three render byte-identically.** The whole episode's
reasoning is in context regardless of the flag. (Tested on 3.8 only; 3.6 serves a
different template and was not re-tested.) That retires `--preserve_thinking` as
a variable for this model — the arms that differed on it differed on nothing.

Two things the render exposed that no one was looking for:

**① The template prepends an empty `<think>\n\n</think>` to every historical
assistant turn, unconditionally.** With a plain answer the model sees
`<think>\n\n</think>\n\nPLAINANSWER`; with our real responses — which already
open with `<think>` — it sees **two** blocks back to back:

```
<|im_start|>assistant
<think>

</think>

<think>
...the real reasoning...
</think>

...the visible content...<|im_end|>
```

This also makes our `ensure_empty_think_prefix` (`history.py:92`) dead weight on
3.8: the template does the same job, and on responses that already carry
reasoning our function is a no-op while the template still prepends.

**② The template injects a reasoning-effort preamble ahead of our system prompt,
and its default is the highest setting.** With no kwargs at all:

> `Reasoning effort is set to xhigh. Please think carefully through the task,
> validate key assumptions, consider plausible alternatives, and prioritize
> correctness, consistency, and clarity in the final answer.`

then a blank line, then our own system prompt. Passing
`reasoning_effort: "medium"` is the only setting that emits **no line at all**
(18 tokens vs 44 for `low`); `high`/`xhigh` were rejected with a 400 through
`chat_template_kwargs`, so the route to change it is not yet established.

**The live campaign is running on `xhigh`,** since `_build_payload` sends only
`{"enable_thinking": true}`. What that costs, measured over both campaigns'
`traj.jsonl` on the same 100-task corpus:

| | steps | response chars med / p90 | `<think>` present | think chars med / p90 |
|---|---:|---|---:|---|
| Qwen3.6 | 3770 | 605 / 1056 | 100% | 357 / **755** |
| Qwen3.8 (live) | 1399 | 872 / **9688** | 100% | 379 / **6495** |

Medians are close; the **p90 tail is ~9× longer**. That is the xhigh preamble
showing up as occasional very long deliberation. It is not obviously bad — 3.8 is
doubling 3.6's score on these tasks — but it is a setting nobody chose, and it
belongs in any account of why 3.8's steps are slower.

**How fold_size=10 actually works — a saw-tooth, not a sliding window**
(`history.py:7`, five lines): `folded_prefix_k` counts folded OLDEST
screenshots, monotone, advancing by 10 whenever active images would exceed 20.
Active visual window oscillates 11↔20 (boundary jumps at steps 21, 31, 41…);
folded steps keep their full text (think/prose/actions) and only the image
becomes "This screenshot has been collapsed." The chunked design buys prefix
stability — ten consecutive steps share a byte-identical history prefix —
which is exactly what makes Qwen-CUA's fold-aware training slices (and prefix
caching, where the architecture allows it) possible. It also times the diff-5
cliff: those failures close at steps 23–37, i.e. 10–20 images already folded,
first app visible only as text.

**"History = 3" and "history = 20" are not the same axis.** This caused real
confusion, so, verified in the code 2026-08-14:

- The paper's **3** is *one* number covering *both* modalities: three
  `(observation, action)` pairs — three screenshots **and** three actions, capped
  together. `run.py`'s `max_trajectory_length`.
- The Qwen runner **splits that into two independent axes**: `history_n` for
  TEXT and `image_max` (+ `fold_size`) for IMAGES. Text is kept in full; only
  images are capped. There is no `max_trajectory_length` on this line at all.

**Why split them: images cost ~5× more than text even at 1/5 the count.**
`process_image` (`mm_agents/qwen/images.py:19`) sets
`max_pixels = 16*16*4*12800 = 13,107,200`, which a 1920×1080 screenshot
(2,073,600 px) never reaches — so no downscale, and at 28×28 px per visual token
one screenshot is **≈2,650 tokens**. 20 of them ≈ **53,000 tokens**. A response
is 418 chars at the median (measured on the authors' qwen3.6-think run) ≈ 110
tokens, so 100 turns of text ≈ **11,000 tokens**. Capping images and keeping all
text is the cheap trade, and it is why the two knobs exist.

**A long history is not a Qwen peculiarity.** `image_max`/`fold_size` are unique
to this runner, but keeping far more than 3 turns is common upstream:
`muse_spark` 100, `gui_owl15` 50, `mobileagent_v3` 50, `owl` 15, `m3` 10,
`os_symphony` 8. The paper's 3 is a 2024 GPT-4o-era baseline, not a standard.

**Thinking DOES go back into the context — verbatim, for the whole episode.**
The chain, all verified in code:

1. `client.py:51` — `merge_reasoning_content` builds the stored response as
   `<think>\n{reasoning}\n</think>\n\n{content}` whenever the server returns a
   reasoning field.
2. `main.py:265` — `QwenAgent._response_transform` is `ensure_empty_think_prefix`.
3. `history.py:92` — that function **returns the text unchanged if it already
   matches `^\s*<think>.*?</think>`**, and otherwise prepends an *empty*
   `<think>\n\n</think>`.

So a response that carries reasoning is replayed into every later turn with its
reasoning intact, until `history_n` drops it. **With our `history_n 100` and
`max_steps 50`, nothing is ever dropped: the model sees the full reasoning of
every step it has taken.** The authors' runs are the same by construction —
`history_n` equals `max_steps` in all of theirs. The paper's 3-turn baseline had
no reasoning to carry at all (GPT-4o, 2024).

This is the concrete form of the context-compression question: the argument for
an OpenWebRL-style `hide_thinking` is that a context which is almost entirely
past reasoning invites the model to imitate reasoning rather than act. Nothing
here settles that — it just establishes that the reasoning really is all there.

**The authors' own Qwen runs, verbatim.** Their trajectory release ships the
`args.json` each run wrote. Pulled 2026-08-14 by HTTP range request (no archive
downloaded in full — `sft/tools/zpeek.py`); copies in
`reference/osworld-author-runs/`. **They use our exact runner** — the arg set has
`history_n` / `image_max` / `fold_size` / `coord` / `simple_path` /
`add_thought_prefix`, which only `run_multienv_qwen.py` has.

| | qwen3.7-plus | qwen3.6 think | qwen3.6 nothink | `mano` (qwen2.5-vl) | **ours** |
|---|---|---|---|---|---|
| benchmark | **Verified 361** | V2 (102) | V2 (102) | **Verified 361** | generated |
| max_steps | 100 | 300 | 300 | 100 | **50** |
| history_n | 100 | 300 | 300 | 3 (+5 images) | 100 |
| image_max / fold_size | 20 / 10 | 20 / 10 | 20 / 10 | — | 20 / 10 |
| coord | relative | relative | relative | — | relative |
| sleep_after_execution | **5.0** | **5.0** | **5.0** | **10.0** | 3 |
| temperature | **0.6** | **0.6** | **0.6** | 0.0 | **1.0** |
| top_p | 0.95 | 0.95 | 0.95 | 0.9 | 0.95 |
| max_tokens | **8192** | **8192** | **8192** | 1000 | 81920 |
| enable_thinking | false | false | false | — | true |
| num_envs | 9 | 6 | 10 | 10 | 3 |
| enable_proxy | **true** | — | — | — | false |

Two rules hold across all of theirs: **`history_n` is always set equal to
`max_steps`** (keep everything — our 100-with-50-steps has the same effect), and
**`temperature` is 0.6, never 1.0.** `image_max 20` / `fold_size 10` / `coord
relative` match us exactly.

**Their scores, from each archive's own `summary/results.json`:** qwen3.7-plus on
Verified 361 = **mean 0.6899, exact-1.0 66.6%** (n=374). qwen3.6-think on
OSWorld-V2 102 = mean 0.2984, exact-1.0 6.3% (n=95).

**Thinking is present in their trajectories.** Sampled `qwen36-cua-think` task
006: **337/337 steps carry a `</think>` block**, median response 418 chars, p90
771 — and with `history_n 300` all of it stays in context. Note `enable_thinking`
is `false` in their args, which confirms the flag is inert against a local vLLM
(it is honoured only for `dashscope` base URLs); the reasoning arrives through
the parser, not the flag.

**Their action dialect is the newline form**, e.g.
`<parameter=action>\nleft_click\n</parameter>` — the same shape our parser
expects, so `OSTG_PARAM_DIALECT` stays unset.

**Which tool definition they used.** The `qwen35` RL archive ships the literal
`tools_def.json`, and its 14-action enum is **byte-identical to upstream's
`build_base_tools_def`** — including `answer`, which it documents as "Answer a
question". But the qwen3.7 Verified-361 trajectories emit `screenshot`, which
only `build_internal_tools_def` declares. So both dialects are in real use by the
authors, and **our choice of `internal` matches their 3.7 run.** `answer` is
therefore not a hallucination *in general* — it is declared in the base dialect —
but it is genuinely undeclared in the internal dialect we run.

**The spread is not chaos — the authors declare three tiers.** The repo alone
made the variation look arbitrary, so it was checked against the authors'
external sources on 2026-08-14. Their own trajectory release
(`huggingface.co/datasets/xlangai/ubuntu_osworld_verified_trajs`, "15+ model
variants", 1000+ episodes, 500 GB) states the protocol the repo never documents:

> **15 steps** — Quick evaluation · **50 steps** — Standard evaluation ·
> **100 steps** — Extended evaluation

Every per-runner number above lands on one of those three, or on a submitter's
own pick between them. `run.py`'s 15 is the *quick* tier, which is what the
NeurIPS paper reports; the 50s and 100s are *standard* and *extended*.
**Our 50 is the authors' Standard tier** — that was luck, not design, but it is
the right place to be.

**The tier is worth several benchmark points, and the authors say so.** From the
OSWorld-Verified announcement: *"o3's performance varies drastically with step
budget (9.1% to 23.0%), compared with 5% of GPT-4o"* — a 14-point swing on one
model from one config knob, and a 3× ratio between the same model's own numbers.
They also state plainly: *"We ran experiments for each model under different step
settings."* So the leaderboard is not one protocol; it is the best of three per
submission.

Third-party aggregators reach the same conclusion independently — the Steel.dev
benchmark registry warns that rows *"can vary by evaluator, harness, attempt
budget, tool access, task filtering, or verification level"*, and its OSWorld
board shows the current top entries at 100 steps against OpenAI CUA's 50.

**Sources checked (2026-08-14).** Paper §4.1 (`ar5iv` HTML): *"a max step limit
of 15"*, *"providing the most recent 3 observations and actions in chat mode"*,
*"a temperature of 1.0 and top-p of 0.9"*, *"resolution … set to 1920×1080"*.
Appendix C.1 ("Hyper-Parameter of the Baseline Agents") is referenced by the
paper but was not retrievable — **max_tokens and any inter-action sleep are
still unconfirmed from the paper itself**; the 1500 / sleep-3 figures above come
from the repo, not the paper. The OSWorld-Verified blog does **not** publish a
per-model × per-tier score table, and the HF dataset viewer is broken (schema
error), so the per-tier numbers behind "9.1% to 23.0%" could not be read.

**How our generated-task campaigns sit against the paper baseline:**

| | authors' baseline | ours |
|---|---|---|
| runner | `run.py` | `run_multienv_qwen.py` (also upstream) |
| max_steps | 15 | 50 |
| history | 3 turns | 100 turns + 20 images |
| max_tokens | 1500 | 81920 (measured p90 output: **143 tokens**) |
| sleep | 3 | 3 (was 1 until 2026-08-14) |
| thinking | n/a for gpt-4o | on, via two local patches |

### The harness is behaviourally upstream again (2026-08-14)

**`mm_agents/qwen/actions.py` is now `+60 / −0` against upstream `091f5ef1`** —
sixty added lines, **zero upstream lines changed**. What remains is a dialect
shim that does nothing unless `OSTG_PARAM_DIALECT=inline`, and one
`logger.warning`. With that variable unset the behaviour is upstream's.

**What was reverted, and why it mattered.** Every campaign before this one ran
with a patch turning an unparseable response into `WAIT` instead of upstream's
`DONE`:

```python
if not pyautogui_code:
    pyautogui_code.append("FAIL" if infeasible_response else "DONE")   # upstream
#                                                           "WAIT"    # our patch
```

The patch was added because the model sometimes emits nothing after `</think>`
and three impress tasks died on it. But **`DONE` is not "fail"** — it stops the
episode and scores the final state — so the patch could only *add* attempts.
It inflated pass rates against every published OSWorld number. Measured on our
own corpora before reverting:

| corpus | tasks that would have ended earlier upstream | of those, currently scoring 1.0 |
|---|---:|---:|
| v11 (100) | 10 | **7** |
| v11-500 (252 scored) | 54 | **20** |

So **v11's 39% and v11-500's 24% are numbers from a patched harness** and are
not comparable to published OSWorld results. Every campaign from 2026-08-14
onward is.

### How far the run parameters sit from upstream defaults

`run_multienv_qwen.py` is upstream's own Qwen runner, not something we wrote.
Its defaults versus what we pass:

| parameter | upstream default | ours | note |
|---|---|---|---|
| `history_n` / `image_max` / `fold_size` | 100 / 20 / 10 | **same** | what the model sees is untouched |
| `action_space` / `observation_type` / screen | pyautogui / screenshot / 1920×1080 | **same** | |
| `max_steps` | 50 | **50** | v11-500 used 100 until 2026-08-14 |
| `sleep_after_execution` | 0.0 | **1.0** | gives the UI time to repaint before the screenshot |
| `num_envs` | 1 | **3** | throughput |
| `temperature` | 0.0 (greedy) | **per the model card** | see below |
| `max_tokens` | 32768 | **81920** | 32768 is also Qwen's general recommendation; 81920 is their competition setting |

**A naming trap worth knowing**: the official-361 result directory is called
`...-temp06-sleep3-maxsteps50-...` but the campaign passed
`--sleep_after_execution 0` (`run_verified_campaign.sh:153`, confirmed by its
own `args.json`). **The `sleep3` in that name is wrong and no code reads it.**

### Sampling: the client wins, so the serve file lies

`--override-generation-config` on the vLLM serve only sets *defaults*. The
runner sends `temperature` on every request and that takes precedence. The
Qwen3.6 serve script has said `"temperature": 1.0` for its whole life while
every rollout actually ran at **0.6**. **Read the runner command, not the serve
file.**

Qwen publishes two thinking profiles for 3.5, 3.6 and 3.8 alike:

| | thinking · general | thinking · precise coding |
|---|---|---|
| all three models | **temp 1.0**, top_p 0.95, top_k 20, min_p 0 | temp 0.6, top_p 0.95, top_k 20 |

Campaigns through 2026-08-13 used the **precise-coding** profile — Qwen labels
that row "precise coding tasks (e.g. WebDev)", and driving a GUI is agentic
control. The Qwen3.8 campaign uses the general profile.

### There are TWO tool definitions upstream; we use `internal`

`mm_agents/qwen/prompts.py` ships both, and they are deliberately different
interfaces for different model generations — not an oversight to be aligned:

| | `build_base_tools_def` | `build_internal_tools_def` (ours) |
|---|---|---|
| how a task ends | `answer` | `terminate` + `call_user` |
| low-level input | — | `key_down`/`key_up`, `left_mouse_down`/`up` |
| explicit capture | — | `screenshot` |

`QwenAgent` — what `run_multienv_qwen.py` instantiates — uses `internal`.
Qwen3.6 emitted `answer` **64 times across 3,425 steps** even though it is not
in the list it was given; the parser has no branch, so those steps degraded to
the fallback. **Do not add an `answer` branch mapping to DONE** — that makes a
hallucination end the episode irreversibly.

### The teacher serve is FP8 since 2026-08-14

`serve-chain-36-fp8.sbatch` (model `Qwen3.6-27B-FP8`, the official quantization)
replaces `serve-chain-36.sbatch`. Measured A/B on identical prompts and images,
`logs/fp8_ab.log`:

| images per request | BF16 | FP8 | speedup |
|---|---|---|---|
| 1 | 2.8 s | 2.0 s | **1.41×** |
| 8 | 4.8 s | 3.2 s | **1.51×** |
| 20 | 6.9 s | 4.9 s | **1.39×** |

Two things do **not** change, on purpose: `--served-model-name` is still
`qwen36-27b-bf16-local`, so `--model` and every result path stay as they were.
The name is now a misnomer — **the precision of record is
`PRECISION_BOUNDARY.json` inside the result dir**, not the directory name. It
lists every task generated under BF16 (v11-500: the first 121, 32 passed);
everything after its timestamp is FP8. Mixing precisions inside one campaign is
a deliberate, recorded choice, and any per-task analysis that cares must read
that file rather than assume the corpus is homogeneous.

The Slurm job name changes with it: **`eval` → `evalfp8`**. Anything that finds
the serve by name (the tunnel's `JOB=`, cancel selectors) has to follow. Use
`squeue -n <name>`, which is an exact match, rather than a `grep`/`awk` pattern —
a `$` anchor does not survive Mac shell → ssh → wsl → ssh → remote shell.

Resuming the campaign after a serve swap is one command:
`osworld-verified-control/v11_500_fp8.sh` (cancels the old serve, submits the
FP8 one, re-points the tunnel, then supervises the runner until every task in
the manifest has a `result.txt` — it survives the serve self-chaining onto a new
node at its 12 h wall).

Preflight — the tunnel must answer (HTTP 200 + model id):

```bash
cd $OW && set -a && . ./.env && set +a && curl -s -w '\nHTTP %{http_code}\n' \
  -H "Authorization: Bearer $OPENAI_API_KEY" http://127.0.0.1:18001/v1/models
```

Standard parameters (official-361 protocol except sleep 1, max_steps 100, and
thinking captured + preserved):

```bash
cd $OW && setsid nohup .venv/bin/python scripts/python/run_multienv_qwen.py \
  --provider_name docker --path_to_vm $OW/docker_vm_data/Ubuntu.qcow2 --headless \
  --observation_type screenshot --action_space pyautogui \
  --model qwen36-27b-bf16-local --base_url http://127.0.0.1:18001/v1 \
  --temperature 0.6 --top_p 0.95 --max_tokens 81920 \
  --max_steps 100 --sleep_after_execution 1 \
  --enable_thinking --preserve_thinking --num_envs 3 --simple_path \
  --screen_width 1920 --screen_height 1080 \
  --test_config_base_dir $TG/out/runs/<set>-all \
  --test_all_meta_path $TG/out/runs/<set>-all/manifest.json \
  --result_dir $R/<set>-ms100-think-preserve-$(date +%Y%m%d) \
  > $TG/logs/rollout-<set>.log 2>&1 &
```

The **no-preserve variant** (v11 standard: official-comparable budget, and
preserve_thinking is implicated in loop-lock — EXPERIMENTS §3 finding 2):
drop `--preserve_thinking`, set `--max_steps 50`, name the result dir
`<set>-ms50-think-nopreserve-<date>`. Thinking is still generated and
captured per step; it just isn't re-fed as context.

The whole chain (wait for control lanes → build `manifest_clean.json` minus
BAD slugs → tunnel check → rollout → memory medic at <1G → heal passes →
traj_html) is scripted: `autolaunch_v11.sh` in the execution repo — copy and
rename per set.

**Re-running with the same `--result_dir` is the recovery mechanism**: tasks
with a result.txt are skipped, tasks without one are redone (screenshot-500
casualties, Slurm handoff blips, setup aborts — all healed by one relaunch at
the end).

max_steps counts MODEL CALLS, not actions: one call emitting several
tool_calls burns one step. Thinking lands in traj.jsonl inside the response
(`<think>…</think>`), preserved across turns via
`chat_template_kwargs.preserve_thinking`.

## 6 HTML trajectory viewer

Upstream OSWorld has no visualizer; generate/refresh at any time, mid-run
safe:

```bash
PYTHONPATH=. $P -m ostg.traj_html $R/<run-dir> --tasks out/runs/<set>-all
```

Browse `D:\research\OSWorld\results_generated\...\<run>\index.html` on
Windows. Per task: a step player (prev/next, arrow keys, slider) with labeled
THINKING / ACTION / TOOL CALL / EXECUTED blocks per model call, taxonomy
chips, config/evaluator fold-out, recording link. Step numbers are per model
call; multi-action calls render as 11.1 / 11.2.

To hand the whole thing to someone: recompress the screenshots and zip
(`traj_bundle` pattern — JPEG bytes under the .png names, browsers sniff
content; ~30 MB for a 2,000-screenshot run, recordings excluded).

## 7 Health checks and concurrency red lines

```bash
ss -ltn | grep 18001                       # tunnel alive?
docker ps --format "{{.Names}}" | wc -l    # VM count
free -g                                    # available memory
grep -c "Failed to get screenshot" logs/rollout-<set>.log   # rising = memory pressure
```

Memory red lines (measured, 19 GB total):

| mix | verdict |
|---|---|
| rollout × 3 VMs (exclusive) | safe — the standard configuration |
| rollout × 2 + control × 1 | **screenshot 500s, tasks die silently** (measured 2026-08-09) |
| control × 3 (exclusive) | safe |

**Runner memory creeps.** With preserve-thinking the runner processes grow by
several GB over ~5 hours (context history handling); available memory decays
from ~7G to ~3G and screenshot-500s begin. The fix is the recovery mechanism
itself: kill the runner and its containers, relaunch with the same
--result_dir — memory resets, scored tasks are skipped, and every casualty
re-runs in the same stroke.

Screenshot-500 symptom: `Failed to get screenshot. Status code: 500` followed
by `TypeError: a bytes-like object is required` in the runner log — the task
has no result.txt; heal it with the §5 same-result_dir relaunch.

**A SIGTERM'd runner dies slowly.** Graceful cleanup (stop recordings, tear
down containers) can run for tens of minutes — the whole time still matching
`pgrep -f run_multienv_qwen.py`, which stalls anything waiting on runner
death (the autolaunch heal loop). Bound the wait (~5 min), then `pkill -9`
and `docker stop` the leftovers yourself.

Slurm serving chain: the vLLM job self-renews every 24 h (USR1 → successor,
14-link cap). Each handoff is a ~5–10 minute service gap; up to num_envs
in-flight tasks abort and are healed by the §5 relaunch.


## 质量审计三命令(固化,2026-08-17;全部为元数据不做过滤)

```bash
# 0) 规则层(构建前自动跑,census 含 think 长度分层报告)
$P -m ostg.sft.census RESULT_DIR

# 1) 步级 judge 审计(前后截图证据;--targets 供 quarantine 清单,--strata terminal,recovery)
$P -m ostg.sft.stepaudit RESULT_DIR --tasks TASKS_DIR --strata terminal,recovery --out stepaudit.jsonl

# 2) 轨迹级盲评 0-10 + judge 校准考试(judge 不见 checker 真值)
$P -m ostg.sft.trajaudit RESULT_DIR --tasks TASKS_DIR --out trajaudit.jsonl
$P -m ostg.sft.trajaudit --report trajaudit.jsonl   # AUC/分离度/混淆/分域
```

### 数据完整性四道门(2026-08-17 固化,ostg@1df5c975)

按流水线顺序,任一门失败即停:

| # | 门 | 在哪 | 查什么 |
|---|---|---|---|
| 1 | **merge slug 门** | `ostg.taskgen.merge` | 合并分片时拒绝重复 slug(**冲突的诞生地**) |
| 2 | **census slug 门** | `ostg.sft.census --tasks` | 构建前打印池级 slug 唯一性(`SLUG-COLLISION` 行) |
| 3 | **build 唯一化** | `ostg.sft.build` | 冲突 slug 的图片目录加 task_id 后缀;`report.json` 记 `slug_collisions` |
| 4 | **verify 交叉引用** | `ostg.sft.verify` | 图片存在且非空 **+ 任一图片目录被两个 task_id 引用即硬失败** |

`pipeline.sh` 已自动串起 2→3→4(`set -e`,任一门失败中止)。
体检历史语料:`for d in out/sft-*/; do $P -m ostg.sft.verify $d; done`。

**原则**:存在性检查 ≠ 正确性检查。凡拿业务字段当文件路径,写入层就要假定
冲突会发生(唯一化 + 事后交叉引用),不能依赖上游保证唯一。

judge 端点默认打教师 serve(:18020 隧道);运行前 source OSWorld/.env。
judge 未过校准考试(report 的 AUC/分离度)前,其分数不得用于任何过滤或加权。

### v2 rubric 与仲裁(2026-08-17 晚,v1 考试后加装;代码 557e170b)

```bash
# 轨迹级 v2:结构化 prompt(标号帧、截图>自述规则、temp0、本地 judge 走 guided_json)
$P -m ostg.sft.trajaudit RESULT_DIR --tasks TASKS_DIR --rubric v2 --out t2.jsonl
# v2req:先拆 requirement(六档 status+指认证据帧/步)再打分;脚本反算 derived 分
$P -m ostg.sft.trajaudit RESULT_DIR --tasks TASKS_DIR --rubric v2req --out t2r.jsonl
$P -m ostg.sft.trajaudit --report t2r.jsonl --score-field j_derived   # 用推导分复算校准

# 仲裁(assisted 二阶段):对 checker-vs-judge 分歧集亮出 evaluator 配置,
# Opus5 开 thinking 裁决谁错(checker_right_judge_fooled / checker_bug_lenient
# / checker_bug_strict / ambiguous)。产出 checker 缺陷清单,仍是元数据。
$P -m ostg.sft.arb RESULT_DIR --tasks TASKS_DIR \
  --qwen trajaudit.jsonl --opus trajaudit_opus.jsonl --out arb.jsonl
```

- `--rubric v1` 是默认且与 8-17 考试逐字节一致,复跑可复现;v2 系列另起 --out,不覆写 v1。
- 盲评(trajaudit)永不见 checker;仲裁(arb)专职分歧集,故意亮 checker——两阶段不可混。
- 长跑必须由持住 ssh 的后台任务驱动;瞬时 ssh + nohup 会被 WSL 掐死(8-17 实测,连日志都不落)。
- `--effort`(qwen 后端)默认 low = 实测最优;medium 实测**降** AUC(.774→.698,
  自我说服效应),别调高。qwen 后端 v2* 问卷自动换"只回一个 JSON"契约
  (无工具通道,serve 静默忽略 guided_json)。
- **生产判官政策(08-17)**:全池扫描 = Qwen v2req low(免费、并发 10);
  Opus 只精判嫌疑区/仲裁(付费,勿全池 req 扫);新判官/新问卷上岗前
  必须与 v1 基线同卷比 AUC。error 行不计分,补跑前先从 jsonl 剥掉
  error 行(resume 会把 error 当已完成跳过)。

### 筛选四步全流水(2026-08-17 固化,ostg@dbb0d892)

```bash
# ① 全池判官(生产问卷 v2req,本地 27B,10 并发)
$P -m ostg.sft.trajaudit RESULT_DIR --tasks TASKS_DIR --rubric v2req \
   --effort low --workers 10 --out out/trajaudit2req_POOL_qwen.jsonl

# ② 流式仲裁:判官边跑边裁,不等收卷(每 INTERVAL 秒一遍,断点续传)
POOL=v11500 RESULT_DIR=... TASKS=... \
QWEN=out/trajaudit2req_v11500_qwen.jsonl OPUS=out/trajaudit_v11500_opus.jsonl \
  bash ostg/sft/tools/arb_stream.sh          # 前台跑;nohup+瞬时 ssh 会被 WSL 杀

# ③ 三张名单(纯读,原始轨迹零改动)
$P -m ostg.sft.curate --traj J1.jsonl [--traj J2...] --arb arb.jsonl \
   --step S1.jsonl [--step S2...] --out-prefix out/curate_POOL

# ④ tier2 复核:把"过了但被标瑕疵"的轨迹送仲裁定罪(非分歧也强制裁)
$P -m ostg.sft.arb RESULT_DIR --tasks TASKS_DIR --targets out/curate_POOL_tier2.jsonl \
   --qwen J1.jsonl --out out/arb_POOL.jsonl    # 裁完回到 ③ 重出名单
```

### 终止规范化(Bhqs-2-terminal 起,2026-08-17)

```bash
# ① 教师重写末步理由 + 确定性拼 terminate;auto 尾巴策略只截真空转
#    --tasks 传 run 目录(load_instruction 自己拼 examples/,别传到 examples)
#    --backend anthropic 时 **必须** 给 --model claude-opus-5:
#    anthropic_cfg 原样透传模型名,漏传会静默返回空理由
$P -m ostg.sft.terminalfix RESULT_DIR --tasks TASKS_DIR \
   --targets out/final_POOL_keep.jsonl --targets out/final_POOL_rescue.jsonl \
   --endpoint http://127.0.0.1:18020/v1 --workers 8 \
   --tail-policy auto --stall-min 2 --out out/terminal_POOL.jsonl

# ①b 尾巴策略改过之后(不要删档重跑):只重算 keep_to,
#     位置没动的行保留教师原文,动了的 / 理由为空的才回炉
cp -n out/terminal_POOL.jsonl out/terminal_POOL.v1.jsonl     # 先留快照
$P -m ostg.sft.terminalfix RESULT_DIR --tasks TASKS_DIR \
   --targets out/final_POOL_keep.jsonl --targets out/final_POOL_rescue.jsonl \
   --out out/terminal_POOL.jsonl --recompute-tails \
   --backend anthropic --model claude-opus-5 --workers 6 \
   --tail-policy auto --stall-min 2

# ② build 接入重写(替换末步目标 + 按 keep_to 截尾)
$P -m ostg.sft.build RESULT_DIR --tasks TASKS_DIR --out OUT \
   --include ..._rescue.jsonl --exclude ..._drop.jsonl \
   --whole-traj-filter --think-cap 2048 --image-cache PRIOR \
   --terminal-rewrite out/terminal_POOL.jsonl

# ③ 出包前的终止形式硬门(只对规范化过的语料用)
$P -m ostg.sft.verify OUT --require-terminate

# ④ 语料审计:verify 查不了的那一半 —— 语料描述的还是 checker 验收的那条轨迹吗
$P -m ostg.sft.corpusaudit --corpus OUT_100 --corpus OUT_500 \
   --results-root /mnt/d/research/OSWorld/results_generated \
   --baseline PREV_ARM_100 --baseline PREV_ARM_500 \
   --harness /mnt/d/research/OSWorld --json out/audit_ARM.json --text
```
`--require-terminate` 检查每条轨迹的**末步目标必须解析出 `terminate` 且
status 非 failure**;散文兜底、`call_user`、terminate(failure) 一律 exit 1。
实测对未规范化的旧语料报 55 条不合格,对规范化后应为 0。
report.json 增 `terminal_rewritten` / `terminal_tail_truncated` 两个计数。

**截尾的硬门(2026-08-17 加,起因见 SFT_DATA.md)**:`decide_keep_to()` 在启发式
提出切点之后,强制比对**终止步截图与原末步截图的 md5**;不一致就整条退回
last-only 并记 `tail_gate="reverted"`。checker 打分打的是原末步的状态,
所以只有画面逐字节相同时截尾才是可证安全的。**启发式可以错,硬门不该缺。**

**`corpusaudit` 八项检查**:composition / ending_form / infeasible /
images / coverage / tail_safety / invariance / justification,任一 FAIL 则
exit 1。它读**原始轨迹**,所以比 verify 慢得多(约 3-5 分钟/臂),定位在
build 之后、ship 之前跑一次,不进每次 build 的快路径。
**轨迹定位一律按 `meta['run']` 并用 `orig_steps` 校验步数**——同一 task_id
在多个 model/run 下都存在且轨迹完全不同,按 task_id 瞎找会得出假结论。

**为什么要做**:harness 把"没有工具调用"直接判 DONE
(`actions.py: if not pyautogui_code: append(DONE)`),于是 72% 的轨迹用散文
结束、13% 用 `call_user` 结束,显式 `terminate` 只占 15%。4B 学生在 SFT 前
eval-50 上 **100% 显式终止,SFT 后 0%**,撞上限 28%→34%。**停止是我们监督
最少、而且被教成负动作的信号。**

**为什么不用固定模板**:319 条逐字节相同的 response 会占语料 6%,模型学到的
是背诵那句话。教师按各自任务写 ≤60 词的确认,动作部分才由脚本确定性拼接。

产物语义:`_rescue`(checker 冤案 → 候选**加入**语料)、`_drop`(仲裁坐实
假 pass → 候选**移出**)、`_tier1`(干净 pass = 一等品)、`_tier2`(pass 但
有瑕疵标记 → 送 ④,**不得仅凭判官怀疑丢弃**)、`_report.json`(计数/标记
清单/分域)。**权限铁律:判官提名、仲裁定罪**——只有仲裁裁决能让轨迹越过
checker 划的线;`checker_right_judge_fooled` 会清掉它审过的 judge_low 标记
(至今 6/6 该方向都是判官错)。名单是候选,建语料仍走 stage+swap+snapshot。
