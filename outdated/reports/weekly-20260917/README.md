# CUA Weekly Findings — September 17, 2026

Eleven-page English browser presentation at http://127.0.0.1:8797/.

From the CUA repository:

```sh
python3 -m http.server 8797 --bind 127.0.0.1 --directory reports/weekly-20260917
```

Pages 1–3 explain the question, experiment, and finding before the evidence: history compression, visual-signal examples and comparisons, then terminal-trained TMAX initialization followed by CUA SFT. TMAX domain changes are summarized in one sentence. Pages 4–11 cover eight real failure case types. Four additions show repetitive clicks, incorrect infeasibility handling, planning/step-budget exhaustion, and a command/evaluator mismatch. Each uses real screenshots and concise what/wrong/should explanations.

Previous / Next, arrow keys, full screen, and #1 through #11 are supported. Click cropped screenshots to see full originals. Evidence buttons expose source records; the attention examples include actual patch heatmaps and links to the original trajectory viewer. Source JSON and assets are local, so the presentation does not depend on the Windows hosts; full-trajectory links still require port 8793.

## Data and limits

- `evidence.json`: compression results, 99 matched TMAX/old-r5 scores, and two illustrative visual-signal decisions. One interrupted task is excluded, never assigned zero. The 20/fold10 follow-up is not included. Compression budget saving is an estimate for a full 10-image window.
- `attention-cohort.json`: all 99 task records and exclusions. Select nonterminal model step 10, exactly 10 images × 2,040 vision tokens, complete whole-output mean attention at L31/H0. There are 65 eligible tasks: 26 full passes and 39 non-full passes. 28 tasks ended before step 10 and six terminated at step 10. Each task contributes one observation. It is a selected longer-task cohort, not an unbiased all-task sample. Image entropy is H(share)/log(10); top-image share is max(share). Table values are task means. Current-image summary excludes unresolved source mappings. Exploratory bootstrap differences and the random seed are retained in the JSON; these do not establish causality.
- `failure-analysis.json`: captured actual/gold DOCX/XLSX structures, original evaluator code/results, actions/responses, and sampled step-level visual measurements. `failure-signals.json` retains the sampled signal summaries separately.
- `subscript-evidence.json`: original TMAX actions, evaluator outputs, and DOCX run properties. Text comparison passes; subscript comparison fails; the actual file has zero explicit subscript runs. The old-r5 screenshot is from its score-1 final trajectory. Screenshots have different original UI zoom levels; crops do not imply matching zoom.
- `assets/`: original screenshots and SHA-verified captured result/reference documents. Image crops and click/reference outlines use SVG and preserve original image files. They are not attention heatmaps.

Historical compression sources: actual result.txt files from MixB, MixB Terminal Fix, and histcomp; `sft/docs/RESULTS.md` sections 5.36 and 5.39; recipe in `sft/training/histcomp/sitecustomize.py`. TMAX initialization provenance: `sft/plans/PLAN-20260915-tmax9b-r5-cua-sft.md`.

The slides distinguish confirmed result mismatches from plausible failure patterns. Attention concentration is a diagnostic, not a correctness or causality test. Per-application tables and detailed metric inventories were removed from the presentation but source evidence remains inspectable.

## Browser review

All seven pages were inspected using computer-use interactions in the actual Codex browser at its normal 1127×934 viewport. Previous/Next and keyboard navigation, original-image zoom, and the focused-attention example were exercised. This caught cramped heatmap captions and footer overflow at this window height; caption spacing, compact-height layout, and the final case's note size were fixed and visually rechecked. The browser was returned to page 1.

## Visual-signal walkthrough and history-position ranking

Page 2 now has three views: a real decision walkthrough (capture → average raw attention over output tokens → sum patches per image → image-only normalization), the 65-task outcome cohort, and historical-position ranking. Link directly with `?signals=example#2`, `?signals=cohort#2`, or `?signals=rank#2`; switching views preserves the URL state.

The ranking uses one equally weighted step-10 decision per eligible task and input positions 1–9 (oldest to most recent history). Slot 10 is shown separately. Each value remains a share of all ten images; values are not renormalized among history images. Includes separate means for 26 full-pass and 39 non-full-pass tasks, and the count of times each slot has the largest historical share.

Re-read image IDs, attention-frame IDs, and source-step metadata on both hosts: all 65 vectors align with image-0 through image-9; known source steps match input order. 59 of 650 source-step labels are ambiguous; exact recorded input positions remain available, so these are retained without inventing source-step labels. Source metadata and all computed means are saved in `attention-cohort.json`.

## Broader failure coverage and speaking notes

`speaker-notes.md` provides a short English talk track and a Chinese explanation for Visual Signals. The page selector and Failure-mode coverage dialog link all eight case types. `additional-failure-evidence.json` retains actual responses, actions, evaluation inputs/results, and screenshot paths for the four added cases. `repetition-audit.json` records screening of all 48 non-full-pass tasks. Terminal and empty decisions are excluded from repetition motifs; WAIT-only candidates remain distinguished from actionable loops. Repetition is a screening heuristic, never an automatic causal label. The PDF-scrolling case made page progress and is presented as inefficient planning, not an unchanged-state loop. The conversion case failed a recorded command-history rule; PDF-content comparison short-circuited and functional equivalence is not claimed.

The four new case pages and the coverage dialog were visually checked through computer use in the actual browser.
