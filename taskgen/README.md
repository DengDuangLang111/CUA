# Task generation

The folders below organize the source snapshot in this repository. In particular, `generation/gen.py` is a historical adapter snapshot (2026-08-15): it is not the current v16 implementation, and this reorganization does not deploy it to Windows.

| Folder | Responsibility |
|---|---|
| [generation/](generation/) | Taxonomy, task generation, shipping orchestration and merging |
| [validation/](validation/) | Acceptance, static scans, VM controls, gold scripts and audits |
| [fixtures/](fixtures/) | Office-file preparation and concrete fixture builders |
| [analysis/](analysis/) | Coverage, evaluator families, task fit and fixture-type analysis |
| [prompts/](prompts/) | Checked-in prompt snapshots |
| [scripts/](scripts/) | Rollout/monitoring drivers and archived campaign scripts |
| [docs/](docs/) | Pipeline design and operations runbook |

Read [docs/PIPELINE.md](docs/PIPELINE.md) for design and [docs/RUNBOOK.md](docs/RUNBOOK.md) for version-specific procedures. [sft/docs/JUDGING.md](../sft/docs/JUDGING.md) covers rollout judging. The documented v16 `gen16.py`, `strongjudge.py` and `curate16.py` are not present in this local snapshot; use a verified live source for those implementations.

Generation calls validation and fixture helpers through their new packages. Shared API utilities remain at [llm.py](../llm.py). [analysis/taxonomy_tag.py](analysis/taxonomy_tag.py) is explicitly deprecated; it remains with its dependent historical analyses for reproducibility, while [family_census.py](analysis/family_census.py) owns the current recorded evaluator-family mapping.

The generator imports its environment loader, protocol selector, message/response conversion and stream assembly helpers from `llm.py`. Its request, retry and extraction policies remain local: they differ from the shared client's temperature and JSON-string recovery behavior. This cleanup shares identical helpers without changing those historical policies.

<!-- REPO NAV -->
[Repository map](../README.md)
<!-- /REPO NAV -->
