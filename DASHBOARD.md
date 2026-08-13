# The dashboard — what every run must show

https://cua-dashboard-theta.vercel.app · source `dashboard/index.html`,
published from `main` (Vercel's production branch), live numbers written by
`dash_status_daemon.sh` on the lab machine.

**The rule this file exists for: a new run is not "on the dashboard" until it
shows everything the v11 entry shows.** v11 is the reference layout. Adding a
run means filling in the same sections with that run's evidence — not a
reduced version, and not waiting to be asked.

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
| 5 | **Similarity & contamination** | jaccard · cosine · vs CUA-Gym · vs official-361 · quota drift, each with its gate | `ostg.accept` |
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

## 3 Hard-won rules

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
