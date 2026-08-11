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
import io
import json
import time
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
    from PIL import Image
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
            # A `launch` that opens a file the setup creates must run AFTER the
            # setup, exactly as it does in a rollout (config is ordered). Left
            # in reset it fires against a file that does not exist yet and the
            # app comes up empty -- which the visibility check then reports as
            # a broken task. Browser-grade launches stay in reset: they are
            # chrome's debug harness, and chrome_open_tabs needs it running.
            browser = (task.get("ostg") or {}).get("grade") == "browser"
            deferred = ("execute", "open") if browser else ("execute", "open", "launch")
            rest = [c for c in cfg if c["type"] not in deferred]
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
                elif c["type"] == "launch" and "launch" in deferred:
                    p = c["parameters"]
                    lr = requests.post(base + "/setup/launch",
                                       json={"command": p.get("command"),
                                             "shell": p.get("shell", False)},
                                       timeout=180)
                    open_rc = lr.status_code
                    if lr.status_code != 200:
                        err = err or ("launch %s -> HTTP %d"
                                      % (p.get("command"), lr.status_code))
            # Warm tasks promise a visible workspace. Do NOT ask the window
            # manager whether a window exists: a setup that ran soffice
            # leaves the compositor unable to PAINT the window it later
            # opens, and wmctrl/xprop happily report it mapped and focused
            # while the agent's screen stays bare (measured 2026-08-10 --
            # this lane passed the whole calc domain that then scored 0/15).
            # Judge the only surface the agent has: its own screenshot.
            windows = None
            if any(c["type"] in ("open", "launch") for c in cfg):
                time.sleep(8)
                try:
                    shot = env.controller.get_screenshot()
                    im = Image.open(io.BytesIO(shot)).convert("RGB")
                    im = im.resize((160, 90))
                    px = list(im.getdata())
                    bare = sum(1 for r, g, b in px
                               if r > 60 and b > 60 and g < min(r, b) * 0.75)
                    # the stock wallpaper is the giveaway: a mapped, painted
                    # application covers most of it
                    windows = 0 if bare / len(px) > 0.55 else 1
                except Exception:
                    windows = None
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
