# SFT experimental arms

Experimental arms live here so that production builders, shipped datasets,
and existing training recipes remain unchanged. Every arm must document its
single intended variable, source-data hashes, output invariants, and rollback
path before it can launch a GPU job.

| Arm | Status | Intended variable | Entry point |
|---|---|---|---|
| `webstar_step_filter` | IMPLEMENTED / CALIBRATION PENDING | Which current target steps contribute SFT loss | [`webstar_step_filter/README.md`](webstar_step_filter/README.md) |

`CALIBRATION PENDING` means the offline pipeline and tests exist, but the
200-step o4-mini calibration has not run. Full grading, dataset ship, and GPU
training remain gated on that calibration and its manual review.
