"""Coverage audit: does the grader check what the instruction promises?

    python -m ostg.taskgen.audit out/runs/<set>/specs.jsonl [...] --out audit.jsonl \
        [--model claude-opus-4-6] [--limit N]

One API call per spec. The auditor sees the instruction and the grader
(probe source / table rules / url patterns) and reports, both directions:
requirements the grader never verifies (a do-half agent could score 1.0)
and grader demands the instruction never made. It also flags assumptions
about live-web or external state (a URL assumed dead, a site assumed up) --
the class gold-injection structurally cannot catch, because the injected
gold shares the generator's world-model.

Report-only: nothing blocks on the verdicts. Use a DIFFERENT model from the
one that generated the set; a model re-reading its own work agrees with it.
"""
import argparse
import json
import sys
from pathlib import Path

from ostg.llm import call_and_extract, load_env

AUDIT_TOOL = {
    "name": "audit",
    "description": "Report the coverage verdict for one task.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["covered", "partial", "overreach"]},
            "missing": {"type": "array", "items": {"type": "string"},
                        "description": "instruction requirements the grader does not verify"},
            "grader_extra": {"type": "array", "items": {"type": "string"},
                             "description": "grader demands the instruction never made"},
            "world_assumptions": {"type": "array", "items": {"type": "string"},
                                  "description": "assumptions about live-web/external state "
                                                 "that may not hold in reality"},
            "note": {"type": "string"},
        },
        "required": ["verdict", "missing", "grader_extra", "world_assumptions"],
    },
}

SYSTEM = """You audit desktop-automation tasks. For the task below, list every
requirement its instruction makes that a grader could verify, then compare
with what the grader ACTUALLY verifies.

verdict: covered   = every user-visible requirement is verified
         partial   = the instruction demands things the grader ignores
         overreach = the grader demands things the instruction never asked

Also fill world_assumptions with any belief about external reality baked into
the grader or its constants -- a URL assumed to 404, a site assumed alive, a
page assumed to contain a string. Check each belief against what you know of
the real web; report the ones that are wrong or fragile. Be terse."""


def grader_text(spec):
    g = spec.get("grade", "probe")
    if g == "probe":
        return "probe (python, runs in the VM at grading time):\n" + (spec.get("probe") or "")
    if g == "table":
        return ("compare_table on %s with rules:\n%s"
                % (spec.get("table_target"), json.dumps(spec.get("table_rules"), indent=1)))
    return ("grader checks ONLY the active Chrome URL against these patterns "
            "(nothing else is graded):\n%s" % json.dumps(spec.get("url_patterns")))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("specs", nargs="+")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--env", default=".env")
    ap.add_argument("--max-tokens", type=int, default=2000)
    ap.add_argument("--stream", action="store_true")
    args = ap.parse_args(argv)
    load_env(args.env)
    import os
    cfg = {"model": args.model, "max_tokens": args.max_tokens,
           "base": os.environ.get("PPAPI_BASE_URL", "https://app-us.ppapi.ai").rstrip("/"),
           "key": os.environ.get("PPAPI_API_KEY", ""),
           "stream": args.stream}

    rows = [json.loads(l) for p in args.specs for l in open(p, encoding="utf-8") if l.strip()]
    if args.limit:
        rows = rows[:args.limit]
    counts = {"covered": 0, "partial": 0, "overreach": 0}
    flagged = []
    with args.out.open("w", encoding="utf-8") as fh:
        for i, s in enumerate(rows):
            user = ("instruction:\n%s\n\ngrade: %s\n\n%s"
                    % (s["instruction"], s.get("grade", "probe"), grader_text(s)))
            try:
                res, _, _ = call_and_extract(
                    [{"role": "user", "content": user}],
                    [{"type": "text", "text": SYSTEM}], cfg,
                    tool=AUDIT_TOOL, field=None)
            except RuntimeError as e:
                res = {"verdict": "error", "note": str(e)[:200],
                       "missing": [], "grader_extra": [], "world_assumptions": []}
            res["slug"] = s["slug"]
            res["grade"] = s.get("grade", "probe")
            fh.write(json.dumps(res, ensure_ascii=False) + "\n")
            fh.flush()
            counts[res["verdict"]] = counts.get(res["verdict"], 0) + 1
            if res["verdict"] != "covered" or res.get("world_assumptions"):
                flagged.append(res)
            print("%3d/%d %-44s %s%s" % (i + 1, len(rows), s["slug"], res["verdict"],
                                         " +world" if res.get("world_assumptions") else ""))
    print("\n== %s" % "  ".join("%s=%d" % kv for kv in sorted(counts.items())))
    for r in flagged:
        why = r.get("missing") or r.get("grader_extra") or r.get("world_assumptions")
        print("  %-10s %-44s %s" % (r["verdict"], r["slug"], str(why)[:90]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
