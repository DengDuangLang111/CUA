"""
Task rows for task_check.py from CUA-Gym task ids (full ids or unique prefixes): extracts those tasks from the
CUA-Gym bundle into <out-dir>/tasks/ and writes <out-dir>/rows.jsonl, one row per task as training builds it
(build_task_parquet.cuagym_task). Python >= 3.14 (the bundle is .tar.zst).

    python3 make_rows.py --slime <slime-cua worktree> --out-dir <dir> [--bundle <cua_gym_tasks_v1.tar.zst>] <id>...
"""
import argparse
import importlib.util
import json
import os
import sys
import tarfile

p = argparse.ArgumentParser()
p.add_argument("--slime", required=True, help="slime-cua worktree (examples/cua_desktop/build_task_parquet.py)")
p.add_argument("--out-dir", required=True)
p.add_argument("--bundle", default=os.path.expanduser("~/uw/computeragent/cua-rl-local/datasets/cua_gym_tasks_v1.tar.zst"))
p.add_argument("ids", nargs="+")
a = p.parse_args()

spec = importlib.util.spec_from_file_location("btp", os.path.join(a.slime, "examples/cua_desktop/build_task_parquet.py"))
btp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(btp)

folder = os.path.join(a.out_dir, "tasks")
os.makedirs(folder, exist_ok=True)
found = set()
with tarfile.open(a.bundle, "r:zst") as bundle:
    for member in bundle:
        top = member.name.split("/")[0]
        if member.isfile() and not os.path.basename(member.name).startswith("._") and top.startswith(tuple(a.ids)):
            bundle.extract(member, folder, filter="data")
            found.add(top)
for prefix in a.ids:
    matches = [t for t in found if t.startswith(prefix)]
    if len(matches) != 1:
        sys.exit(f"{prefix}: {len(matches)} tasks in the bundle {matches[:3]}")
rows = [btp.cuagym_task(os.path.join(folder, t)) for t in sorted(found)]
with open(os.path.join(a.out_dir, "rows.jsonl"), "w") as handle:
    handle.writelines(json.dumps(row) + "\n" for row in rows)
print(f"{len(rows)} rows -> {os.path.join(a.out_dir, 'rows.jsonl')}")
