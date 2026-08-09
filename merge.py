"""Merge several run dirs into one rollout set.

    python -m ostg.merge out/runs/a out/runs/b --out out/runs/all

The runner takes ONE --test_config_base_dir and ONE manifest, and control's
--start/--limit sharding needs one ordered manifest -- but sharded generation
lands one dir per shard. This copies the examples/ trees together, rebuilds
the manifest, and refuses id collisions. Sources are untouched.
"""
import argparse
import collections
import glob
import json
import os
import shutil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sources", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    shutil.rmtree(a.out, ignore_errors=True)
    os.makedirs(os.path.join(a.out, "examples"))
    manifest = collections.defaultdict(list)
    seen = {}
    for src in a.sources:
        for f in glob.glob(os.path.join(src, "examples", "*", "*.json")):
            j = json.load(open(f, encoding="utf-8"))
            dom = os.path.basename(os.path.dirname(f))
            if j["id"] in seen:
                raise SystemExit("id collision: %s in %s and %s" % (j["id"], seen[j["id"]], src))
            seen[j["id"]] = src
            d = os.path.join(a.out, "examples", dom)
            os.makedirs(d, exist_ok=True)
            shutil.copy(f, d)
            manifest[dom].append(j["id"])
    json.dump(dict(sorted(manifest.items())),
              open(os.path.join(a.out, "manifest.json"), "w"), indent=1)
    print("%s: %d tasks, %d domains" % (a.out, len(seen), len(manifest)))


if __name__ == "__main__":
    main()
