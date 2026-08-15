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

Batch losses are re-drawn by refill; check the tail of the log for the
closing axis summary.
## 2 Ship (accept gates)

```bash
PYTHONPATH=. $P -m ostg.taskgen.ship out/runs/<set>-s0 out/runs/<set>-s1 \
  --ref cua-gym=/mnt/d/research/cua-gym/tasks.jsonl \
  --ref osworld-361=$OW/evaluation_examples/examples
```

re-emit rebuilds every task JSON with the current emitter (older sets pick up
newer fixes), then runs the HARD/REVIEW gates (see README). **To cull a
duplicate**: move its line from `specs.jsonl` to `specs_culled.jsonl` in the
same run dir and re-run ship (keep the earlier-generated member of a pair).

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

Exits loudly on id collisions; sources are untouched. Re-merge after any cull.

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
