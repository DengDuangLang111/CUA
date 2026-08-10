"""Office-file prebuild -- the fix for the soffice compositor poison.

A setup that runs `soffice --convert-to` inside the eval VM leaves GNOME's
compositor unable to PAINT the window later opened from that file: wmctrl and
xprop report the window focused and mapped, but the agent's screenshot shows a
bare desktop (proven 2026-08-10 by comparing wmctrl state to the screenshot
endpoint on the same env). The VM ships no python office libraries and no pip,
so the file cannot be built in-VM another way. Official OSWorld sidesteps this
by DOWNLOADING pre-made files.

This stage does the same, self-contained: it runs each soffice-carrying setup
once in a throwaway build container (real LibreOffice), snapshots the exact
file tree the setup produced under /home/user, and rewrites the setup to
MATERIALIZE that tree via base64 -- mkdir + `base64 -d`, no soffice, no logic.
The task's starting state is byte-identical; only the way it is reached
changes, from "convert at eval time" to "decode a prebuilt blob".

    python -m ostg.prebuild out/runs/set-s0/specs.jsonl [more...]

Idempotent: specs whose setup no longer mentions soffice are skipped.
"""
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BUILD_IMAGE = "ubuntu:22.04"
DOCKER_CFG = "/tmp/dockercfg"        # dodge the Docker Desktop credential helper
SNAP = "/home/user"


def _docker(args, **kw):
    env = {"DOCKER_CONFIG": DOCKER_CFG, "PATH": "/usr/bin:/bin:/usr/local/bin"}
    return subprocess.run(["docker", *args], env=env, capture_output=True,
                          text=True, **kw)


def _run_setup(setup):
    """Run a setup script inside the build container.

    The script arrives on STDIN rather than through a heredoc: setups are
    multi-kilobyte one-liners full of quotes and backslashes, and wrapping
    them in a heredoc inside `bash -c` mangled five of them (bash exited 2
    before the artifact was written, leaving the spec poisoned).
    """
    return _docker(["exec", "-i", "-u", "user", "-w", "/home/user",
                    "ostg-prebuild", "bash", "-s"], input=setup)


def wanted(path, setup):
    """Is this produced file part of the task's starting state?

    Running soffice leaves ~40 files of LibreOffice PROFILE behind
    (~/.config/libreoffice/...). Those are runtime state, not fixtures:
    embedding them bloats the task by 200 KB and ships the very profile whose
    creation poisons the compositor. Hidden paths therefore ride along only
    when the setup deliberately wrote into them -- which is how genuine
    dotfile fixtures (a .thunderbird profile, a .config preference store)
    stay intact.
    """
    if "/." not in path:
        return True
    for part in Path(path).parts:
        if part.startswith(".") and part in setup:
            return True
    return False


def _rewrite(files):
    """files: {abs_path: bytes} -> a shell setup that recreates them exactly."""
    dirs = sorted({str(Path(p).parent) for p in files})
    lines = ["mkdir -p %s" % " ".join("'%s'" % d for d in dirs)]
    for p, data in sorted(files.items()):
        b64 = base64.b64encode(data).decode()
        lines.append("printf %%s '%s' | base64 -d > '%s'" % (b64, p))
    return " && ".join(lines)


def main(paths):
    Path(DOCKER_CFG).mkdir(exist_ok=True)
    (Path(DOCKER_CFG) / "config.json").write_text("{}")
    # one persistent container for the whole batch
    _docker(["rm", "-f", "ostg-prebuild"], check=False)
    up = _docker(["run", "-d", "--name", "ostg-prebuild", BUILD_IMAGE,
                  "sleep", "infinity"])
    if up.returncode:
        print("cannot start build container:", up.stderr[:200], file=sys.stderr)
        return 1
    try:
        # The build container must be able to run ANY setup we might rewrite,
        # not just the soffice call: the same script often draws an image,
        # writes a workbook or cuts a clip. Missing a tool means the setup
        # fails here and the spec is left untouched (and stays poisoned), so
        # the toolbox mirrors what the eval VM offers.
        _docker(["exec", "ostg-prebuild", "bash", "-c",
                 "apt-get update -qq && DEBIAN_FRONTEND=noninteractive "
                 "apt-get install -y -qq --no-install-recommends "
                 "libreoffice python3 python3-pil python3-openpyxl "
                 "python3-lxml ffmpeg zip unzip poppler-utils "
                 ">/dev/null 2>&1; "
                 "useradd -m user 2>/dev/null; mkdir -p /home/user; "
                 "chown -R user /home/user"], check=False)
        total = 0
        for path in paths:
            path = Path(path)
            lines = [l for l in path.read_text(encoding="utf-8").splitlines()
                     if l.strip()]
            out = []
            changed = 0
            for line in lines:
                s = json.loads(line)
                setup = s.get("setup") or ""
                if "soffice" not in setup:
                    out.append(line)
                    continue
                # clean slate, run the real setup, capture the produced tree
                _docker(["exec", "ostg-prebuild", "bash", "-c",
                         "rm -rf /home/user/* /tmp/* 2>/dev/null; "
                         "mkdir -p /home/user; chown -R user /home/user"],
                        check=False)
                r = _run_setup(setup)
                listing = _docker(["exec", "ostg-prebuild", "bash", "-c",
                                   "find /home/user -type f 2>/dev/null"])
                found = [f for f in listing.stdout.splitlines() if f.strip()]
                if r.returncode != 0 or not found:
                    print("  !! %-34s setup rc=%s files=%d (left as-is): %s"
                          % (s.get("slug", "?"), r.returncode, len(found),
                             (r.stderr or "").strip().replace("\n", " ")[-160:]),
                          file=sys.stderr)
                    out.append(line)
                    continue
                keep = [f for f in found if wanted(f, setup)]
                if not keep:
                    print("  !! %-34s produced no fixture files (left as-is)"
                          % s.get("slug", "?"), file=sys.stderr)
                    out.append(line)
                    continue
                files = {}
                for f in keep:
                    b = _docker(["exec", "ostg-prebuild", "base64", "-w0", f])
                    files[f] = base64.b64decode(b.stdout)
                size = sum(len(v) for v in files.values())
                if size > 2_000_000:
                    print("  !! %-34s fixtures %.1f MB -- too big to embed, "
                          "left as-is" % (s.get("slug", "?"), size / 1e6),
                          file=sys.stderr)
                    out.append(line)
                    continue
                s["setup"] = _rewrite(files)
                s.setdefault("ostg", {})["prebuilt"] = True
                out.append(json.dumps(s, ensure_ascii=False))
                changed += 1
                print("  prebuilt %-34s %d file(s), %d bytes: %s"
                      % (s.get("slug", "?"), len(files), size,
                         ", ".join(Path(f).name for f in sorted(files))[:60]))
            if changed:
                path.write_text("\n".join(out) + "\n", encoding="utf-8")
            print("== %s: %d/%d specs prebuilt" % (path.parent.name, changed,
                                                    len(lines)))
            total += changed
        print("[prebuild] %d spec(s) rewritten to embedded blobs" % total)
        return 0
    finally:
        _docker(["rm", "-f", "ostg-prebuild"], check=False)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
