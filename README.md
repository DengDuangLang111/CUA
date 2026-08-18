# ostg / CUA

LLM-generated OSWorld desktop tasks whose successful teacher rollouts become
SFT data for a small student model. This repo is the **documentation capital
and dashboard** of the project; canonical taskgen *code* runs from the WSL
ostg repo (branch v11.1 = main), of which `taskgen/` `sft/` `llm.py` here are
a synced copy.

Start here, then follow the router in `CLAUDE.root.md` §5 (the same file the
top-level CLAUDE.md imports into every agent session).

## Repo map

| where | what | doc |
|---|---|---|
| `taskgen/` | generation pipeline (taxonomy → gen → accept/cull → ship → control) | `TASKGEN_PIPELINE.md` (design) · `RUNBOOK.md` (commands) |
| `sft/` | trajectory → training samples + verification | `SFT_DATA.md` · `sft/TRAINING.md` · `sft/CONTEXT.md` |
| `llm.py` | LLM client, Anthropic/OpenAI protocol adapter (claude* / qwen* auto-route) | — |
| `dashboard/` + `traj_html.py` | live rollout monitor (Vercel; pushed by WSL daemon) | `DASHBOARD.md` |
| `eval/` | frozen eval-50 task lists + the keepthink chat template (retired 2026-08-18 — it renders byte-identically to stock, see `sft/RESULTS.md` §5.7) | `sft/TRAINING.md` |
| `reference/` | frozen deep references (OSWorld-Verified / V2 runtime requirements, author-run forensics) | each file's header |
| `outdated/` | superseded historical docs | `outdated/README.md` |
| ledgers | `EXPERIMENTS.md` (what happened, status block on top) · `V11.md` · `taskgen/GIT_HISTORY.md` | — |
| ops | `OPS.md` (WSL mods, proxy, tunnel, resources, task-JSON semantics) | — |

Data and weights never enter this repo: SFT sets + checkpoints live on
Tillicum `/gpfs/scrubbed/jy050706/sft/`, raw trajectories on the lab machine
(`results_generated/`), task sources in `os-simple-taskgen-v8/out/runs/` (WSL).

## The generator in one screen (v11.1 lineage — current)

Every task is drawn at a coordinate in **intent × domain × difficulty ×
ambiguity (5 × 13 × 5 × 4 = 1300 cells)** with a **voice register** derived
per cell; the cell dictates what kind of task gets written and how its
instruction may speak. Axis definitions and quotas live in
`taskgen/taxonomy.py` (AMBIGUITY_MIX 10/30/30/30); measurements per version in
`EXPERIMENTS.md`.

Three grades, all judged by stock OSWorld machinery:

    probe    (default) setup + a python3 probe in the VM printing PASS/FAIL;
             vm_command_line + check_include_exclude
    table    spreadsheet cells: the .xlsx is pulled out and check_cell rules
             run on the host (openpyxl); vm_file + compare_table, no gold file
    browser  browser_tab cells: where Chrome ended up;
             active_url_from_accessTree + is_expected_url_pattern_match

Nothing is built on the host and nothing is uploaded; the task JSON is the
whole task. Graders stay exact at every ambiguity level; gates enforce the
register mechanically (a path in an ambiguity≥2 instruction rejects the spec).

## Pipeline

    gen  →  ship (re-emit + accept gates [+ cull] + scan)  →  control (VM)  →  rollout

Commands with real paths: `RUNBOOK.md`. Stage design and what each layer can
and cannot see: `TASKGEN_PIPELINE.md`. When accept FAILs, `taskgen/cull.py`
is the mechanical remedy (greedy keep-earlier + reference-corpus contamination;
dry-run first, `--apply` leaves the audit trail in `specs_culled.jsonl`).

## OSWorld facts the emitter is built on

Verified against the OSWorld source, commit 091f5ef1:

- the expected getter reads `rules` — plural (`getters/misc.py:92`)
- `vm_command_line` returns raw stdout, so PASS arrives as `"PASS\n"`;
  `check_include_exclude` tolerates that and guards None, which also makes the
  evaluator unable to throw (an evaluator exception means NO result.txt and the
  task silently leaves the denominator)
- the VM's `/execute` endpoint kills commands at 120 s; `shell:true` is /bin/sh
- setup exit codes are never checked, and `until: {returncode: 0}` retries a
  permanently failing command forever — hence no `until`, and control.py
- an agent whose last action is FAIL scores 0 without the probe running

The full silent-failure catalogue of the harness (9 traps, ranked):
`OPS.md` §6.
