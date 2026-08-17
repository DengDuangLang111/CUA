"""Merge several run dirs into one rollout set.

    python -m ostg.taskgen.merge out/runs/a out/runs/b --out out/runs/all
        [--allow-slug-collision]

The runner takes ONE --test_config_base_dir and ONE manifest, and control's
--start/--limit sharding needs one ordered manifest -- but sharded generation
lands one dir per shard. This copies the examples/ trees together, rebuilds
the manifest, and refuses id AND slug collisions. Sources are untouched.

Why slugs matter here (2026-08-17 incident, `SFT_DATA.md`): ids are UUIDs and
never collide, but ostg slugs are derived from task content, so two shards can
independently mint the same slug. Each shard is internally unique; the
collision is BORN at merge. Downstream, `sft/build.py` used the slug as an
image directory name, so the second trajectory silently overwrote the first's
screenshots -- 29 samples of B/Bs trained on another task's pixels, invisible
to an existence-only check. build/verify/census now defend themselves, and
this gate stops it at the source: a merged pool with duplicate slugs does not
get created unless you explicitly opt in.
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
    ap.add_argument("--allow-slug-collision", action="store_true",
                    help="merge anyway, printing the duplicates (downstream "
                         "build disambiguates image dirs, but the pool is "
                         "then ambiguous for anything else slug-keyed)")
    a = ap.parse_args()
    shutil.rmtree(a.out, ignore_errors=True)
    os.makedirs(os.path.join(a.out, "examples"))
    manifest = collections.defaultdict(list)
    seen = {}
    slugs = collections.defaultdict(list)
    for src in a.sources:
        for f in glob.glob(os.path.join(src, "examples", "*", "*.json")):
            j = json.load(open(f, encoding="utf-8"))
            dom = os.path.basename(os.path.dirname(f))
            if j["id"] in seen:
                raise SystemExit("id collision: %s in %s and %s" % (j["id"], seen[j["id"]], src))
            seen[j["id"]] = src
            slug = (j.get("ostg") or {}).get("slug")
            if slug:
                slugs[slug].append("%s %s/%s" % (src, dom, j["id"]))
            d = os.path.join(a.out, "examples", dom)
            os.makedirs(d, exist_ok=True)
            shutil.copy(f, d)
            manifest[dom].append(j["id"])
    dup = {k: v for k, v in slugs.items() if len(v) > 1}
    if dup:
        for k, v in sorted(dup.items()):
            print("SLUG-COLLISION %s:" % k)
            for m in v:
                print("    %s" % m)
        if not a.allow_slug_collision:
            shutil.rmtree(a.out, ignore_errors=True)
            raise SystemExit(
                "%d slug collisions across shards -- cull one member of each "
                "pair (ostg.taskgen.cull) and re-merge, or pass "
                "--allow-slug-collision. Output NOT written." % len(dup))
        print("WARNING: merged with %d duplicate slugs (explicitly allowed)" % len(dup))
    json.dump(dict(sorted(manifest.items())),
              open(os.path.join(a.out, "manifest.json"), "w"), indent=1)
    print("%s: %d tasks, %d domains, %d unique slugs%s"
          % (a.out, len(seen), len(manifest), len(slugs),
             " (%d duplicated)" % len(dup) if dup else ""))


if __name__ == "__main__":
    main()
