"""SFT admission review of PASSED trajectories. Observations, not a gate:
what earns top marks is deliberately undecided, so the judge reports flaws
and strengths and a provisional rating -- thresholds come later, from data.

    python -m ostg.sft.check RESULT_DIR --tasks out/runs/<set> --out sft_review.jsonl \
        [--reference OTHER_RESULT_DIR] [--model claude-opus-4-6] [--limit N]

Only score==1.0 trajectories are reviewed (the probe already owns correctness;
this pass judges the PROCESS). --reference points at another model's run of
the same tasks; when the same task passed there, its action digest is shown to
the judge as a comparison path. No step-count heuristics on purpose.
"""
import argparse
import base64
import glob
import json
import os
import sys
from pathlib import Path

from ostg.llm import call_and_extract, load_env

REVIEW_TOOL = {
    "name": "review",
    "description": "Report the process review for one passed trajectory.",
    "input_schema": {
        "type": "object",
        "properties": {
            "flaws": {"type": "array", "items": {"type": "string"},
                      "description": "detours, redundant or repeated actions, wrong turns "
                                     "later corrected, risky side effects, luck"},
            "strengths": {"type": "array", "items": {"type": "string"}},
            "process_rating": {"type": "integer", "minimum": 1, "maximum": 5,
                               "description": "provisional; no admission threshold is "
                                              "attached to this yet"},
            "reference_comparison": {"type": "string",
                                     "description": "how this path compares to the "
                                                    "reference path, if one was shown"},
            "note": {"type": "string"},
        },
        "required": ["flaws", "strengths", "process_rating"],
    },
}

SYSTEM = """You review the PROCESS of a desktop-automation trajectory that
already passed its correctness check. Judge only how it got there: detours,
repetition, wrong turns, risky side effects, luck. The final screenshot shows
the end state. Do not re-judge correctness. Be concrete and terse."""


def digest(td):
    lines = [json.loads(l) for l in open(os.path.join(td, "traj.jsonl"), encoding="utf-8")
             if l.strip()]
    calls, prev = [], None
    for l in lines:
        r = l.get("response") or ""
        if r != prev:
            after = r.split("</think>")[-1]
            act = after.split("Action:")[-1].split("<tool_call>")[0].strip()[:100]
            calls.append({"n": len(calls) + 1, "action": act, "exec": []})
        prev = r
        calls[-1]["exec"].append(str(l.get("action"))[:80])
    return calls


def last_png(td):
    pngs = sorted(glob.glob(os.path.join(td, "step_*.png")), key=os.path.getmtime)
    return pngs[-1] if pngs else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("result_dir")
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--reference", default=None)
    ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--env", default=".env")
    ap.add_argument("--max-tokens", type=int, default=2000)
    ap.add_argument("--stream", action="store_true")
    args = ap.parse_args(argv)
    load_env(args.env)
    cfg = {"model": args.model, "max_tokens": args.max_tokens,
           "base": os.environ.get("PPAPI_BASE_URL", "https://app-us.ppapi.ai").rstrip("/"),
           "key": os.environ.get("PPAPI_API_KEY", ""),
           "stream": args.stream}

    meta = {}
    for f in glob.glob(os.path.join(args.tasks, "examples", "*", "*.json")):
        j = json.load(open(f, encoding="utf-8"))
        meta[j["id"]] = {"slug": (j.get("ostg") or {}).get("slug", j["id"]),
                         "instruction": j.get("instruction", "")}

    passed = []
    for r in glob.glob(os.path.join(args.result_dir, "*", "*", "result.txt")):
        try:
            if float(open(r).read().strip()) == 1.0:
                passed.append(os.path.dirname(r))
        except ValueError:
            pass
    if args.limit:
        passed = passed[:args.limit]

    with args.out.open("w", encoding="utf-8") as fh:
        for i, td in enumerate(sorted(passed)):
            tid = os.path.basename(td)
            m = meta.get(tid, {"slug": tid, "instruction": ""})
            content = [{"type": "text", "text":
                        "instruction:\n%s\n\ntrajectory (per model call):\n%s"
                        % (m["instruction"], json.dumps(digest(td), ensure_ascii=False))}]
            if args.reference:
                ref = glob.glob(os.path.join(args.reference, "*", tid))
                if ref and os.path.isfile(os.path.join(ref[0], "result.txt")) \
                        and float(open(os.path.join(ref[0], "result.txt")).read().strip()) == 1.0:
                    content.append({"type": "text", "text":
                                    "reference path (another model, also passed):\n%s"
                                    % json.dumps(digest(ref[0]), ensure_ascii=False)})
            png = last_png(td)
            if png:
                content.append({"type": "image", "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": base64.b64encode(open(png, "rb").read()).decode()}})
            try:
                res, _, _ = call_and_extract(
                    [{"role": "user", "content": content}],
                    [{"type": "text", "text": SYSTEM}], cfg,
                    tool=REVIEW_TOOL, field=None)
            except RuntimeError as e:
                res = {"flaws": [], "strengths": [], "process_rating": 0,
                       "note": "ERROR " + str(e)[:200]}
            res["slug"] = m["slug"]
            fh.write(json.dumps(res, ensure_ascii=False) + "\n")
            fh.flush()
            print("%3d/%d %-44s rating=%s flaws=%d"
                  % (i + 1, len(passed), m["slug"], res.get("process_rating"),
                     len(res.get("flaws") or [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
