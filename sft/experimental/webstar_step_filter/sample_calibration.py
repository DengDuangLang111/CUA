"""Select a deterministic 200-step calibration panel from MixB sources.

Use `--source NAME=DIR` once per frozen neutral build. The real data-host paths
must be verified before running; this command deliberately has no guessed
defaults.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from .common import (action_signature, is_terminal_sample, load_source_rows,
                     parse_named_paths, sha256_text, stable_rank,
                     think_est_tokens)


RECOVERY_RE = re.compile(
    r"\b(previous|prior|last)\b.{0,80}"
    r"\b(mistake|wrong|incorrect|failed|did not|didn't|misclick)",
    re.IGNORECASE | re.DOTALL)


def classify_rows(index):
    info = {}
    by_traj = defaultdict(list)
    for key, source_row in index.items():
        by_traj[key.source_build, key.run, key.domain, key.task_id].append(
            source_row)

    for rows in by_traj.values():
        rows.sort(key=lambda row: row.key.step)
        signatures = [action_signature(row.sample.get("response", ""))
                      for row in rows]
        for pos, row in enumerate(rows):
            response = row.sample.get("response", "")
            repeated = pos > 0 and signatures[pos] == signatures[pos - 1]
            changed_after_repeat = (
                pos >= 2 and signatures[pos - 1] == signatures[pos - 2]
                and signatures[pos] != signatures[pos - 1])
            recovery = changed_after_repeat or bool(RECOVERY_RE.search(response))
            risky = repeated or signatures[pos] in {
                "wait", "call_user", "no_action_tag"
            }
            info[row.key] = {
                "terminal": is_terminal_sample(row.sample),
                "recovery": recovery,
                "risky": risky,
                "think_est_tokens": think_est_tokens(response),
                "action_signature": signatures[pos],
                "response_sha256": sha256_text(response),
            }
    return info


def _balanced_pick(candidates, count, seed, used):
    candidates = [key for key in candidates if key not in used]
    groups = defaultdict(list)
    for key in candidates:
        groups[key.source_build].append(key)
    for keys in groups.values():
        keys.sort(key=lambda key: stable_rank(key, seed))
    names = sorted(groups)
    picked = []
    while len(picked) < count:
        progressed = False
        for name in names:
            if groups[name] and len(picked) < count:
                picked.append(groups[name].pop(0))
                progressed = True
        if not progressed:
            raise ValueError(
                f"calibration stratum needs {count} unique rows, only "
                f"{len(picked)} remain")
    used.update(picked)
    return picked


def select_calibration(index, seed=20260831, random_count=100,
                       terminal_count=25, recovery_count=25,
                       long_count=25, risky_count=25):
    info = classify_rows(index)
    used, selected = set(), []

    def add(name, candidates, count, salt):
        picked = _balanced_pick(candidates, count, f"{seed}:{salt}", used)
        selected.extend((key, name) for key in picked)

    add("terminal", [key for key, row in info.items() if row["terminal"]],
        terminal_count, "terminal")
    add("recovery", [key for key, row in info.items() if row["recovery"]],
        recovery_count, "recovery")

    long_candidates = sorted(
        (key for key in info if key not in used),
        key=lambda key: (-info[key]["think_est_tokens"],
                         stable_rank(key, f"{seed}:long")))
    if len(long_candidates) < long_count:
        raise ValueError("not enough unique long-think calibration candidates")
    long_picked = long_candidates[:long_count]
    used.update(long_picked)
    selected.extend((key, "long_think") for key in long_picked)

    add("risky", [key for key, row in info.items() if row["risky"]],
        risky_count, "risky")
    add("random", list(info), random_count, "random")

    expected = (random_count + terminal_count + recovery_count
                + long_count + risky_count)
    if len(selected) != expected or len(used) != expected:
        raise AssertionError("calibration selection is not unique and complete")

    output = []
    for key, stratum in selected:
        source_row = index[key]
        meta = source_row.sample.get("meta") or {}
        output.append({
            **key.as_dict(),
            "n_steps": int(meta.get("n_steps") or 0),
            "stratum": stratum,
            **info[key],
        })
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True,
                        help="source build as NAME=DIR; repeat per build")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260831)
    args = parser.parse_args(argv)

    source_dirs = parse_named_paths(args.source, "--source")
    index, source_reports = load_source_rows(source_dirs)
    selected = select_calibration(index, seed=args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in selected:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    report = {
        "seed": args.seed,
        "source_rows": len(index),
        "selected_rows": len(selected),
        "strata": dict(sorted({
            name: sum(row["stratum"] == name for row in selected)
            for name in {row["stratum"] for row in selected}
        }.items())),
        "sources": source_reports,
    }
    report_path = args.out.with_suffix(args.out.suffix + ".report.json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False)
                           + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
