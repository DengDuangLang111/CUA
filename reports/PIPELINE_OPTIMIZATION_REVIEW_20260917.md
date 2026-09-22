# CUA capture / trajectory pipeline optimization review

Date: 2026-09-17. The measurements below are the original read-only review. The user subsequently authorized items 1–5; all five are now implemented and deployed. Current implementation, tests and live receipts: [deployment validation](pipeline-optimization-20260917/deployment-validation.json). Rollout/model settings remain unchanged; validated producer attention binaries are now cleaned according to the existing delete-after-export choice.

## Findings

The present bottleneck is a combination of single-worker postprocessing, single-file transfer queues, and retained producer copies. More rollout VMs do not directly increase the capacity of those stages.

Local and deployed hashes match for `retention.py`, `attention_download.py`, `visual_signals.py`, `vllm_capture.py`, and `after_task.py` on both Windows hosts. The findings therefore apply to the deployed implementation, not an unrelated local copy.

| Live observation | Workstation | Windows |
|---|---:|---:|
| Export queue | 31 processed / 12 pending / 1 waiting for attention | 17 processed / 1 pending |
| Oldest pending export age | about 76 min | about 4.3 min |
| Export-worker CPU | 95.7% of one CPU | 77.7% of one CPU |
| Export-worker RSS | about 404 MiB | about 273 MiB |
| Available WSL memory | about 27.0 GiB | about 10.0 GiB |
| Attention downloads queued/in progress | 132 + 1 | 13 + 1 |
| Declared sizes of queued files | about 7.36 GiB | about 3.35 GiB |
| Recent 30 downloads: bytes / summed transfer seconds | 4.84 MiB/s | 3.22 MiB/s |

Queue bytes include a downloading file's full declared size, not only its remaining bytes. Export delay includes queue wait, transfer wait, and processing; it is not pure render time. Snapshots change while the run continues. Full timestamps and module hashes are in [evidence.json](pipeline-optimization-20260917/evidence.json).

## Priority 1: Faster heatmap conversion and buffered JSON writes

Smallest useful code changes:

- `sft/analysis/retention.py::write_gzip_json`: retain streaming, atomic rename, fsync and read-back validation, but buffer encoded JSON using `io.TextIOWrapper` instead of passing each tiny encoder fragment directly to `GzipFile.write`.
- `HeatmapWriter.__call__`: use existing NumPy for float64 median/linear/logarithmic quantization. Keep PNG compression level 6, each row's round-trip check, hashes, and the same packed-file layout.

Offline Mac measurements, three JSON repeats and repeated heatmap trials:

| Component | Current | Prototype | Scope |
|---|---:|---:|---|
| 1.06 MB JSON write + gzip + read-back | 0.157 s | 0.095 s | Real 2-image / 275-output-token record |
| 8.46 MB JSON write + gzip + read-back | 1.073 s | 0.646 s | Real 10-image / 1,484-output-token record |
| 20,400-patch linear+log quantization | 4.10 ms | 0.40 ms | Real mean-attention weights |
| 40,800-patch linear+log quantization | 8.20 ms | 0.90 ms | Same real vector repeated to a 20-image shape |
| 40,800-patch quantization + PNG encode + decode check | 9.23 ms | 1.77 ms | Same PNG compression and verification |

The buffered JSON has identical decompressed bytes. Quantized pixels and level-6 PNG bytes matched exactly for the tested arrays. The complete tested heatmap substage was about 5.2× faster; this is **not** a 5.2× speedup of full rendering or evaluation. Full attention statistics, means, input validation, hashing, file I/O, and model inference were outside that timing.

Before deployment: repeat in the actual WSL Python environment; compare pixels on real per-token rows including zeros, tiny weights, maxima and rounding-boundary cases; compare full exported statistics and browser overlays. Preserve numerical image statistics exactly; do not blindly vectorize their summation with changed precision.

A lower PNG compression setting is less attractive for this storage-sensitive workflow: level 6 → 1 reduced the vectorized substage from 1.77 to 1.32 ms in the sample, but increased the PNG from 25,898 to 33,619 bytes (+29.8%). Keep level 6 first.

## Priority 2: Finish the storage lifecycle on Klone

`RenderedArchive.finalize` explicitly records `producer_cache="not managed; this policy only covers this task's local capture artifacts"`. `finish_cleanup` only deletes task-local Windows files. This is a scope gap, not a failed local delete operation.

The 17:42 storage snapshot attributes 100.95 GiB on Klone to 10/fold1 and 103.09 GiB to 20/fold10. These are source copies, not necessarily all immediately deletable. A further 106.33 GiB could not be assigned to those runs through returned artifact filenames.

Minimal design: extend the existing per-task retention receipt with producer artifact names and size/SHA; batch an explicit acknowledgement/cleanup step after the rendered artifact set and required source records pass validation. Reuse the `keep` and `delete-after-export` switches. No new database or distributed scheduler is needed.

Guards: require completed/immutable producer artifacts, a matching task/run receipt, size/SHA validation, complete verified renders, and no outstanding consumers/retries. Restrict paths to the configured producer spool. Keep raw files for incomplete/failed validation and keep-policy runs. Leave unattributed files untouched until attribution is established. An archive being small is not evidence that it is complete.

