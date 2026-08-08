"""specs.jsonl -> OSWorld task JSON, with two host-side controls.

    python -m ostg.emit out/specs.jsonl --build out/build --out out/tasks --batch v1

For each spec:

    <build>/<slug>/seed/     setup_py output, laid out exactly like /home/user;
                             this is what gets uploaded
    <build>/<slug>/solved/   seed + solve_py; the witness state

then probe_py is run against both trees on the host, with TG_ROOT pointed at each:

    negative control  probe(seed)   must print FAIL   -- catches a probe that
                                                        passes an idle agent
    positive control  probe(solved) must print PASS   -- catches a probe and a
                                                        solution that disagree

Neither control drops a spec. Both outcomes are recorded in the task JSON's
"taskgen" block so the filter can slice yield by control status and you can find
out empirically whether control-failing tasks are worth generating.

The emitted evaluator is the same shape official command-probe tasks use --
exact_match over vm_command_line stdout against a rule -- so OSWorld runs it
unmodified: no custom metric, no import shim, no gold file.
"""
import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from ostg import prompt as P

HERE = Path(__file__).resolve().parent
NS = uuid.UUID("2f8e41b6-7c05-5d93-9a12-6be0d47cf381")
GUEST_HOME = "/home/user"
HELPER_GUEST = "/tmp/tghelp.py"

SNAPSHOT = {k: v[0] for k, v in P.APPS.items()}
WINDOW = {k: v[1] for k, v in P.APPS.items() if v[1]}

# The two document apps' affordances, both measured over the 361 official tasks
# and both gated on the SAME set -- the three LibreOffice apps. chrome and vscode
# have window titles too, which is why this cannot just reuse WINDOW: official
# chrome (0/46) and vs_code (0/23) tasks never pre-open a document, and the ctrl+s
# postconfig is a LibreOffice ritual (94 of the 132 official ctrl+s blocks).
OFFICE = {"libreoffice_calc", "libreoffice_writer", "libreoffice_impress"}
OPEN_EXT = {"xlsx", "xls", "ods", "docx", "odt", "pptx", "odp", "txt", "csv", "pdf"}

LAUNCH = {
    "chrome": ["google-chrome", "--remote-debugging-port=1337"],
    "vscode": ["code"],
    "thunderbird": ["thunderbird"],
    "gimp": ["gimp"],
    "vlc": ["vlc"],
    "files": ["nautilus"],
    "terminal": ["gnome-terminal"],
}


def run(script, root, extra_env=None, timeout=60):
    """Run a generated program with TG_ROOT pointed at `root`. Returns (rc, out, err)."""
    env = dict(os.environ, TG_ROOT=str(root), TG_HELP=str(HERE))
    env.update(extra_env or {})
    try:
        p = subprocess.run([sys.executable, "-c", script], capture_output=True,
                           text=True, timeout=timeout, env=env)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -9, "", "timeout after %ds" % timeout


def _host_of(url):
    """Host part of a url, for the last-resort url pattern."""
    from urllib.parse import urlparse

    return (urlparse(str(url)).netloc or str(url)).strip()


# The four steps every official chrome task uses to hand the agent a live browser,
# verbatim from chrome/a728a36e and 45 others. socat is not decoration: it
# republishes the debugging port so the host-side getter can reach CDP, and
# get_active_url_from_accessTree needs it. Readiness is judged on the
# "DevTools listening on ws://" line in chrome's stderr, not on the process
# starting, so the launch order matters.
def chrome_steps(start_url):
    return [
        {"type": "launch",
         "parameters": {"command": ["google-chrome", "--remote-debugging-port=1337"]}},
        {"type": "launch",
         "parameters": {"command": ["socat", "tcp-listen:9222,fork", "tcp:localhost:1337"]}},
        {"type": "chrome_open_tabs", "parameters": {"urls_to_open": [start_url]}},
        {"type": "activate_window", "parameters": {"window_name": "Google Chrome"}},
    ]


def guest_path(rel):
    """Desktop/a.xlsx -> /home/user/Desktop/a.xlsx (idempotent if already absolute)."""
    r = str(rel).replace("\\", "/").strip()
    if r.startswith(GUEST_HOME):
        return r
    return GUEST_HOME + "/" + r.lstrip("/")


