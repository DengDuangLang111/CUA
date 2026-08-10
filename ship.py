"""One command from finished specs to a shippable set. Orchestration only --
every check lives in the module that owns it.

    python -m ostg.ship out/runs/v8big-s0 out/runs/v8big-s1 \
        --ref cua-gym=/mnt/d/research/cua-gym/tasks.jsonl \
        --ref osworld=/mnt/d/research/OSWorld/evaluation_examples/examples \
        [--path_to_vm .../Ubuntu.qcow2]

    1 re-emit   examples/ + manifest.json rebuilt from specs.jsonl with the
                CURRENT emitter and gate, so emit fixes (flush postconfig) and
                gate tightenings (setup compile) reach sets generated earlier
    2 accept    the six gates (ostg.accept); any hard failure stops here
    3 control   only with --path_to_vm: the VM negative checks (ostg.control)
"""
import collections
import json
import shutil
import sys
from pathlib import Path

from ostg import accept, control, scan
from ostg.gen import gate, task_json


def reemit(setdir):
    specs = [json.loads(l) for l in (setdir / "specs.jsonl").read_text(
        encoding="utf-8").splitlines() if l.strip()]
    ex = setdir / "examples"
    if ex.is_dir():
        shutil.rmtree(ex)
    manifest = collections.defaultdict(list)
    dropped = 0
    for s in specs:
        why = gate(s)
        if why:
            dropped += 1
            print("  drop %-38s %s" % (s.get("slug", "?"), why[:60]))
            continue
        domain, tj = task_json(s, setdir.name)
        d = ex / domain
        d.mkdir(parents=True, exist_ok=True)
        (d / ("%s.json" % tj["id"])).write_text(
            json.dumps(tj, ensure_ascii=False, indent=1), encoding="utf-8")
        manifest[domain].append(tj["id"])
    (setdir / "manifest.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    kept = sum(len(v) for v in manifest.values())
    print("== %s: %d specs -> %d task json, %d dropped" % (setdir, len(specs), kept, dropped))


def main():
    argv = sys.argv[1:]
    vm = None
    if "--path_to_vm" in argv:
        i = argv.index("--path_to_vm")
        vm = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    refs = []
    while "--ref" in argv:
        i = argv.index("--ref")
        refs += argv[i:i + 2]
        argv = argv[:i] + argv[i + 2:]
    dirs = [Path(a) for a in argv]

    print("#### 1 re-emit")
    for d in dirs:
        reemit(d)

    print("\n#### 2 accept")
    fails = accept.main([str(d / "specs.jsonl") for d in dirs] + refs)
    if fails:
        print("\nSHIP BLOCKED: %d hard gate failure(s)" % fails)
        return 1

    print("\n#### 2.5 grader-defect scan (review, non-blocking)")
    scan.main([str(d / "specs.jsonl") for d in dirs])

    if vm:
        print("\n#### 3 control")
        for d in dirs:
            rc = control.main(["--tasks", str(d), "--path_to_vm", vm])
            if rc:
                print("SHIP BLOCKED: control found bad tasks in %s" % d)
                return 1
    else:
        print("\n(control skipped -- pass --path_to_vm to run it)")
    print("\nSHIP OK: %s" % ", ".join(map(str, dirs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