## Priority 3: Bounded concurrency where the queue is accumulating

`after_task.py::process_pending` holds a whole-output `.postprocess.lock` while rendering all tasks serially. `attention_download.py::download_one` similarly holds one host-queue worker lock during an entire transfer.

After Priority 1 is measured:

- Try **two export processes on Workstation**, retaining one on the smaller Windows host initially. Use one lightweight coordinator plus per-task ownership/locks; retain the existing short `.index.lock` for publication. Merely starting a second current worker does not help—it returns busy.
- Try **two concurrent artifact transfers per host**, with per-file locks and the existing resumable Range/size/SHA checks. This can reduce head-of-line blocking; higher total bandwidth is not guaranteed if the host link is already saturated.
- Keep explicit worker-count switches, bounded memory and disk reserve. Compare VM latency, export throughput, peak RSS, and queue age before raising concurrency further. Do not set concurrency equal to the VM count by default.

The observed Workstation queue and low render RSS make two render processes a plausible candidate, but a controlled WSL test is still required. Do not multiply the microbenchmark speedup by worker count to claim an end-to-end gain.

## Priority 4: Resume rendering at a verified decision boundary

Before task-level finalization there is no reusable per-decision receipt. A retry can recompute already finished heatmap decisions and rebuild the text archive. Add a small completion record to existing per-decision artifacts keyed by request ID, response hash, collector version and rendering configuration. Reuse only complete hash-verified records, never `.tmp` files. Preserve the final task-wide integrity gate.

This is a reliability/avoid-rework improvement. Its present frequency and full-run speed benefit have not been measured, so it follows the two small measured changes.

## Other issues to track separately

- Repeated long API requests need timeout/cancellation tracing. Before changing retry policy, verify whether timed-out server requests are actually cancelled. This review does not establish duplicate GPU work. Avoid changing token limits or collected attention scope as a substitute for diagnosis.
- Native `Error` rows and actual action rows need distinct display/validation treatment. Keep original error evidence; never invent an after screenshot or silently turn incomplete captures into passed validation to enable cleanup.
- Partial metadata from interrupted-task exports can overwrite richer run arguments and split a previously merged catalog group. Preserve authoritative run-level provenance when adding task-level exports. The existing refresh-index recovery is documented, but an import-time regression test would be better.
- The Mac viewer's SSH autoreconnection is now configured. That fixes visibility of new results, not rollout throughput.

## Proposed implementation order

1. Buffered JSON + NumPy heatmap conversion; preserve all data and output formats.
2. Repeat targeted benchmarks and artifact/GUI equivalence checks in WSL.
3. If render backlog remains, enable bounded two-process Workstation exports and measure interference.
4. Complete receipt-based Klone source cleanup; preserve both retention modes.
5. Add two-download concurrency only after a bounded throughput test; then decision-level resume if retries justify it.

These can mostly be introduced in the postprocessing path without changing model generation or VM trajectories. Deploy at a task boundary so the active exporter finishes its current transaction. The original review proposed this boundary; deployment subsequently completed at that boundary on both hosts (see validation link above).

## Reproduction

`pipeline-optimization-20260917/benchmark.py` takes saved rendered signal JSON records and an output filename. It uses temporary files and does not modify the source records:

```sh
python3 reports/pipeline-optimization-20260917/benchmark.py \
  /path/to/small-signal.json /path/to/large-signal.json \
  --output /tmp/cua-pipeline-benchmark.json
```

The evidence JSON retains actual local component timings, PNG sizes, live queue snapshots, transfer samples, and deployed module hashes. Input samples used in this audit were the already saved real example records, not a new model evaluation.


## Implementation and deployment follow-up

All five user-approved changes are active: buffered JSON, vectorized heatmap quantization,
receipt-driven producer cleanup, bounded export/download concurrency, and verified decision-level resume.
Workstation uses two export processes and two download threads; Windows uses one export process and
two download threads. The native eval controllers retained their PID and start-time identities.
Only the page worker was replaced after its then-current task completed. An old worker's intentional
SIGTERM may remain in `export-error.json`; the deployment receipt and successful new exports record recovery.

Local pipeline tests: 55/55; eval orchestration tests: 10/10. On each WSL: 55 run, 54 passed and one
Node-dependent browser test skipped (passed on Mac). Real old/new heatmap packs were byte-identical.
The warmed full writer test over the same 24 rows, including PNG round-trip and durable writes, was
0.3031 → 0.0849 s on Workstation and 0.1917 → 0.0565 s on Windows. NumPy cold import adds startup
cost; these figures do not measure full eval or complete task exports.

New real task exports on both hosts passed capture validation, retained-artifact hash checks and
created resume manifests. Browser inspection confirmed actual UI screenshots, mean and single-token
heatmaps, and exact image-level statistics in a newly exported Windows task. Producer cleanup is
active and acknowledged by Klone; producer JSONL metadata, unknown files and failed/unfinalized tasks
remain. See the timestamped JSON for recovered bytes and queue state rather than treating this note
as a live counter. Operational examples are in [TRAJECTORY_PIPELINE](../sft/docs/TRAJECTORY_PIPELINE.md#bounded-postprocessing)
and [EVAL_AUTOMATION](../sft/docs/EVAL_AUTOMATION.md#postprocessing-settings-for-the-next-evaluation).
