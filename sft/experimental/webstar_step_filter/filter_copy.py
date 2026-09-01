"""Create immutable filtered Swift JSONL copies from final step decisions.

No images or source rows are modified. Output image references point to the
existing source dataset roots supplied via `--image-root NAME=PATH`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path

try:  # production checkout is imported as `ostg`; local worktree uses `sft`
    from ostg.sft.to_swift import convert as to_swift
except ModuleNotFoundError:  # pragma: no cover - environment-dependent import
    from sft.to_swift import convert as to_swift

from .audit_report import build_retention_report
from .common import (StepKey, has_explicit_done, iter_jsonl,
                     load_source_rows, parse_named_paths, sha256_file,
                     sha256_text)


def load_decisions(path):
    out = {}
    for row in iter_jsonl(path):
        key = StepKey.from_dict(row)
        if key in out:
            raise ValueError(f"duplicate final decision: {key.text()}")
        if row.get("decision") not in {"keep", "drop", "review"}:
            raise ValueError(f"invalid final decision: {key.text()}")
        out[key] = row
    return out


def validate_coverage(index, decisions, expected_rows=0):
    if expected_rows and len(index) != expected_rows:
        raise ValueError(
            f"source row invariant failed: expected {expected_rows}, got {len(index)}")
    missing = sorted(key.text() for key in index if key not in decisions)
    extra = sorted(key.text() for key in decisions if key not in index)
    if missing or extra:
        raise ValueError(
            f"decision coverage mismatch: missing={missing[:5]} extra={extra[:5]}")
    reviews = sorted(key.text() for key, row in decisions.items()
                     if row["decision"] == "review")
    if reviews:
        raise ValueError(f"unresolved review decisions: {reviews[:10]}")
    for key, source_row in index.items():
        decision = decisions[key]
        response_hash = sha256_text(source_row.sample.get("response", ""))
        if decision.get("source_response_sha256") != response_hash:
            raise ValueError(f"source response hash mismatch: {key.text()}")
        meta = source_row.sample.get("meta") or {}
        terminal = int(meta.get("step") or 0) == int(meta.get("n_steps") or -1)
        if terminal:
            if decision["decision"] != "keep":
                raise ValueError(f"terminal target is not kept: {key.text()}")
            if not has_explicit_done(source_row.sample.get("response", "")):
                raise ValueError(f"terminal target lacks explicit DONE: {key.text()}")


def _git_commit(cwd):
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def build_filtered_copy(source_dirs, decisions, image_roots, output_dir,
                        policy_path, expected_rows=0, decisions_path=None):
    index, source_reports = load_source_rows(source_dirs)
    validate_coverage(index, decisions, expected_rows)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise FileExistsError(
            f"filtered output must be a new empty directory: {output_dir}")
    outputs = {}
    counts = Counter()

    handles, temporary = {}, {}
    try:
        for name in source_dirs:
            out_path = output_dir / f"{name}_train_swift_abs.jsonl"
            temp_path = out_path.with_suffix(out_path.suffix + ".tmp")
            handles[name] = temp_path.open("x", encoding="utf-8")
            temporary[name] = temp_path
            outputs[name] = out_path
        for key in sorted(index):
            source_row = index[key]
            decision = decisions[key]["decision"]
            counts[decision] += 1
            if decision != "keep":
                continue
            swift_row = to_swift(source_row.sample)
            rewritten = []
            for image in swift_row.get("images", []):
                image_path = Path(image)
                local_path = (image_path if image_path.is_absolute()
                              else source_row.source_dir / image_path)
                if not local_path.is_file():
                    raise FileNotFoundError(
                        f"{key.text()}: source image missing: {local_path}")
                if image_path.is_absolute():
                    try:
                        relative_image = local_path.resolve().relative_to(
                            source_row.source_dir.resolve())
                    except ValueError as exc:
                        raise ValueError(
                            f"{key.text()}: absolute image is outside source "
                            f"build and cannot be remapped safely: {image_path}") from exc
                else:
                    relative_image = image_path
                remote_root = image_roots[key.source_build]
                rewritten.append(str(remote_root / relative_image))
            if rewritten:
                swift_row["images"] = rewritten
            handles[key.source_build].write(
                json.dumps(swift_row, ensure_ascii=False) + "\n")
    except Exception:
        for handle in handles.values():
            handle.close()
        for path in temporary.values():
            path.unlink(missing_ok=True)
        raise
    else:
        for handle in handles.values():
            handle.close()
        for name, path in temporary.items():
            path.replace(outputs[name])

    retention = build_retention_report(index, decisions)
    retention_path = output_dir / "retention_report.json"
    retention_path.write_text(json.dumps(retention, indent=2,
                                         ensure_ascii=False) + "\n",
                              encoding="utf-8")
    policy_out = output_dir / "FILTER_POLICY.json"
    shutil.copyfile(policy_path, policy_out)
    decisions_sha256 = None
    if decisions_path:
        decisions_out = output_dir / "step_decisions.final.jsonl"
        shutil.copyfile(decisions_path, decisions_out)
        decisions_sha256 = sha256_file(decisions_out)
    source_hash_lines = [
        f"{report['sha256']}  {name}/samples.jsonl"
        for name, report in sorted(source_reports.items())
    ]
    (output_dir / "SOURCE_FILES.sha256").write_text(
        "\n".join(source_hash_lines) + "\n", encoding="utf-8")

    output_reports = {}
    for name, path in outputs.items():
        with path.open(encoding="utf-8") as handle:
            row_count = sum(1 for _ in handle)
        output_reports[name] = {
            "path": str(path.resolve()),
            "rows": row_count,
            "sha256": sha256_file(path),
        }
    version = {
        "data_version": "mixB-webstar-filter-v1",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "code_commit": _git_commit(Path(__file__).resolve().parents[3]),
        "policy_sha256": sha256_file(policy_out),
        "decisions_sha256": decisions_sha256,
        "decision_counts": dict(sorted(counts.items())),
        "source_rows": len(index),
        "sources": source_reports,
        "outputs": output_reports,
        "retention_report_sha256": sha256_file(retention_path),
    }
    (output_dir / "DATA_VERSION.json").write_text(
        json.dumps(version, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return version


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True,
                        help="neutral build as NAME=DIR")
    parser.add_argument("--image-root", action="append", required=True,
                        help="training-visible existing image root as NAME=DIR")
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=Path(__file__).with_name(
        "policy_v1.json"))
    parser.add_argument("--expected-rows", type=int, default=18576)
    args = parser.parse_args(argv)

    source_dirs = parse_named_paths(args.source, "--source")
    image_roots = parse_named_paths(args.image_root, "--image-root")
    if set(source_dirs) != set(image_roots):
        raise ValueError("--source and --image-root names must match exactly")
    decisions = load_decisions(args.decisions)
    version = build_filtered_copy(
        source_dirs, decisions, image_roots, args.out, args.policy,
        args.expected_rows, args.decisions)
    print(json.dumps(version, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
