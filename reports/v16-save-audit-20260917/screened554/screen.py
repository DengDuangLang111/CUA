"""Offline review-queue screening; this does not certify saved artifacts."""
import collections
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RULES = {
    "disk_readback": r"\bcat\b|\bgrep\b|\bunzip\b|unzip\w*|read[- ]?back|read back|read from disk|read of the|read\(\)|re-?open(?:ed|ing)?|re-?load(?:ed|ing)?|print\(open",
    "file_presence": r"\bls\b|\bstat\b|terminal listing|file listing|file manager.{0,50}(?:shows|lists)|files app.{0,50}shows|\b\d[\d,]* bytes\b|\bmtime\b|icon.{0,30}appear",
    "ui_completion": r"image (?:saved|exported) to|\((?:overwritten|exported)\)|(?:asterisk|dirty.{0,15}(?:dot|indicator)|modified.{0,25}indicator|indicator.{0,20}(?:changed|changes|cleared|unmodified))|(?:no longer|without).{0,20}asterisk|no dirty|no unsaved.{0,10}(?:dot|indicator)",
}
# A conservative veto for an evidence *sentence*, not a failure judgment.
NEGATIVE = re.compile(
    r"\b(?:no (?:explicit |direct |post-save )?(?:verification|confirmation|file listing|on-disk)|"
    r"not (?:verified|confirmed|reopened|read)|without (?:verification|confirmation|checking|reopening)|"
    r"never (?:verified|confirmed|reopened)|cannot (?:verify|confirm)|unable to (?:verify|confirm))",
    re.I,
)
PATTERNS = {name: re.compile(pattern, re.I) for name, pattern in RULES.items()}
SOURCE_ONLY = re.compile(
    r"^(?:locate|find|read|inspect)\b|ask where to save|offer to save|"
    r"leave.{0,65}(?:on screen|user can read)", re.I)


def evidence_hits(row):
    hits = []
    for q in row["save_requirements"]:
        if SOURCE_ONLY.search(q.get("text", "")):
            continue
        if not q.get("evidence_steps") or not q.get("evidence_frames"):
            continue
        for sentence in re.split(r"[.;]\s+", q.get("note", "")):
            if NEGATIVE.search(sentence):
                continue
            for kind, pattern in PATTERNS.items():
                if pattern.search(sentence):
                    hits.append({"kind": kind, "requirement_id": q.get("id"),
                                 "requirement": q["text"], "note_excerpt": sentence,
                                 "judge_evidence": q.get("evidence"),
                                 "steps": q["evidence_steps"],
                                 "frames": q["evidence_frames"]})
    return hits


def main():
    audit = json.loads((ROOT / "audit.json").read_text())
    groups = collections.defaultdict(list)
    for source in audit["rows"]:
        row = dict(source)
        hits = evidence_hits(row)
        if row["bucket"] in {"missing_current_judgment", "latest_judge_not_admitted"}:
            tier = row["bucket"]
        elif row["step_restart"] or abs((row["judge_result_mtime"] or 0) - row["result_mtime"]) > 1:
            tier = "provenance_review"
        else:
            kinds = {h["kind"] for h in hits}
            tier = next((kind + "_candidate" for kind in RULES if kind in kinds),
                        "save_action_or_claim_only" if row["save_requirements"] or row["save_hotkeys"]
                        else "delivery_requirement_review")
        row["screen_tier"] = tier
        row["screen_evidence"] = hits
        row["independently_verified_all_deliverables"] = False
        groups[tier].append(row)
    for tier, rows in groups.items():
        (ROOT / (tier + ".jsonl")).write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    candidates = [row for tier in RULES for row in groups[tier + "_candidate"]]
    (ROOT / "save_evidence_candidates.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in candidates))
    summary = {
        "total": len(audit["rows"]), "counts": {k: len(v) for k, v in groups.items()},
        "candidate_count": len(candidates), "rules": RULES,
        "semantics": "Prioritizes existing judge notes, not new visual judgments. A hit supports at least one save-related requirement, not necessarily all deliverables. Do not use as certified training admission.",
        "by_domain": {tier: dict(collections.Counter(row["domain"] for row in rows))
                      for tier, rows in groups.items()},
    }
    assert sum(summary["counts"].values()) == summary["total"]
    assert len({(r["run"], r["domain"], r["task_id"]) for r in audit["rows"]}) == summary["total"]
    (ROOT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ["total", "counts", "candidate_count"]}, indent=2))


if __name__ == "__main__":
    main()
