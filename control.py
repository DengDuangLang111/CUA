"""Pre-rollout controls, on the real evaluation path. Needs the OSWorld venv.

    python -m ostg.control --tasks out/runs/v8 --path_to_vm .../Ubuntu.qcow2

Per task: boot a fresh VM, run the setup by hand and check its exit code
(OSWorld never does), then env.evaluate() on the untouched desktop -- an idle
agent must score 0. Catches a broken setup, a probe that crashes, and a probe
that passes without work, each before any rollout minutes are spent.

With --gold gold.jsonl (from ostg.gold) the check inverts: after setup the
gold script runs and the grader must award 1.0 -- catching probes that can
never pass (stale-store reads, impossible constants). It cannot catch a gold
whose world-beliefs are wrong; audit.py owns that direction.
"""
import argparse
import json
from pathlib import Path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=Path, required=True,
                    help="directory holding examples/ and manifest.json")
    ap.add_argument("--path_to_vm", required=True)
    ap.add_argument("--provider_name", default="docker")
    ap.add_argument("--client_password", default="password")
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--start", type=int, default=0,
                    help="skip the first N manifest tasks, so two processes "
                         "can split one set")
    ap.add_argument("--gold", type=Path, default=None,
                    help="gold.jsonl: run each task's gold script after setup "
                         "and require score 1.0 instead of 0.0")
    args = ap.parse_args(argv)

    import requests
    from desktop_env.desktop_env import DesktopEnv

    manifest = json.loads((args.tasks / "manifest.json").read_text(encoding="utf-8"))
    files = [args.tasks / "examples" / d / ("%s.json" % i)
             for d, ids in sorted(manifest.items()) for i in ids]
    if args.start:
        files = files[args.start:]
    if args.limit:
        files = files[:args.limit]
    report = args.report or (args.tasks / ("gold_report.jsonl" if args.gold
                                           else "control_report.jsonl"))
    golds = {}
    if args.gold:
        for l in args.gold.read_text(encoding="utf-8").splitlines():
            if l.strip():
                g = json.loads(l)
                golds[g["slug"]] = g.get("gold") or ""

    env = DesktopEnv(provider_name=args.provider_name, path_to_vm=str(args.path_to_vm),
                     action_space="pyautogui", headless=True, require_a11y_tree=False,
                     os_type="Ubuntu", client_password=args.client_password)
    bad = 0
    with report.open("w", encoding="utf-8") as fh:
        for f in files:
            task = json.loads(f.read_text(encoding="utf-8"))
            cfg = task.get("config") or []
            execs = [c["parameters"] for c in cfg if c["type"] == "execute"]
            # Non-execute steps (chrome launch, open tabs) run through reset as
            # they would in a real rollout; execute steps run by hand so their
            # exit codes are observable. `open` is dropped: it needs the files
            # the execute steps have not created yet, and grading never reads it.
            rest = [c for c in cfg if c["type"] not in ("execute", "open")]
            env.reset(task_config=dict(task, config=rest))
            base = "http://%s:%s" % (env.vm_ip, env.server_port)
            rcs, err = [], ""
            for p in execs:
                r = requests.post(base + "/execute",
                                  json={"command": p["command"],
                                        "shell": p.get("shell", False)},
                                  timeout=180).json()
                rcs.append(r.get("returncode"))
                err = err or (r.get("error") or "").strip()[-200:]
            # `open` steps were skipped by reset (they need files the manual
            # executes just created); run them now so deictic tasks that start
            # from an opened document are actually exercised.
            open_rc = None
            for c in cfg:
                if c["type"] == "open":
                    orr = requests.post(base + "/setup/open_file",
                                        json={"path": c["parameters"]["path"]},
                                        timeout=180)
                    open_rc = orr.status_code
                    if orr.status_code != 200:
                        err = err or ("open %s -> HTTP %d"
                                      % (c["parameters"]["path"], orr.status_code))
            # Warm tasks promise a visible workspace, but no exit code says
            # whether a window actually mapped -- a lingering headless
            # process (the soffice collision) or a silently failed open
            # delivers a bare desktop that only screenshots betray. Count
            # mapped windows with whichever X tool the image carries;
            # windows == 0 on a warm task is BAD. None (no tool) skips.
            windows = None
            if any(c["type"] in ("open", "launch") for c in cfg):
                count_cmd = (
                    "sleep 6; export DISPLAY=:0; "
                    "if command -v wmctrl >/dev/null; then wmctrl -l | wc -l; "
                    "elif command -v xdotool >/dev/null; then "
                    "xdotool search --onlyvisible --name . 2>/dev/null | wc -l; "
                    "elif command -v xwininfo >/dev/null; then "
                    "xwininfo -root -children 2>/dev/null | grep -c child:; "
                    "else echo NA; fi")
                wr = requests.post(base + "/execute",
                                   json={"command": count_cmd, "shell": True},
                                   timeout=60).json()
                out = (wr.get("output") or "").strip()
                windows = int(out) if out.isdigit() else None
            env.is_environment_used = True  # manual POSTs bypass the flag
            slug = (task.get("ostg") or {}).get("slug") or task["id"]
            gold_rc = None
            if args.gold:
                g = golds.get(slug)
                if not g:
                    print("%-38s no gold script, skipped" % slug)
                    continue
                gr = requests.post(base + "/execute",
                                   json={"command": g, "shell": True},
                                   timeout=180).json()
                gold_rc = gr.get("returncode")
            probe_out = probe_err = ""
            res = task["evaluator"].get("result") or {}
            if res.get("type") == "vm_command_line":
                pr = requests.post(base + "/execute",
                                   json={"command": res["command"], "shell": False},
                                   timeout=180).json()
                probe_out = (pr.get("output") or "").strip()
                probe_err = (pr.get("error") or "").strip()[-200:]
            score = env.evaluate()
            want = 1.0 if args.gold else 0.0
            row = {"slug": slug,
                   "grade": (task.get("ostg") or {}).get("grade", "probe"),
                   "setup_rc": rcs, "setup_err": err, "gold_rc": gold_rc,
                   "open_rc": open_rc, "windows": windows,
                   "probe_out": probe_out, "probe_err": probe_err,
                   "score": score,
                   "ok": all(rc == 0 for rc in rcs) and score == want
                         and open_rc in (None, 200)
                         and windows != 0}
            bad += not row["ok"]
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            print("%-38s %-7s rc=%-6s probe=%-6s score=%s %s"
                  % (row["slug"], row["grade"], row["setup_rc"],
                     probe_out[:6], score, "ok" if row["ok"] else "BAD"))
    env.close()
    print("%d task(s), %d bad -> %s" % (len(files), bad, report))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