def build_one(spec, build_root):
    """setup -> solve -> two probe controls. Returns a report dict.

    seed/ and solved/ are both laid out exactly like /home/user, so probe_py's
    paths mean the same thing on the host and in the VM and nothing has to be
    remapped between the three programs.
    """
    slug = spec["slug"]
    kind = spec.get("gold_kind") or "file"
    root = build_root / slug
    seed, solved = root / "seed", root / "solved"
    for d in (seed, solved):
        if d.exists():
            shutil.rmtree(d)
    seed.mkdir(parents=True)

    rep = {"gold_kind": kind, "setup": "ok", "solve": "ok",
           "negative": "?", "positive": "?", "notes": []}

    rc, _, err = run(P.HOST_PREAMBLE + spec["setup_py"], seed)
    if rc != 0:
        rep["setup"] = "error"
        rep["notes"].append("setup_py: " + (err.strip().splitlines() or ["?"])[-1][:200])
        return rep, seed

    # Neither of the non-file kinds has a probe or a solution to run: OSWorld
    # grades them with its own machinery -- the agent's FAIL signal
    # (desktop_env.py:469) for infeasible, its url matcher for browser_state.
    # Running the two controls on them would be theatre, so they are recorded as
    # not applicable rather than given a verdict that means nothing.
    if kind in ("infeasible", "browser_state"):
        rep["solve"] = rep["negative"] = rep["positive"] = "n/a:" + kind
        return rep, seed

    shutil.copytree(seed, solved)
    rc, _, err = run(P.HOST_PREAMBLE + spec.get("solve_py", ""), solved)
    if rc != 0:
        rep["solve"] = "error"
        rep["notes"].append("solve_py: " + (err.strip().splitlines() or ["?"])[-1][:200])

    probe = P.build_probe(spec)
    for tag, root_dir, want in (("negative", seed, "FAIL"), ("positive", solved, "PASS")):
        rc, out, err = run(probe, root_dir)
        verdict = out.strip().splitlines()[-1].strip() if out.strip() else ""
        if rc != 0:
            rep[tag] = "error"
            rep["notes"].append("probe(%s): %s" % (tag, (err.strip().splitlines() or ["?"])[-1][:200]))
        elif verdict == want:
            rep[tag] = "ok"
        else:
            rep[tag] = "wrong:" + (verdict or "<no output>")

    return rep, seed


def config_steps(spec, seed_dir):
    """Upload every file setup_py produced, at the guest path its position implies."""
    files = []
    for src in sorted(seed_dir.rglob("*")):
        if src.is_file():
            rel = src.relative_to(seed_dir).as_posix()
            files.append({"local_path": str(src.resolve()), "path": guest_path(rel)})
    # tghelp only exists for probe_py to import. A kind that has no probe should
    # not be shipping a helper module into /tmp where the agent can read it, and
    # official infeasible tasks carry an empty config.
    if (spec.get("gold_kind") or "file") == "file":
        files.append({"local_path": str((HERE / "tghelp.py").resolve()),
                      "path": HELPER_GUEST})
    cfg = [{"type": "upload_file", "parameters": {"files": files}}] if files else []
    # Anything that has to be installed or started runs before the applications
    # do, in the exact form the 6 official apt tasks use: one shell string,
    # shell=true, sudo fed the password through {CLIENT_PASSWORD}, and NO `until`.
    #
    # `until` looks like the safe choice and is the opposite. _execute_setup
    # retries every 0.3s until the condition holds or nb_failings >= 5, and
    # nb_failings only counts HTTP failures (setup.py:509-517) -- a non-zero
    # return code is not one. So `until: {"returncode": 0}` on a command that
    # cannot succeed, e.g. an apt-get that forgot sudo, loops forever and setup
    # never returns. Without it a failed install is a silent no-op, which is the
    # trap official lives with; a silent no-op costs one task, a hang costs the run.
    for cmd in spec.get("setup_shell") or []:
        if not cmd:
            continue
        # A list is an older spec's argv form. shlex.join, not " ".join: the
        # naive join turns ["/bin/bash","-c","apt-get install -y jq"] into
        # `/bin/bash -c apt-get install -y jq`, where bash -c takes "apt-get"
        # as the whole program and the rest as positional args, so it runs
        # apt-get with no arguments and exits non-zero.
        cmd = cmd if isinstance(cmd, str) else shlex.join(cmd)
        cfg.append({"type": "execute",
                    "parameters": {"command": cmd, "shell": True}})
    if (spec.get("gold_kind") or "file") == "browser_state":
        # Chrome is started by chrome_steps, with the debugging port the getter
        # needs; the generic LAUNCH entry would start it without one.
        return cfg + chrome_steps(spec.get("start_url") or "https://www.google.com")
    for app in spec.get("apps", []):
        if app in LAUNCH:
            cfg.append({"type": "launch", "parameters": {"command": LAUNCH[app]}})
    # `open` is a LibreOffice affordance, not general boilerplate. Measured over
    # the 361 official tasks: calc 47/47, writer 23/23 and impress 45/47 pre-open
    # their document, while gimp 0/26, os 0/24, vs_code 0/23, chrome 0/46 and
    # thunderbird 0/15 never do -- they `launch` and leave opening to the agent.
    # Every extension ever passed to `open` is an office document, txt or pdf.
    # Emitting it for a .png (first run, add-watermark-to-photo) made the server's
    # open_file endpoint return 500 and aborted the episode during setup, so the
    # task produced no result.txt at all.
    if (spec.get("apps") or [""])[0] in OFFICE:
        for rel in spec.get("open_paths", []) or []:
            if Path(rel).suffix.lower().lstrip(".") in OPEN_EXT:
                cfg.append({"type": "open", "parameters": {"path": guest_path(rel)}})
    return cfg


