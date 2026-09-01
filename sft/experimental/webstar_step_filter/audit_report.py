"""Before/after coverage report for WebSTAR-filtered source rows."""
from __future__ import annotations

from collections import defaultdict

from .common import action_signature, think_est_tokens
from .sample_calibration import classify_rows


def _bucket_length(n_steps):
    n = int(n_steps or 0)
    if n <= 10:
        return "01-10"
    if n <= 20:
        return "11-20"
    if n <= 30:
        return "21-30"
    if n <= 40:
        return "31-40"
    return "41-50+"


def build_retention_report(index, decisions):
    decision_map = decisions
    recovery_info = classify_rows(index)
    dimensions = {
        "source": defaultdict(lambda: defaultdict(float)),
        "domain": defaultdict(lambda: defaultdict(float)),
        "action": defaultdict(lambda: defaultdict(float)),
        "trajectory_length": defaultdict(lambda: defaultdict(float)),
        "terminal": defaultdict(lambda: defaultdict(float)),
        "recovery": defaultdict(lambda: defaultdict(float)),
    }

    for key, source_row in index.items():
        decision = decision_map[key]["decision"]
        sample = source_row.sample
        response = sample.get("response", "")
        meta = sample.get("meta") or {}
        labels = {
            "source": key.source_build,
            "domain": key.domain,
            "action": action_signature(response),
            "trajectory_length": _bucket_length(meta.get("n_steps")),
            "terminal": "terminal" if decision_map[key].get("terminal") else "nonterminal",
            "recovery": "recovery" if recovery_info[key]["recovery"] else "ordinary",
        }
        target_tokens = len(response) / 3.5
        think_tokens = think_est_tokens(response)
        for dimension, label in labels.items():
            cell = dimensions[dimension][label]
            cell["before_rows"] += 1
            cell[f"{decision}_rows"] += 1
            cell["before_target_tokens_est"] += target_tokens
            cell["before_think_tokens_est"] += think_tokens
            if decision == "keep":
                cell["kept_target_tokens_est"] += target_tokens
                cell["kept_think_tokens_est"] += think_tokens

    rendered = {}
    for dimension, cells in dimensions.items():
        rendered[dimension] = {}
        for label, cell in sorted(cells.items()):
            before = int(cell["before_rows"])
            rendered[dimension][label] = {
                "before_rows": before,
                "keep_rows": int(cell["keep_rows"]),
                "drop_rows": int(cell["drop_rows"]),
                "review_rows": int(cell["review_rows"]),
                "retention_ratio": round(cell["keep_rows"] / before, 6)
                if before else None,
                "before_target_tokens_est": round(
                    cell["before_target_tokens_est"], 1),
                "kept_target_tokens_est": round(
                    cell["kept_target_tokens_est"], 1),
                "before_think_tokens_est": round(
                    cell["before_think_tokens_est"], 1),
                "kept_think_tokens_est": round(
                    cell["kept_think_tokens_est"], 1),
            }
    return rendered
