"""Create a non-destructive SWE-MeM-style weighted copy of an SFT build.

This reproduces the rollout-level normalization in SWE-MeM Eq. (3) as closely
as stock ms-swift's per-message ``loss_scale`` permits:

1. Keep every existing step-prefix row and the existing ``last_round`` mask.
2. Count all supervised target tokens belonging to each trajectory.
3. Give every target response in a trajectory one scalar weight so the total
   weighted token mass of every trajectory is the corpus mean.
4. Write new Swift JSONL files in a new directory. The source build and its
   images are never changed; output image paths are absolute references to the
   source images.

The final ``<|im_end|>\n`` suffix is not covered by ms-swift's per-message
loss_scale. Its token count is included analytically when solving for each
trajectory's response-body weight, so total weighted token mass remains equal.

Example on the training host:

    python -m ostg.sft.experiments.swe_mem.prepare_copy \
      /gpfs/scrubbed/jy050706/sft/data/mixB-swemem \
      --source-dir /gpfs/scrubbed/jy050706/sft/data/v16-main \
      --source-dir /gpfs/scrubbed/jy050706/sft/data/v16-pilot \
      --source-dir /gpfs/scrubbed/jy050706/sft/data/v11new-500 \
      --source-dir /gpfs/scrubbed/jy050706/sft/data/v11new-all \
      --tokenizer /gpfs/scrubbed/jy050706/sft/models/Qwen3.5-9B

The copied training arm MUST add ``--is_binary_loss_scale false``. Without it,
ms-swift silently collapses these non-binary weights back to ordinary labels.
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
from pathlib import Path

if __package__:
    from ...data.to_swift import convert
else:  # Keep the existing standalone CLI usable outside an installed ostg package.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from sft.data.to_swift import convert


def trajectory_key(sample):
    meta = sample.get("meta") or {}
    key = (meta.get("run"), meta.get("domain"), meta.get("task_id"))
    if key[2]:
        return key
    fallback = meta.get("slug")
    if fallback:
        return (key[0], key[1], fallback)
    raise ValueError("sample has no meta.task_id or meta.slug")


def to_swift(sample, source_dir, weight):
    """Reuse ordinary serialization; only paths and the target weight differ."""
    row = convert(sample)
    if "images" in row:
        row["images"] = [str((source_dir / path).resolve()) for path in row["images"]]
    row["messages"][-1]["loss_scale"] = weight
    return row


def response_token_count(tokenizer, response):
    return len(tokenizer.encode(response or "", add_special_tokens=False))


def solve_weights(group_body_tokens, group_rows, suffix_tokens):
    """Return weights making every trajectory's weighted token mass equal.

    ms-swift applies a message-level loss_scale to the assistant response body
    but leaves the suffix tokens at weight 1. If trajectory i has B_i body
    tokens and R_i response rows, choose

        w_i = (mean_total - R_i * suffix_tokens) / B_i

    where mean_total is mean(B_i + R_i * suffix_tokens) across trajectories.
    Then ``w_i * B_i + R_i * suffix_tokens == mean_total``.
    """
    totals = {
        key: group_body_tokens[key] + group_rows[key] * suffix_tokens
        for key in group_body_tokens
    }
    mean_total = statistics.fmean(totals.values())
    weights = {}
    for key, body_tokens in group_body_tokens.items():
        if body_tokens <= 0:
            raise ValueError(f"trajectory {key!r} has no supervised response-body tokens")
        suffix_mass = group_rows[key] * suffix_tokens
        numerator = mean_total - suffix_mass
        if numerator <= 0:
            raise ValueError(
                f"trajectory {key!r} suffix mass {suffix_mass} exceeds target mass {mean_total}")
        weights[key] = numerator / body_tokens
    return weights, totals, mean_total


def prepare_rows(samples, tokenizer, suffix_tokens):
    groups = collections.OrderedDict()
    body_counts = collections.Counter()
    row_counts = collections.Counter()
    for sample in samples:
        key = trajectory_key(sample)
        groups.setdefault(key, []).append(sample)
        body_counts[key] += response_token_count(tokenizer, sample.get("response", ""))
        row_counts[key] += 1

    weights, totals, mean_total = solve_weights(body_counts, row_counts, suffix_tokens)
    audit = []
    for key, rows in groups.items():
        weight = weights[key]
        weighted_mass = weight * body_counts[key] + row_counts[key] * suffix_tokens
        steps = [int((row.get("meta") or {}).get("step") or 0) for row in rows]
        audit.append({
            "run": key[0],
            "domain": key[1],
            "task_id": key[2],
            "rows": row_counts[key],
            "min_step": min(steps),
            "max_step": max(steps),
            "response_body_tokens": body_counts[key],
            "suffix_tokens": row_counts[key] * suffix_tokens,
            "unweighted_target_tokens": totals[key],
            "loss_scale": weight,
            "weighted_target_mass": weighted_mass,
        })
    return groups, weights, audit, mean_total


def load_jsonl(path):
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: {exc}") from exc
    return rows


def write_split(source_dirs, output_dir, tokenizer, suffix_tokens, src_name, dst_name):
    samples = []
    sample_sources = {}
    key_sources = {}
    source_files = []
    for source_dir in source_dirs:
        src = source_dir / src_name
        if not src.is_file():
            continue
        source_files.append(str(src.resolve()))
        for sample in load_jsonl(src):
            key = trajectory_key(sample)
            prior_source = key_sources.setdefault(key, source_dir)
            if prior_source != source_dir:
                raise ValueError(
                    f"trajectory {key!r} occurs in both {prior_source} and {source_dir}")
            samples.append(sample)
            sample_sources[id(sample)] = source_dir
    if not samples:
        return None
    groups, weights, audit, mean_total = prepare_rows(samples, tokenizer, suffix_tokens)

    output_paths = {
        source_dir: output_dir / f"{source_dir.name}_{dst_name}"
        for source_dir in source_dirs
        if (source_dir / src_name).is_file()
    }
    handles = {
        source_dir: path.open("w", encoding="utf-8")
        for source_dir, path in output_paths.items()
    }
    try:
        for sample in samples:
            key = trajectory_key(sample)
            source_dir = sample_sources[id(sample)]
            handles[source_dir].write(json.dumps(
                to_swift(sample, source_dir, weights[key]), ensure_ascii=False) + "\n")
    finally:
        for handle in handles.values():
            handle.close()

    audit_path = output_dir / f"{Path(src_name).stem}_trajectory_weights.jsonl"
    with audit_path.open("w", encoding="utf-8") as handle:
        for row in audit:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    values = [row["loss_scale"] for row in audit]
    masses = [row["weighted_target_mass"] for row in audit]
    max_abs_error = max(abs(value - mean_total) for value in masses)
    return {
        "sources": source_files,
        "outputs": [str(path.resolve()) for path in output_paths.values()],
        "audit": str(audit_path.resolve()),
        "rows": len(samples),
        "trajectories": len(groups),
        "suffix_tokens_per_row": suffix_tokens,
        "mean_unweighted_target_tokens_per_trajectory": mean_total,
        "loss_scale_min": min(values),
        "loss_scale_median": statistics.median(values),
        "loss_scale_max": max(values),
        "weighted_target_mass_min": min(masses),
        "weighted_target_mass_max": max(masses),
        "max_abs_equalization_error": max_abs_error,
    }


def build_tokenizer(path):
    try:
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise SystemExit("transformers is required; run this inside the training venv") from exc
    return AutoTokenizer.from_pretrained(path, trust_remote_code=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--source-dir", type=Path, action="append", required=True,
                        help="source build directory; repeat for every MixB component")
    parser.add_argument("--tokenizer", required=True,
                        help="Qwen3.5 model/tokenizer path used by the training arm")
    args = parser.parse_args(argv)

    sources = [path.resolve() for path in args.source_dir]
    output = args.output_dir.resolve()
    if output in sources:
        raise SystemExit("refusing to overwrite a source build")
    if len(set(sources)) != len(sources):
        raise SystemExit("duplicate --source-dir")
    missing = [source / "samples.jsonl" for source in sources
               if not (source / "samples.jsonl").is_file()]
    if missing:
        raise SystemExit("missing source files: " + ", ".join(map(str, missing)))
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)

    tokenizer = build_tokenizer(args.tokenizer)
    suffix_tokens = len(tokenizer.encode("<|im_end|>\n", add_special_tokens=False))
    if suffix_tokens <= 0:
        raise SystemExit("tokenizer produced no assistant suffix tokens")

    train_report = write_split(
        sources, output, tokenizer, suffix_tokens,
        "samples.jsonl", "train_swift_abs.jsonl")
    val_report = write_split(
        sources, output, tokenizer, suffix_tokens,
        "val_samples.jsonl", "val_swift_abs.jsonl")
    report = {
        "method": "SWE-MeM Eq. (3) rollout-level target-token normalization",
        "source_dirs": [str(source) for source in sources],
        "tokenizer": str(args.tokenizer),
        "production_source_modified": False,
        "images_copied": False,
        "image_policy": "absolute read-only references to source build images",
        "required_training_arg": "--is_binary_loss_scale false",
        "train": train_report,
        "validation": val_report,
    }
    (output / "swemem_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "SOURCE_DIRS.txt").write_text(
        "\n".join(str(source) for source in sources) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
