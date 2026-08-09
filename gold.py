"""Write a gold script per spec: shell that turns the post-setup VM into the
completed state, so control --gold can assert the grader awards 1.0.

    python -m ostg.gold out/runs/<set>/specs.jsonl [...] --out gold.jsonl

Blind spot, by construction: the script comes from the same model family that
wrote the task, so a gold whose world-beliefs are wrong (a URL assumed dead)
passes its own injection. audit.py covers that direction.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from ostg.gen import call_and_extract, load_env

GOLD_TOOL = {
    "name": "gold",
    "description": "Emit the gold script for one task.",
    "input_schema": {
        "type": "object",
        "properties": {
            "gold": {"type": "string",
                     "description": "non-interactive /bin/sh script producing the "
                                    "completed end state from the post-setup state"},
            "note": {"type": "string"},
        },
        "required": ["gold"],
    },
}

SYSTEM = """Write the GOLD script for the desktop task below: a non-interactive
/bin/sh script that, run on the VM right after the task's setup, produces the
end state a perfect agent would leave. It runs as user `user`, HOME=/home/user.

Rules:
- Direct state manipulation is fine (write files, sqlite3 into Chrome's Web
  Data, edit JSON prefs with python3) -- you are not the agent, you are the
  answer key.
- If the grader reads an app's on-disk state, the app must NOT be running
  when you write it (pkill first if the task config launched it).
- browser grade (graded on the active Chrome URL): end by launching
  google-chrome on a URL that matches the patterns, then `sleep 6`.
- The script must be idempotent and finish in under 60 seconds.
- Compute concrete values yourself (the same numbers the grader expects)."""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("specs", nargs="+")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--env", default=".env")
    ap.add_argument("--max-tokens", type=int, default=4000)
    ap.add_argument("--stream", action="store_true")
    args = ap.parse_args(argv)
    load_env(args.env)
    cfg = {"model": args.model or os.environ.get("PPAPI_MODEL", "claude-opus-4-6"),
           "max_tokens": args.max_tokens,
           "base": os.environ.get("PPAPI_BASE_URL", "https://app-us.ppapi.ai").rstrip("/"),
           "key": os.environ.get("PPAPI_API_KEY", ""),
           "stream": args.stream}

    rows = [json.loads(l) for p in args.specs for l in open(p, encoding="utf-8") if l.strip()]
    if args.limit:
        rows = rows[:args.limit]
    with args.out.open("w", encoding="utf-8") as fh:
        for i, s in enumerate(rows):
            user = json.dumps({k: s.get(k) for k in
                               ("slug", "instruction", "grade", "setup", "open_path",
                                "probe", "table_target", "table_rules",
                                "start_url", "url_patterns")},
                              ensure_ascii=False, indent=1)
            try:
                res, _, _ = call_and_extract(
                    [{"role": "user", "content": user}],
                    [{"type": "text", "text": SYSTEM}], cfg,
                    tool=GOLD_TOOL, field=None)
                row = {"slug": s["slug"], "gold": res.get("gold", ""),
                       "note": res.get("note", "")}
            except RuntimeError as e:
                row = {"slug": s["slug"], "gold": "", "note": "ERROR " + str(e)[:200]}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            print("%3d/%d %-44s %s" % (i + 1, len(rows), s["slug"],
                                       "ok" if row["gold"] else "EMPTY"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
