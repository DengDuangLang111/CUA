"""Focused smoke tests for the SWE-MeM experimental copy builder."""

import math
import json
import tempfile
from pathlib import Path

from .prepare_copy import prepare_rows, solve_weights, to_swift, write_split


class WordTokenizer:
    def encode(self, text, add_special_tokens=False):
        del add_special_tokens
        return text.split()


def sample(task_id, step, response):
    return {
        "messages": [{
            "role": "user",
            "content": [{"type": "text", "text": "task"}],
        }],
        "response": response,
        "meta": {
            "run": "test",
            "domain": "chrome",
            "task_id": task_id,
            "step": step,
            "n_steps": step,
        },
    }


def main():
    # Trajectory A: two body tokens over two rows, plus two unweighted suffixes.
    # Trajectory B: six body tokens in one row, plus one unweighted suffix.
    rows = [
        sample("a", 1, "one"),
        sample("a", 2, "two"),
        sample("b", 1, "one two three four five six"),
    ]
    groups, weights, audit, mean_total = prepare_rows(rows, WordTokenizer(), suffix_tokens=1)
    assert len(groups) == 2
    assert math.isclose(mean_total, 5.5)
    assert math.isclose(weights[("test", "chrome", "a")], 1.75)
    assert math.isclose(weights[("test", "chrome", "b")], 0.75)
    assert all(math.isclose(row["weighted_target_mass"], 5.5) for row in audit)

    swift_row = to_swift(rows[0], Path("/tmp/source"), 1.75)
    assert swift_row["messages"][-1]["role"] == "assistant"
    assert swift_row["messages"][-1]["loss_scale"] == 1.75
    assert swift_row["channel"] == "chrome"

    weights2, _, mean2 = solve_weights({"a": 2, "b": 6}, {"a": 2, "b": 1}, 1)
    assert math.isclose(mean2, 5.5)
    assert math.isclose(weights2["a"] * 2 + 2, 5.5)
    assert math.isclose(weights2["b"] * 6 + 1, 5.5)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_a, source_b, output = root / "a", root / "b", root / "out"
        source_a.mkdir()
        source_b.mkdir()
        output.mkdir()
        with (source_a / "samples.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows[:2]:
                handle.write(json.dumps(row) + "\n")
        with (source_b / "samples.jsonl").open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(rows[2]) + "\n")
        report = write_split(
            [source_a, source_b], output, WordTokenizer(), 1,
            "samples.jsonl", "train_swift_abs.jsonl")
        assert report["rows"] == 3
        assert report["trajectories"] == 2
        assert len(report["sources"]) == 2
        assert report["max_abs_equalization_error"] < 1e-12
        assert len((output / "a_train_swift_abs.jsonl").read_text().splitlines()) == 2
        assert len((output / "b_train_swift_abs.jsonl").read_text().splitlines()) == 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
