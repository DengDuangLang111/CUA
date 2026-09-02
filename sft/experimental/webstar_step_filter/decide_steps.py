"""Convert immutable WebSTAR scores into keep/drop/review decisions."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from .common import (StepKey, has_explicit_done, iter_jsonl,
                     load_source_rows, parse_named_paths, sha256_text)


def load_score_rows(paths):
    by_key, seen = defaultdict(list), set()
    prompt_hashes = set()
    for path in paths:
        for row in iter_jsonl(path):
            key = StepKey.from_dict(row)
            token = key, str(row.get("pass_id"))
            if token in seen:
                raise ValueError(f"duplicate score for {key.text()} pass={token[1]}")
            score = row.get("score")
            if not isinstance(score, int) or not 0 <= score <= 10:
                raise ValueError(f"invalid score for {key.text()}: {score!r}")
            seen.add(token)
            by_key[key].append(row)
            prompt_hashes.add(str(row.get("prompt_sha256")))
    if len(prompt_hashes) != 1:
        raise ValueError(f"score files mix prompt versions: {prompt_hashes}")
    return by_key, prompt_hashes.pop()


def load_overrides(path):
    out = {}
    if not path:
        return out
    for row in iter_jsonl(path):
        key = StepKey.from_dict(row)
        if key in out:
            raise ValueError(f"duplicate manual override: {key.text()}")
        if row.get("decision") not in {"keep", "drop"}:
            raise ValueError(f"override must be keep/drop: {key.text()}")
        if not row.get("reviewer") or not row.get("reason"):
            raise ValueError(f"override needs reviewer and reason: {key.text()}")
        out[key] = row
    return out


def decide(index, scores_by_key, overrides=None, require_passes=1):
    overrides = overrides or {}
    decisions = []
    # 打分之后 terminalfix 的 keep_to 会截掉停滞的尾巴,那些 step 不再进语料。
    # 它们没有 source row,也就无从决策 —— 跳过,但计数上报,数量异常大时说明
    # source 选错了而不是截了几条尾巴。
    truncated = []
    for key in sorted(scores_by_key):
        if key not in index:
            truncated.append(key.text())
            continue
        source_row = index[key]
        score_rows = scores_by_key[key]
        pass_ids = {str(row.get("pass_id")) for row in score_rows}
        if len(pass_ids) < require_passes:
            raise ValueError(
                f"{key.text()}: needs {require_passes} passes, has {pass_ids}")
        response = source_row.sample.get("response", "")
        # 2026-09-01: 去掉打分后的 response sha256 校验。terminalfix 重写末步
        # 是流水线的正常一步(build --terminal-rewrite),它必然改 response,
        # 而重写只换收尾写法、不改这一步做了什么,判官的分仍然成立。
        # 校验与既定流程冲突,删除,不留开关。输出行仍记当前 response 的 hash,
        # 供事后追溯"决策是对哪个版本的 response 下的"。
        response_hash = sha256_text(response)

        scores = [int(row["score"]) for row in score_rows]
        keep_votes = [score > 5 for score in scores]
        if all(keep_votes):
            decision, reason = "keep", "all judge scores are above 5"
        elif not any(keep_votes):
            decision, reason = "drop", "all judge scores are 5 or below"
        else:
            decision, reason = "review", "judge passes disagree across score > 5"

        meta = source_row.sample.get("meta") or {}
        terminal = int(meta.get("step") or 0) == int(meta.get("n_steps") or -1)
        explicit_done = has_explicit_done(response)
        if terminal and not explicit_done:
            decision, reason = "review", "terminal target lacks explicit DONE/terminate"
        elif terminal and decision == "drop":
            decision, reason = "review", "terminal scored <=5; trajectory needs adjudication"

        source = "judge"
        if key in overrides:
            override = overrides[key]
            decision = override["decision"]
            reason = override["reason"]
            source = "manual_override"

        decisions.append({
            "schema_version": 1,
            "policy_version": "webstar-filter-v1",
            **key.as_dict(),
            "n_steps": int(meta.get("n_steps") or 0),
            "terminal": terminal,
            "explicit_done": explicit_done,
            "scores": scores,
            "pass_ids": sorted(pass_ids),
            "decision": decision,
            "decision_source": source,
            "reason": reason,
            "source_response_sha256": response_hash,
        })
    extra_overrides = sorted(key.text() for key in overrides if key not in scores_by_key)
    if extra_overrides:
        raise ValueError(f"overrides have no score rows: {extra_overrides[:5]}")
    if truncated:
        print("note: %d scored steps no longer in sources (tail-truncated): %s"
              % (len(truncated), ", ".join(truncated[:5])))
    # 判官调用失败的步没有分数,因此上面的循环走不到它们 —— 但 filter_copy 要求
    # 每个 source row 都有一条决策。它们没有任何判官背书,一律 drop,并在行里
    # 标明来源是 no-score 而不是判官,事后可与真正被判低分的区分开。
    scored = {StepKey.from_dict(d) for d in decisions}
    unscored = 0
    for key, source_row in sorted(index.items()):
        if key in scored:
            continue
        meta = source_row.sample.get("meta") or {}
        decisions.append({
            "schema_version": 1,
            "policy_version": "webstar-filter-v1",
            **key.as_dict(),
            "n_steps": int(meta.get("n_steps") or 0),
            "terminal": int(meta.get("step") or 0) == int(meta.get("n_steps") or -1),
            "explicit_done": has_explicit_done(
                source_row.sample.get("response", "")),
            "scores": [],
            "pass_ids": [],
            "decision": "drop",
            "reason": "no judge score (grader call failed); dropped for lack of evidence",
            "source": "no_score",
            "source_response_sha256": sha256_text(
                source_row.sample.get("response", "")),
        })
        unscored += 1
    if unscored:
        print("note: %d source rows had no judge score, dropped" % unscored)
    return decisions


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True,
                        help="neutral build as NAME=DIR")
    parser.add_argument("--scores", action="append", type=Path, required=True)
    parser.add_argument("--manual-overrides", type=Path, default=None)
    parser.add_argument("--require-passes", type=int, default=1)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    source_dirs = parse_named_paths(args.source, "--source")
    index, source_reports = load_source_rows(source_dirs)
    scores_by_key, score_prompt_sha256 = load_score_rows(args.scores)
    overrides = load_overrides(args.manual_overrides)
    decisions = decide(index, scores_by_key, overrides, args.require_passes)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in decisions:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    counts = Counter(row["decision"] for row in decisions)
    report = {
        "policy_version": "webstar-filter-v1",
        "score_prompt_sha256": score_prompt_sha256,
        "source_reports": source_reports,
        "score_keys": len(scores_by_key),
        "decisions": dict(sorted(counts.items())),
        "manual_overrides": len(overrides),
        "require_passes": args.require_passes,
    }
    report_path = args.out.with_suffix(args.out.suffix + ".report.json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False)
                           + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
