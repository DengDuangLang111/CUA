#!/usr/bin/env python3
"""coverage_audit.py -- what does the generated corpus teach, and what does the
benchmark ask for that it never teaches?

Written 2026-08-20 after the champion scored 0/4 on held-out LibreOffice Writer
tasks that the 27B teacher solved 3/4. The cause was not luck and not a
stricter evaluator: the training corpus contains ZERO tasks whose evaluator is
compare_docx_files, and zero tasks that must be answered "infeasible". The
model had never been shown the shape of either. That class of gap is invisible
in loss curves, invisible in text-similarity contamination checks, and only
shows up as a domain collapsing on the eval -- so it belongs in the pipeline,
run at build time, not discovered a month later from trajectories.

What it reports
  1. evaluator-function mix of the corpus (what the data teaches)
  2. evaluator-function mix of each benchmark panel (what the eval asks)
  3. the GAP list: functions the benchmark uses that the corpus never contains,
     weighted by how many benchmark tasks depend on them
  4. application mix on both sides

Slug mapping: a training sample's image directory is "<ostg.slug>-<8 hex>", so
the trailing hash is stripped to recover the generated task's slug.

Usage (on WSL):
  python3 coverage_audit.py --train-instr /tmp/train_instr.json \
      [--taskgen-glob '/mnt/d/research/os-simple-taskgen-v8/out/runs/*/examples/*/*.json'] \
      [--panel NAME=/path/to/panel.json ...]
"""
import argparse, glob, json, os, re
from collections import Counter


def funcs(ev):
    """Every evaluator function name in a task definition, list-valued or not."""
    out = []
    if not isinstance(ev, dict):
        return out
    f = ev.get("func")
    if isinstance(f, str):
        out.append(f)
    elif isinstance(f, list):
        out += [x for x in f if isinstance(x, str)]
    return out


def load_corpus(train_instr, taskgen_glob):
    """Map every TRAINING KEY to its generated task definition.

    The key is "<ostg.slug>-<8 hex>" and the slug alone is NOT unique: two
    distinct tasks can share it (verified 2026-08-20 -- campaign-brief-broken-
    links and retainer-trust-balance-sheet each name two different tasks with
    different instructions). Keying by slug silently folded those pairs and
    undercounted the corpus by 2, which is harmless for a "3 evaluator
    families" headline and NOT harmless for quota arithmetic. So: group the
    candidate definitions by slug, then disambiguate on the instruction text.
    """
    tr = json.load(open(train_instr, encoding="utf-8"))
    by_slug = {}
    for k in tr:
        m = re.match(r"^(.*)-[0-9a-f]{8}$", k)
        by_slug.setdefault(m.group(1) if m else k, []).append(k)

    cands = {}
    files = glob.glob(taskgen_glob)
    for p in files:
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        sl = (d.get("ostg") or {}).get("slug")
        if sl in by_slug:
            cands.setdefault(sl, []).append(d)

    def norm(x):
        return re.sub(r"\s+", " ", (x or "").strip().lower())

    found = {}
    for sl, keys in by_slug.items():
        defs = cands.get(sl, [])
        if len(keys) == 1 and defs:
            found[keys[0]] = defs[0]
            continue
        for k in keys:                       # disambiguate by instruction
            want = norm(tr[k])
            hit = next((d for d in defs if norm(d.get("instruction")) == want), None)
            if hit is None:                  # fall back to prefix match
                hit = next((d for d in defs
                            if want[:60] and norm(d.get("instruction")).startswith(want[:60])), None)
            if hit is not None:
                found[k] = hit
    return tr, by_slug, found, len(files)


def mix(defs):
    c = Counter(f for d in defs for f in funcs(d.get("evaluator") or {}))
    apps = Counter(a for d in defs for a in (d.get("related_apps") or []))
    return c, apps


def load_panel(meta_path, examples_root):
    meta = json.load(open(meta_path, encoding="utf-8"))
    out = []
    for dom, ids in meta.items():
        for tid in ids:
            for cand in (os.path.join(examples_root, "examples", dom, tid + ".json"),
                         os.path.join(examples_root, dom, tid + ".json")):
                if os.path.exists(cand):
                    try:
                        out.append(json.load(open(cand, encoding="utf-8")))
                    except Exception:
                        pass
                    break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-instr", required=True)
    ap.add_argument("--taskgen-glob",
                    default="/mnt/d/research/os-simple-taskgen-v8/out/runs/*/examples/*/*.json")
    ap.add_argument("--examples-root", default="/mnt/d/research/OSWorld/evaluation_examples")
    ap.add_argument("--panel", action="append", default=[], help="NAME=/path/to/panel.json")
    a = ap.parse_args()

    tr, by_slug, found, nfiles = load_corpus(a.train_instr, a.taskgen_glob)
    print(f"训练任务 {len(tr)} 条({len(by_slug)} 个 slug,故有 {len(tr)-len(by_slug)} 组同名不同题);"
          f"扫描 {nfiles} 个定义,按任务粒度匹配 {len(found)}/{len(tr)}")
    if len(found) < len(tr):
        print(f"  !! {len(tr)-len(found)} 条任务找不到定义 —— 配额分母会偏,先查 --taskgen-glob")
    cmix, capps = mix(found.values())
    n = max(len(found), 1)
    print(f"\n=== 语料教了什么({len(found)} 个任务)")
    for k, v in cmix.most_common():
        print(f"   {k:38s} {v:4d}  {100*v/n:5.1f}%")
    print("   应用: " + ", ".join(f"{k}×{v}" for k, v in capps.most_common(10)))

    taught = set(cmix)
    for spec in a.panel:
        name, path = spec.split("=", 1)
        defs = load_panel(path, a.examples_root)
        pm, pa = mix(defs)
        m = max(len(defs), 1)
        print(f"\n=== 面板 {name}({len(defs)} 题)")
        for k, v in pm.most_common():
            flag = "" if k in taught else "   <-- 语料从未教过"
            print(f"   {k:38s} {v:4d}  {100*v/m:5.1f}%{flag}")
        gap_funcs = [(k, v) for k, v in pm.items() if k not in taught]
        gap_tasks = sum(1 for d in defs
                        if any(f not in taught for f in funcs(d.get("evaluator") or {})))
        print(f"   >>> 缺口:{len(gap_funcs)} 种 evaluator 从未出现在语料里,"
              f"波及 {gap_tasks}/{len(defs)} 题 = {100*gap_tasks/m:.1f}%")
        if gap_funcs:
            print("       " + ", ".join(f"{k}×{v}" for k, v in
                                        sorted(gap_funcs, key=lambda x: -x[1])))


if __name__ == "__main__":
    main()