def save_postconfig(spec):
    """Flush an in-place edit to disk before probing. 94 of the 132 official
    ctrl+s postconfigs use exactly this four-step shape."""
    target = spec.get("save_target")
    apps = spec.get("apps") or []
    primary = apps[0] if apps else ""
    if not target or primary not in OFFICE:
        return None
    title = WINDOW[primary]
    return [
        {"type": "activate_window",
         "parameters": {"window_name": "%s - %s" % (Path(guest_path(target)).name, title),
                        "strict": True}},
        {"type": "sleep", "parameters": {"seconds": 0.5}},
        {"type": "execute",
         "parameters": {"command": ["python", "-c",
                                    "import pyautogui; pyautogui.hotkey('ctrl', 's');"]}},
        {"type": "sleep", "parameters": {"seconds": 2}},
    ]


def emit_one(spec, batch, seed_dir, report):
    apps = spec.get("apps") or ["libreoffice_calc"]
    kind = spec.get("gold_kind") or "file"
    ev = {}

    if kind == "infeasible":
        # No getter, no probe, no postconfig. evaluate() checks this before it
        # touches result_getter (desktop_env.py:469) and scores 1.0 only if the
        # agent's own last action was FAIL. Officially 27 tasks are graded this
        # way, and every one of them is an evaluator with the single key "func".
        # `func` MUST stay a scalar -- as a list the comparison at :469 is against
        # a list and the branch silently never fires, so OSWorld tries to call the
        # zero-argument `infeasible()` and raises, which costs the task its
        # result.txt instead of scoring it 0.
        ev["func"] = "infeasible"
    elif kind == "browser_state":
        # Copied from the official chrome tasks that judge where the browser
        # ended up (a728a36e, 9f935cce, 36037439). is_expected_url_pattern_match
        # re.searches every regex in rules["expected"] against the url and needs
        # all of them to hit (chrome.py:93-100), so an empty list would pass
        # anything -- fall back to the start url's own host in that case rather
        # than emit a task an idle agent scores 1.0 on.
        pats = [p for p in (spec.get("url_patterns") or []) if str(p).strip()]
        if not pats:
            pats = [re.escape(_host_of(spec.get("start_url") or ""))] or ["^https?://"]
        ev["func"] = "is_expected_url_pattern_match"
        ev["result"] = {"type": "active_url_from_accessTree", "goto_prefix": "https://"}
        ev["expected"] = {"type": "rule", "rules": {"expected": pats}}
    else:
        post = save_postconfig(spec)
        if post:
            ev["postconfig"] = post
        ev["func"] = "exact_match"
        ev["result"] = {"type": "vm_command_line",
                        "command": ["python3", "-c", P.build_probe(spec)]}
        ev["expected"] = {"type": "rule", "rules": {"expected": "PASS\n"}}

    return {
        "id": str(uuid.uuid5(NS, "%s:%s" % (batch, spec["slug"]))),
        "snapshot": SNAPSHOT.get(apps[0], "os"),
        "instruction": spec["instruction"],
        "source": "generated: simple-taskgen/%s#%s" % (batch, spec["slug"]),
        "config": config_steps(spec, seed_dir),
        "trajectory": "",
        "related_apps": apps,
        "evaluator": ev,
        # Officially 44 of the 52 tasks that touch a real site carry this, because
        # the sites block datacentre ranges. It is inert unless the runner is
        # given --enable_proxy: DesktopEnv defaults enable_proxy=False and logs a
        # single line before carrying on without one (desktop_env.py:290-292), so
        # a live_web batch run without the flag degrades silently.
        "proxy": (spec.get("source") == "live_web"),
        # Inert in every code path, but emitted so the file is key-for-key
        # identical in shape to an official task.
        "fixed_ip": False,
        "possibility_of_env_change": "low",
        "taskgen": {
            "slug": spec["slug"],
            "batch": batch,
            "gold_kind": kind,
            "url_stability": spec.get("url_stability"),
            "artifact": spec.get("artifact"),
            "source": spec.get("source"),
            "apps": apps,
            "app_count": spec.get("app_count"),
            "drawn_from": spec.get("drawn_from"),
            "controls": report,
        },
    }


