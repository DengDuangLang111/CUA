"""Validate emitted task JSON against the real OSWorld contract.

    python -m ostg.check out/tasks

Must run with OSWorld's own interpreter and from a checkout root, because it
imports desktop_env to resolve the metric, the getters and every setup type the
way the runner will. A name that does not resolve here becomes a task that
raises out of evaluate(), writes no result.txt, and disappears from the campaign
without an error (lib_run_single.py:65-68).
"""
import argparse
import glob
import json
import os
from pathlib import Path


def check_task(t, M, G, SetupController):
    ev = t.get("evaluator") or {}
    errs = []

    for key in ("id", "instruction", "evaluator", "config", "proxy"):
        if key not in t:
            errs.append("missing top-level key %r" % key)

    func = ev.get("func")
    if isinstance(func, list):
        errs.append("func is a list; conj=and averages the metrics "
                    "(desktop_env.py:509) so a partial score silently fails the filter")
    elif not func or not hasattr(M, func):
        errs.append("func %r does not resolve in desktop_env.evaluators.metrics" % func)

    for side in ("result", "expected"):
        cfg = ev.get(side)
        if not isinstance(cfg, dict):
            errs.append("%s is not a dict" % side)
            continue
        ty = cfg.get("type")
        if not ty or not hasattr(G, "get_" + ty):
            errs.append("getter get_%s does not resolve" % ty)

    if "options" in ev and func in ("exact_match", "check_include_exclude",
                                    "match_in_list", "is_in_list", "diff_text_file"):
        errs.append("%s takes no **options; passing one is a TypeError" % func)

    r, e = ev.get("result") or {}, ev.get("expected") or {}
    if r.get("dest") and r.get("dest") == e.get("dest"):
        errs.append("result.dest == expected.dest; both getters write the same cache "
                    "file and the metric compares a file with itself")

    for step in (t.get("config") or []) + (ev.get("postconfig") or []):
        ty = step.get("type")
        if not ty or not hasattr(SetupController, "_%s_setup" % ty):
            errs.append("setup type %r has no handler" % ty)

    up = [s for s in (t.get("config") or []) if s.get("type") == "upload_file"]
    for s in up:
        for f in s["parameters"]["files"]:
            if not f["local_path"].startswith("/"):
                errs.append("local_path not absolute: %s" % f["local_path"])
            elif not os.path.isfile(f["local_path"]):
                errs.append("local_path missing on disk: %s" % f["local_path"])
            elif os.path.isdir(f["local_path"]):
                errs.append("local_path is a directory; _upload_file_setup opens it "
                            "as a file and IsADirectoryError aborts the episode")
            if not f["path"].startswith("/"):
                errs.append("guest path not absolute: %s" % f["path"])

    cmd = (ev.get("result") or {}).get("command")
    if isinstance(cmd, list) and len(cmd) == 3 and cmd[1] == "-c":
        try:
            compile(cmd[2], "probe", "exec")
        except SyntaxError as ex:
            errs.append("probe does not compile: %s" % ex)

    # The metric, exercised on the exact strings this task emits. general.py:41
    # prints both arguments unconditionally, so keep its chatter off our report.
    if func == "exact_match" and isinstance(e.get("rules"), dict):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            good = M.exact_match("PASS\n", e["rules"])
            bad = M.exact_match("FAIL\n", e["rules"])
            nil = M.exact_match(None, e["rules"])
        if good != 1.0:
            errs.append("exact_match does not score PASS as 1.0")
        if bad != 0.0:
            errs.append("exact_match scores FAIL as non-zero")
        if nil != 0.0:
            errs.append("exact_match scores a None result as non-zero")

    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("taskroot", type=Path)
    args = ap.parse_args()

    import desktop_env.evaluators.getters as G
    import desktop_env.evaluators.metrics as M
    from desktop_env.controllers.setup import SetupController

    paths = sorted(glob.glob(str(args.taskroot / "examples" / "*" / "*.json")))
    print("checking %d task json against desktop_env" % len(paths))
    bad = 0
    for p in paths:
        t = json.load(open(p))
        slug = (t.get("taskgen") or {}).get("slug") or Path(p).stem
        errs = check_task(t, M, G, SetupController)
        print(("  OK    " if not errs else "  BAD   ") + slug)
        for e in errs:
            print("        " + e)
        bad += bool(errs)

    man = args.taskroot / "manifest.json"
    if man.is_file():
        ids = {i for v in json.loads(man.read_text()).values() for i in v}
        onfile = {Path(p).stem for p in paths}
        if ids != onfile:
            print("\nmanifest/disk mismatch: only in manifest %s | only on disk %s"
                  % (sorted(ids - onfile), sorted(onfile - ids)))

    print("\n%d/%d clean" % (len(paths) - bad, len(paths)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
