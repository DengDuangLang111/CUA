# SFT experimental arms

Experimental arms live here so that production builders, shipped datasets,
and existing training recipes remain unchanged. Every arm must document its
single intended variable, source-data hashes, output invariants, and rollback
path before it can launch a GPU job.

| Arm | Status | Intended variable | Entry point |
|---|---|---|---|
| `webstar_step_filter` | DESIGN REVIEW | Which current target steps contribute SFT loss | [`webstar_step_filter/README.md`](webstar_step_filter/README.md) |

`DESIGN REVIEW` means that the protocol is versioned but no grading, dataset
rewrite, ship, or training job is authorized yet. The status changes only
after the open decisions in the arm README are resolved.
