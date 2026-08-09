"""Pre-rollout controls, on the real evaluation path. Needs the OSWorld venv.

    python -m ostg.control --tasks out/runs/v8 --path_to_vm .../Ubuntu.qcow2

Per task: boot a fresh VM, run the setup by hand and check its exit code
(OSWorld never does), then env.evaluate() on the untouched desktop -- an idle
agent must score 0. Catches a broken setup, a probe that crashes, and a probe
that passes without work, each before any rollout minutes are spent.
"""
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=Path, required=True,
                    help="directory holding examples/ and manifest.json")
    ap.add_argument("--path_to_vm", required=True)
    ap.add_argument("--provider_name", default="docker")
    ap.add_argument("--client_password", default="password")
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    import requests
    from desktop_env.desktop_env import DesktopEnv

    manifest = json.loads((args.tasks / "manifest.json").read_text(encoding="utf-8"))
    files = [args.tasks / "examples" / d / ("%s.json" % i)
             for d, ids in sorted(manifest.items()) for i in ids]
    if args.limit:
        files = files[:args.limit]
    report = args.report or (args.tasks / "control_report.jsonl")

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
            env.is_environment_used = True  # manual POSTs bypass the flag
            probe_out = probe_err = ""
            res = task["evaluator"].get("result") or {}
            if res.get("type") == "vm_command_line":
                pr = requests.post(base + "/execute",
                                   json={"command": res["command"], "shell": False},
                                   timeout=180).json()
                probe_out = (pr.get("output") or "").strip()
                probe_err = (pr.get("error") or "").strip()[-200:]
            score = env.evaluate()
            row = {"slug": (task.get("ostg") or {}).get("slug") or task["id"],
                   "grade": (task.get("ostg") or {}).get("grade", "probe"),
                   "setup_rc": rcs, "setup_err": err,
                   "probe_out": probe_out, "probe_err": probe_err,
                   "score": score,
                   "ok": all(rc == 0 for rc in rcs) and score == 0.0}
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
