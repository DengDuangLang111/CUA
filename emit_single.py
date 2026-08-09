"""specs.jsonl -> OSWorld task JSON, self-contained, no build step.

    python -m ostg.emit_single out/runs/v6/specs.jsonl --out out/v6_tasks

The difference from ostg.emit is where the starting files come from. emit builds
them on the HOST -- it runs setup_py with openpyxl and python-docx available,
writes a tree, and the task JSON uploads that tree into the VM. That is why it
needs a build directory, an upload_file config, and a --build flag whose absence
silently changes how tasks are graded.

Here the setup runs INSIDE the VM as an `execute` step, so the task JSON carries
everything it needs as text. Nothing is uploaded, nothing is cached, and the file
can be handed to anyone with an OSWorld checkout.

The cost is real and worth stating: the two build-time controls are gone. emit
runs the probe against the untouched setup (must FAIL) and against solve_py's
finished state (must PASS), and on a 185-spec run those caught 21 tasks whose
probe disagreed with their own solution. Without a host-side build there is no
solved state to check against, so a broken probe is found by a rollout instead --
15 to 25 minutes of VM time rather than a second of host time.

The negative control survives in a weaker form: `--check-negative` runs each
probe in a fresh VM right after setup and before any agent acts. It catches the
worse of the two failures, the task that scores 1.0 for doing nothing.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import uuid
from pathlib import Path

from ostg import prompt as P

# Same namespace as ostg.emit, so a slug keeps its id across both emitters and
# results from the two can be joined.
NS = uuid.UUID("2f8e41b6-7c05-5d93-9a12-6be0d47cf381")

# Probe bodies are written as a program, not a function body: there is no
# preamble to inject because there is no P() indirection and no tghelp to import.
# The wrapper exists for one reason -- an uncaught exception must reach stdout as
# FAIL. Without it a crashing probe prints nothing, get_vm_command_line hands the
# metric an empty string, and the task scores 0 for a reason indistinguishable
# from an idle agent.
PROBE_WRAPPER = """import sys, traceback
def _main():
%s

try:
    _main()
except Exception:
    traceback.print_exc(file=sys.stderr)
    print("FAIL")
"""


def wrap_probe(body):
    lines = (body or "").rstrip("\n").splitlines() or ["print('FAIL')"]
    return PROBE_WRAPPER % "\n".join(("    " + l) if l.strip() else l for l in lines)


def task_json(spec, batch):
    slug = spec["slug"]
    apps = spec.get("apps") or ["os"]
    return {
        "id": str(uuid.uuid5(NS, "%s/%s" % (batch, slug))),
        "snapshot": P.APPS.get(apps[0], (apps[0], None))[0],
        "instruction": spec["instruction"],
        "source": "generated: ostg/%s#%s" % (batch, slug),
        "config": [
            # shell=True because the setup is one command line with quoting in
            # it, which is how the model writes it and how a person would run it.
            # No `until` clause: _execute_setup retries a non-zero command every
            # 0.3s and counts only HTTP failures towards its retry cap, so a
            # permanently failing command would spin forever rather than fail.
            {"type": "execute",
             "parameters": {"command": spec["setup"], "shell": True}},
        ] + ([{"type": "open", "parameters": {"path": spec["open_path"]}}]
             if spec.get("open_path") else []),
        "related_apps": apps,
        "evaluator": {
            "func": "exact_match",
            "result": {"type": "vm_command_line",
                       "command": ["python3", "-c", wrap_probe(spec.get("probe"))]},
            "expected": {"type": "rule", "rule": {"expected": "PASS"}},
        },
        "ostg": {"slug": slug, "batch": batch,
                 "difficulty": spec.get("difficulty"),
                 "intent": spec.get("intent"), "domain": spec.get("domain"),
                 "app_count": spec.get("app_count")},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("specs", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--batch", default="v6")
    args = ap.parse_args()

    rows = [json.loads(l) for l in args.specs.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    (args.out / "examples").mkdir(parents=True, exist_ok=True)

    manifest = collections.defaultdict(list)
    written, skipped = 0, []
    for spec in rows:
        # A task with no probe cannot be graded, and a task with no setup starts
        # from whatever the last one left behind. Both are silent failures
        # downstream, so they stop here where the reason is visible.
        if not (spec.get("probe") or "").strip():
            skipped.append((spec.get("slug", "?"), "no probe"))
            continue
        if not (spec.get("setup") or "").strip():
            skipped.append((spec.get("slug", "?"), "no setup"))
            continue
        j = task_json(spec, args.batch)
        dom = j["snapshot"]
        d = args.out / "examples" / dom
        d.mkdir(parents=True, exist_ok=True)
        (d / ("%s.json" % j["id"])).write_text(
            json.dumps(j, ensure_ascii=False, indent=1), encoding="utf-8")
        manifest[dom].append(j["id"])
        written += 1

    (args.out / "manifest.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8")
    print("%d spec(s) -> %d task json under %s" % (len(rows), written, args.out))
    for slug, why in skipped:
        print("  skipped %-34s %s" % (slug, why))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
