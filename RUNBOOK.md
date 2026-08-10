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
  setsid nohup $P -m ostg.gen --n 5 --batches 13 --seed <S> --shard $i/2 --stream     --model claude-opus-5 --env $TG/.env     --out $TG/out/runs/<set>-s$i/specs.jsonl     --avoid-corpus /mnt/d/research/cua-gym/tasks.jsonl     > $TG/logs/<set>-s$i.log 2>&1 &
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
PYTHONPATH=. $P -m ostg.ship out/runs/<set>-s0 out/runs/<set>-s1 \
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
PYTHONPATH=. $P -m ostg.merge out/runs/<set>-s0 out/runs/<set>-s1 --out out/runs/<set>-all
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
  setsid nohup env PYTHONPATH=.:$OW $P -m ostg.control \
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
PYTHONPATH=. $P -m ostg.audit out/runs/<set>-s0/specs.jsonl [...] \
  --out out/runs/audit-<set>.jsonl --model claude-sonnet-4-6 --stream

# 2) gold scripts (API only; the answer key must be computed accurately)
PYTHONPATH=. $P -m ostg.gold out/runs/<set>-s0/specs.jsonl [...] \
  --out out/runs/gold-<set>.jsonl --model claude-opus-5 --stream

# 3) gold injection (VM; control's mirror mode: must score 1.0 after injection)
PYTHONPATH=.:$OW $P -m ostg.control --tasks out/runs/<set>-all \
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
