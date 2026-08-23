#!/usr/bin/env python3
"""panel_difficulty.py -- why does every student score lower on the held-out
half, and how much of it is the tasks rather than the model?

The seen/held gap is large for weak models (base 4B -17.8, champion -21.8) and
almost absent for the teacher (-1.8). An untrained base has seen neither half,
so selection cannot be the whole story: the halves must differ in composition
in a way that binds weak models and not strong ones.

This measures that. It builds per-task difficulty proxies that do NOT depend on
the model under test -- the teacher's step count and score, the domain, the
evaluator family, the instruction length -- reports how the two halves differ
on each, and then does the decisive step: STRATIFIED comparison. If an arm's
seen/held gap disappears once tasks are bucketed by teacher step count, the
gap was composition. If it survives, the halves differ in something this proxy
does not capture.

Usage (WSL):
  python3 panel_difficulty.py --arm nocap DIR_SEEN DIR_HELD [--arm base ...]
"""
import argparse, glob, json, os
from collections import defaultdict

E = "/mnt/d/research/OSWorld/evaluation_examples"
R = "/mnt/d/research/OSWorld/results_generated"


def load_run(pats):
    """task id -> (score, deduped step count, domain)"""
    out = {}
    for pat in pats:
        ds = sorted(glob.glob(pat))
        if not ds:
            continue
        for td in glob.glob(os.path.join(ds[-1], "*", "*")):
            rt = os.path.join(td, "result.txt")
            if not os.path.exists(rt):
                continue
            steps = set()
            tj = os.path.join(td, "traj.jsonl")
            if os.path.exists(tj):
                for line in open(tj, encoding="utf-8", errors="replace"):
                    if line.strip():
                        try:
                            steps.add(json.loads(line).get("step_num"))
                        except ValueError:
                            pass
            steps.discard(None)
            try:
                v = float(open(rt).read().split()[0])
            except Exception:
                continue
            out[os.path.basename(td)] = (v, len(steps),
                                         os.path.basename(os.path.dirname(td)))
    return out


def task_meta(tid, dom):
    p = os.path.join(E, "examples", dom, tid + ".json")
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}
    ev = d.get("evaluator") or {}
    f = ev.get("func")
    fs = f if isinstance(f, list) else [f]
    rules = (ev.get("options") or {}).get("rules")
    return {"func": ",".join(x for x in fs if isinstance(x, str)),
            "instr_len": len(d.get("instruction") or ""),
            "n_rules": len(rules) if isinstance(rules, list) else 1,
            "proxy": bool(d.get("proxy"))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", nargs="+", action="append", required=True,
                    metavar="LABEL DIR...")
    ap.add_argument("--teacher-seen", default=f"{R}/qwen38-27b-local/eval50-t38-2*")
    ap.add_argument("--teacher-held", default=f"{R}/qwen38-27b-local/eval50-t3850b-2*")
    a = ap.parse_args()

    seen = {t for ts in json.load(open(f"{E}/verified_eval50_nonproxy.json")).values() for t in ts}
    teach = load_run([a.teacher_seen, a.teacher_held])

    meta = {}
    for tid, (sc, st, dom) in teach.items():
        m = task_meta(tid, dom)
        m.update(teacher_score=sc, teacher_steps=st, domain=dom,
                 half="seen" if tid in seen else "held")
        meta[tid] = m

    print("=== 两半的成分对比(全部与被测模型无关)")
    for half in ("seen", "held"):
        g = [m for m in meta.values() if m["half"] == half]
        n = max(len(g), 1)
        tsteps = sorted(m["teacher_steps"] for m in g)
        print(f"  {half:5s} n={len(g)}"
              f" | 教师分 {100*sum(m['teacher_score'] for m in g)/n:5.2f}"
              f" | 教师步数 中位 {tsteps[len(tsteps)//2]:4.1f} 均值 {sum(tsteps)/n:5.1f}"
              f" | 指令长 {sum(m['instr_len'] for m in g)/n:5.0f}"
              f" | 规则数 {sum(m['n_rules'] for m in g)/n:4.1f}")
        dm = defaultdict(int)
        for m in g:
            dm[m["domain"]] += 1
        print("        域: " + " ".join(f"{k}{v}" for k, v in sorted(dm.items(), key=lambda x: -x[1])[:6]))
        fm = defaultdict(int)
        for m in g:
            fm["table" if "table" in m["func"] else
               "infeasible" if "infeasible" in m["func"] else
               "pptx/docx" if ("pptx" in m["func"] or "docx" in m["func"]) else "其他"] += 1
        print("        判分族: " + " ".join(f"{k}{v}" for k, v in sorted(fm.items(), key=lambda x: -x[1])))

    # stratify by teacher step terciles, computed over BOTH halves together
    st_all = sorted(m["teacher_steps"] for m in meta.values())
    q1, q2 = st_all[len(st_all)//3], st_all[2*len(st_all)//3]
    def tier(m):
        return "短" if m["teacher_steps"] <= q1 else ("中" if m["teacher_steps"] <= q2 else "长")
    print(f"\n=== 按教师步数分层(短<={q1} 中<={q2} 长>{q2}),看每层里两半各占多少")
    for t in ("短", "中", "长"):
        s = sum(1 for m in meta.values() if tier(m) == t and m["half"] == "seen")
        h = sum(1 for m in meta.values() if tier(m) == t and m["half"] == "held")
        print(f"  {t}档: 已见 {s:2d} | 留出 {h:2d}")

    for spec in a.arm:
        label, dirs = spec[0], spec[1:]
        run = load_run(dirs)
        common = [t for t in run if t in meta]
        print(f"\n=== {label}: 原始差 vs 分层后")
        for half in ("seen", "held"):
            g = [t for t in common if meta[t]["half"] == half]
            if g:
                print(f"  {half:5s} 总分 {100*sum(run[t][0] for t in g)/len(g):5.2f} (n={len(g)})")
        print("  按教师步数分层:")
        for t in ("短", "中", "长"):
            row = []
            for half in ("seen", "held"):
                g = [x for x in common if meta[x]["half"] == half and tier(meta[x]) == t]
                row.append(f"{half} {100*sum(run[x][0] for x in g)/len(g):5.1f}(n={len(g):2d})" if g else f"{half} --")
            gs = [x for x in common if meta[x]["half"] == "seen" and tier(meta[x]) == t]
            gh = [x for x in common if meta[x]["half"] == "held" and tier(meta[x]) == t]
            d = (100*sum(run[x][0] for x in gs)/len(gs) - 100*sum(run[x][0] for x in gh)/len(gh)) if gs and gh else None
            print(f"    {t}档: {row[0]} | {row[1]} | 层内差 {d:+.1f}pp" if d is not None else f"    {t}档: {row[0]} | {row[1]}")


if __name__ == "__main__":
    main()
