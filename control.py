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
            setup_cmd = task["config"][0]["parameters"]["command"]
            probe_cmd = task["evaluator"]["result"]["command"]
            # Empty config: reset boots the VM but leaves setup to us, so the
            # exit code is observable.
            env.reset(task_config=dict(task, config=[]))
            base = "http://%s:%s" % (env.vm_ip, env.server_port)
            r = requests.post(base + "/execute",
                              json={"command": setup_cmd, "shell": True},
                              timeout=180).json()
            env.is_environment_used = True  # manual POSTs bypass the flag
            pr = requests.post(base + "/execute",
                               json={"command": probe_cmd, "shell": False},
                               timeout=180).json()
            score = env.evaluate()
            row = {"slug": (task.get("ostg") or {}).get("slug") or task["id"],
                   "setup_rc": r.get("returncode"),
                   "setup_err": (r.get("error") or "").strip()[-200:],
                   "probe_out": (pr.get("output") or "").strip(),
                   "probe_err": (pr.get("error") or "").strip()[-200:],
                   "score": score,
                   "ok": r.get("returncode") == 0 and score == 0.0}
            bad += not row["ok"]
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            print("%-38s rc=%-3s probe=%-6s score=%s %s"
                  % (row["slug"], row["setup_rc"], row["probe_out"][:6],
                     score, "ok" if row["ok"] else "BAD"))
    env.close()
    print("%d task(s), %d bad -> %s" % (len(files), bad, report))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
