# taskgen — versioned copies of the (unversioned) WSL generator

The executing copy lives at `/mnt/d/research/os-simple-taskgen-v8/ostg/` on
WSL, which is NOT a git repo (CLAUDE.md §8). Load-bearing files get copied
here after changes, same pattern as `control/`. Sync = push file + compare
md5 (CLAUDE.md §9).

> **SUPERSEDED 2026-08-15**: the archived `gen.py` below is the v8.4-era
> adapter build (used for the parked 325-spec run only). The production
> adapter lives in the ostg repo itself — branch v11.1 (= main),
> `ostg/llm.py` + `taskgen/generation/gen.py`, commits `dc9b35d9`/`190009be` — and the
> canonical invocation is that repo's RUNBOOK. This copy stays as history.

- `gen.py` — as of 2026-08-15: protocol adapter added. `--protocol
  auto|anthropic|openai` (auto: claude* → Anthropic `/v1/messages`, everything
  else → OpenAI `/v1/chat/completions`); OpenAI branch translates tools /
  tool_choice / responses back into the Anthropic shape so extract() and the
  retry loop are untouched; default regime for non-claude = enable_thinking
  false + forced tool_choice (the exact v11 production mechanism — verified
  against the gateway; thinking mode rejects forced calls on qwen AND
  anthropic alike); `--thinking` = thinking + auto. Claude path byte-identical
  (regression: 2/2 specs). WSL backup: `ostg/gen.py.bak-preqwen`.


## Additional historical reference retained from the former root README

<details>
<summary>Historical v11.1 generator reference (not the v16 design)</summary>

The material below describes the earlier generator. For v16 data preparation, use [sft/docs/DATA_PIPELINE_V16.md](../../sft/docs/DATA_PIPELINE_V16.md); for generation-version details, follow [taskgen/docs/PIPELINE.md](../../taskgen/docs/PIPELINE.md) and [taskgen/docs/RUNBOOK.md](../../taskgen/docs/RUNBOOK.md).

### The generator in one screen (v11.1 reference)

Every task is drawn at a coordinate in **intent × domain × difficulty ×
ambiguity (5 × 13 × 5 × 4 = 1300 cells)** with a **voice register** derived
per cell; the cell dictates what kind of task gets written and how its
instruction may speak. Axis definitions and quotas live in
`taskgen/generation/taxonomy.py` (AMBIGUITY_MIX 10/30/30/30); measurements per version in
`docs/EXPERIMENTS.md`.

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

### Historical v11 pipeline

    gen  →  ship (re-emit + accept gates [+ cull] + scan)  →  control (VM)  →  rollout

Commands with real paths: `taskgen/docs/RUNBOOK.md`. Stage design and what each layer can
and cannot see: `taskgen/docs/PIPELINE.md`. When accept FAILs, `taskgen/cull.py`
is the mechanical remedy (greedy keep-earlier + reference-corpus contamination;
dry-run first, `--apply` leaves the audit trail in `specs_culled.jsonl`).

### OSWorld facts checked for that emitter

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
`docs/OPS.md` §6.

</details>

<!-- REPO NAV -->
Archived record · [Repository map](../../README.md) · [Archive index](../README.md)
<!-- /REPO NAV -->