def domain_of(spec):
    apps = spec.get("apps") or []
    if len(apps) >= 2:
        return "multi_apps"
    return {"vscode": "vs_code", "files": "os", "terminal": "os"}.get(
        apps[0] if apps else "", apps[0] if apps else "multi_apps")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("specs", type=Path)
    ap.add_argument("--build", type=Path, default=Path("out/build"))
    ap.add_argument("--out", type=Path, default=Path("out/tasks"))
    ap.add_argument("--batch", default="v1")
    args = ap.parse_args()

    specs = [json.loads(x) for x in args.specs.read_text().splitlines() if x.strip()]
    build_root = args.build / args.batch
    build_root.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)

    manifest, rows, written = {}, [], 0
    for spec in specs:
        slug = spec.get("slug", "?")
        try:
            rep, seed_dir = build_one(spec, build_root)
        except Exception as e:
            print("  BUILD-FAIL %-34s %s: %s" % (slug, type(e).__name__, e))
            rows.append({"slug": slug, "setup": "exception", "solve": "-",
                         "negative": "-", "positive": "-", "notes": [str(e)[:200]]})
            continue
        if rep["setup"] != "ok":
            print("  setup-fail  %-34s %s" % (slug, rep["notes"][-1] if rep["notes"] else ""))
            rows.append(dict(rep, slug=slug))
            continue

        task = emit_one(spec, args.batch, seed_dir, rep)
        dom = domain_of(spec)
        d = args.out / "examples" / dom
        d.mkdir(parents=True, exist_ok=True)
        (d / (task["id"] + ".json")).write_text(
            json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest.setdefault(dom, []).append(task["id"])
        written += 1

        flag = "".join("." if rep[k] == "ok" else ("-" if str(rep[k]).startswith("n/a") else "X")
                       for k in ("negative", "positive"))
        print("  %s  %-34s %-14s %s" % (flag, slug, dom, "" if flag == ".." else rep["notes"][-1:] or ""))
        rows.append(dict(rep, slug=slug, id=task["id"], domain=dom))

    (args.out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.out / "controls.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # "not applicable" is not a failure. Counting it as one is the same mistake
    # as emitting a green tick that verified nothing, just pointing the other way:
    # browser_state and infeasible tasks are graded by OSWorld itself and have
    # nothing for these controls to check.
    def _bad(v):
        return v != "ok" and not str(v).startswith("n/a")

    tested = [r for r in rows if not str(r.get("positive", "")).startswith("n/a")]
    ok = sum(1 for r in tested if r.get("negative") == "ok" and r.get("positive") == "ok")
    neg = sum(1 for r in tested if _bad(r.get("negative")))
    pos = sum(1 for r in tested if _bad(r.get("positive")))
    na = len(rows) - len(tested)
    print("\n%d specs -> %d task json under %s" % (len(specs), written, args.out))
    print("controls: %d/%d clean of the %d testable   negative failed %d   positive failed %d"
          % (ok, len(tested), len(tested), neg, pos))
    if na:
        print("          %d not applicable (graded by OSWorld itself: %s)"
              % (na, ", ".join(sorted({str(r.get("gold_kind")) for r in rows
                                       if str(r.get("positive", "")).startswith("n/a")}))))
    print("(nothing was dropped for a failed control; see controls.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
