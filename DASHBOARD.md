# The dashboard — what every run must show

https://cua-dashboard-theta.vercel.app · source `dashboard/index.html`,
published from `main` (Vercel's production branch), live numbers written by two
daemons on the lab machine (§4).

**The rule this file exists for: a new run is not "on the dashboard" until it
shows everything the v11 entry shows.** v11 is the reference layout. Adding a
run means filling in the same sections with that run's evidence — not a
reduced version, and not waiting to be asked.

The site covers two halves of the project. **Task generation** (sidebar groups
Current / Baseline / v8 era / Corpus-only / Early) is one view per rollout.
**SFT** (§4) is three views — Overview, Tier-3 Panel, Training runs — and the
same rule applies to it: an arm is not on the dashboard until its nine tasks
are watchable, not merely counted.

---

## 1 The seven sections of a run entry

Copy the v11 / v11-500 entry and fill each in. Order is fixed, because it
reads top-down as "what happened → under what conditions → why you should
believe it".

| # | Section | Content | Source |
|---|---|---|---|
| 1 | **Results so far** | pass rate with (passed/scored of corpus), then one card per domain | live `status.json` |
| 2 | **Conditions** | corpus · generator · max steps · thinking mode · temp/top-p · sleep · envs · screen · result dir | the runner command |
| 3 | **How the corpus is designed** | coordinate draw, difficulty ladder, ambiguity mix, warm start, voice, repair pipeline | spec counts |
| 4 | **Pre-run verification** | one row per layer: scope + what it caught or removed | ship + control logs |
| 5 | **Similarity & contamination** | jaccard · cosine · vs CUA-Gym · vs official-361 · quota drift, each with its gate | `ostg.taskgen.accept` |
| 6 | **Domain mix** | task counts per application and per grading route | manifest |
| 7 | **Trajectories tab** | embedded step player + full-screen link | `ostg.traj_html` |

A run that is finished keeps the same layout; only the pills change
(`live` → `complete N/N`) and any incident worth remembering gets its own
table (see v11's calc incident).

## 2 The live half

`status.json` is the only moving part. The daemon recomputes it every 5
minutes and pushes to `main`; Vercel redeploys; the page re-fetches every 2
minutes, so an open tab updates itself.

Per run the daemon publishes:

```json
"v11_500": {"corpus": 444, "control_checked": 441, "control_bad": 0,
            "scored": 6, "passed": 4,
            "domains": {"chrome": [passed, scored], ...}}
```

Adding a run to the daemon = one more block computed from its result
directory. Keys are read by the page's `design:()` function through
`window.LIVE.<key>`.

Trajectories are heavier: the daemon regenerates them for the **active run
only**, at most every 30 minutes (rebuilding hundreds of megabytes of
screenshots on every 5-minute cycle once starved the push loop and stalled
the whole site). A finished run's viewer is frozen where it is and never
regenerated.

## 3 The SFT half

Three views under the **SFT** group, all fed by `dashboard/sft.json`:

| view | what it is | moving parts |
|---|---|---|
| **Overview** | the story: the regression, the epoch lever, what was ruled out and on what evidence | headline cards read live arm counts |
| **Tier-3 Panel** | the arbiter — every arm on the identical 9 held-out tasks | fully live: arm table, task × arm matrix, trajectories |
| **Training runs** | recipe, runs in flight, the annealing caveat | hand-written |

**The matrix is the point.** Rows are arms, columns are the nine tasks, and
every cell links into that arm's own step player for that task — so an SFT eval
is watchable exactly like a taskgen rollout, at single-task granularity. The
cell shows pass/fail + step count; the tooltip carries distinct-action count,
longest repeated action, and whether the run ever emitted `terminate`.

`sft.json` per arm:

```json
{"key":"q35-e3","label":"e3","group":"fixed data","data":"abs-pilot2",
 "samples":916,"epochs":3,"preserve":"true","passed":3,"scored":9,
 "term":4,"capped":5,"traj":"traj/sft/q35-e3/index.html",
 "tasks":{"<task_id>":{"score":1.0,"steps":19,"distinct":14,"maxrep":3,
                       "term":true,"dom":"chrome"}}}
```

Arms are labelled from a registry in `sft_dash.py`; the pipeline's
`q35-<run>-ep<k>` checkpoints are derived from a `FAMILY` table so a new epoch
snapshot needs no edit. **An unknown arm still appears**, labelled by its
directory name — an unlabelled row is a visible gap, a dropped row is an
invisible one.

### Why two daemons

`sft_dash_daemon.sh` works in a **second clone** (`cua-dash-sft`), sparse-checked
out so `dashboard/traj/v11*` — the 683 MB the other daemon owns — is not even
present. Two working trees, disjoint paths, two JSON files: neither can take the
other's `index.lock`, neither can clobber the other's keys, and a raced push
resolves as an ordinary rebase. Both reset to `origin/main` at the top of each
cycle and regenerate, so a reset can never lose anything.

### Publishing trajectories

A `.fingerprint` file (result count + newest `traj.jsonl` mtime) inside the
published directory decides:

- **complete arm** (all 9 scored) → published once and never again. A tier-3 arm
  is frozen the moment its ninth `result.txt` lands, unlike the live rollout.
- **arm still rolling** → refreshed at most every 30 minutes, so the arm the
  machine is currently running is watchable while it runs.
- **re-run of an arm** → fingerprint changes, republishes.

The 30-minute floor is not politeness, it is the same lesson as the rollout
viewer: **JPEGs do not delta-compress**, so republishing on every 5-minute cycle
adds the arm's full weight to git history each time. One arm at a time is
guaranteed by the 3-VM ceiling, so the throttle bounds the cost at ~4
republishes per arm.

Screenshots are recompressed (JPEG q30, 1000 px) **and then deduped by content
hash**, with the surviving filename substituted into `viewer.html`. This matters
more here than anywhere else on the site: a 50-step loop trajectory is ~50
near-copies of one screen, and the SFT panel is full of them. Measured on e3:
**352 files / 77 MB → 148 files / 4.5 MB.** Dedup must run *after* `traj_html`
writes the viewer, or the substitution has nothing to rewrite.

## 4 Hard-won rules

- **Push to `main`.** Vercel's production branch is `main`; pushes to any
  other branch produce Preview deployments that never reach the live URL —
  the site silently serves an old snapshot while every push "succeeds".
- **Never `git add -A` in this repo.** It has committed deletions of
  `.gitignore`/docs and added `__pycache__` binaries. Stage explicit paths.
- **The daemon must survive a bad cycle.** It runs `set +e`, force-syncs to
  the remote before writing (data is regenerated, so a reset loses nothing),
  and logs each stage so a death is diagnosable.
- **Count verdicts from the final corpus, newest re-check wins.** A raw
  control sweep can contain failures that a later re-check cleared; ordering
  the report files matters (`v11-500-recheck` sorts *before* `v500-all`,
  which silently reinstated stale verdicts once).
- **Corpus size = emitted tasks, not spec lines.** Gate-blocked specs stay
  in `specs.jsonl` but never become tasks.
