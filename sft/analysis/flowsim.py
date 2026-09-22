#!/usr/bin/env python3
"""flowsim.py -- flow-level (action-sequence) similarity between eval-50
trajectories and the r5 training corpus.

Question it answers (2026-08-19, user): are an arm's wins concentrated on
tasks whose ACTION FLOWS collide with training trajectories?  This is the
action-space twin of the text nearest-neighbour check in RESULTS 5.11.1
(max 0.22).  Pure file analysis: no GPU, no VM.

Canonical alphabet (both sides map into it):
  CLICK@gx,gy / RCLICK@ / DCLICK@ / MCLICK@ / DRAG@ / MOVE@   (8x4 grid)
  TYPE          (text content deliberately ignored)
  KEY:<sorted+combo>   SCROLL:<dir>   WAIT   END   FAIL   OTHER:<name>
Two alphabets are scored: FULL (with grid cells) and TYPE-ONLY (action
kinds only, coordinates stripped) -- TYPE-ONLY is the harsher collision
test, FULL the more literal one.

Metrics per eval task:
  * k-gram hit rate (k=3,4,5): fraction of the task's k-grams present in
    the union of all training k-grams.
  * nn_sim: max over training trajectories of Smith-Waterman local
    alignment score / min(len)  (1.0 = a full copy of the shorter side).
Discriminator: are the arm's UNIQUE wins over base (arm>0.5, base<=0.5)
sitting higher on nn_sim / hit rate than the rest?  Anchors: base arm
(never saw the corpus = generic-OS floor), teacher arm (wrote the corpus
= inheritance ceiling), and a sensitivity probe (2 training trajectories
replayed as pseudo-eval tasks; the pipeline must score them ~1.0 or it is
not detecting anything).

Usage (on WSL, where all data lives):
  python3 flowsim.py --corpus <train_swift.jsonl> [more...] \
    --arm NAME=/path/to/eval50-dir [more...] --base-arm NAME --code-hash H
"""
import argparse, glob, json, os, re, sys
from collections import defaultdict

GX, GY = 8, 4

# ---------- canonicalisation ----------

def grid(fx, fy):
    gx = min(GX - 1, max(0, int(fx * GX)))
    gy = min(GY - 1, max(0, int(fy * GY)))
    return f"{gx},{gy}"

CLICK_KIND = {"click": "CLICK", "leftClick": "CLICK", "rightClick": "RCLICK",
              "doubleClick": "DCLICK", "middleClick": "MCLICK",
              "moveTo": "MOVE", "dragTo": "DRAG"}

def canon_eval_row(action_str):
    """One traj.jsonl `action` string -> list of canonical tokens."""
    s = action_str.strip()
    u = s.upper()
    if u.startswith("DONE"):
        return [("END", "END")]
    if u.startswith("FAIL"):
        return [("FAIL", "FAIL")]
    if u.startswith("WAIT"):
        return [("WAIT", "WAIT")]
    toks = []
    for m in re.finditer(r"pyautogui\.(\w+)\(", s):
        fn = m.group(1)
        tail = s[m.end():m.end() + 160]
        if fn in CLICK_KIND:
            kind = CLICK_KIND[fn]
            mm = re.match(r"\s*(?:x\s*=\s*)?(-?\d+(?:\.\d+)?)\s*,\s*(?:y\s*=\s*)?(-?\d+(?:\.\d+)?)", tail)
            if mm:
                fx, fy = float(mm.group(1)) / 1920.0, float(mm.group(2)) / 1080.0
                toks.append((f"{kind}@{grid(fx, fy)}", kind))
            else:
                toks.append((kind, kind))
        elif fn in ("typewrite", "write"):
            toks.append(("TYPE", "TYPE"))
        elif fn == "press":
            keys = re.findall(r"['\"]([^'\"]+)['\"]", tail)
            toks.append((f"KEY:{'+'.join(sorted(k.lower() for k in keys[:1]))}" if keys else "KEY:?", "KEY"))
        elif fn == "hotkey":
            keys = re.findall(r"['\"]([^'\"]+)['\"]", tail)
            toks.append((f"KEY:{'+'.join(sorted(k.lower() for k in keys))}" if keys else "KEY:?", "KEY"))
        elif fn in ("scroll", "hscroll", "vscroll"):
            mm = re.match(r"\s*\(?\s*(-?\d+)", tail)
            d = "?"
            if mm:
                d = "up" if int(mm.group(1)) > 0 else "down"
            toks.append((f"SCROLL:{d}", "SCROLL"))
        elif fn == "sleep":
            toks.append(("WAIT", "WAIT"))
        else:
            toks.append((f"OTHER:{fn}", "OTHER"))
    return toks

CORPUS_KIND = {"left_click": "CLICK", "click": "CLICK", "right_click": "RCLICK",
               "double_click": "DCLICK", "middle_click": "MCLICK",
               "mouse_move": "MOVE", "hover": "MOVE",
               "left_click_drag": "DRAG", "drag": "DRAG"}

def canon_corpus_block(block, denom_x, denom_y):
    a = re.search(r"<parameter=action>\s*([a-zA-Z_]+)", block)
    if not a:
        return None
    name = a.group(1)
    co = re.search(r"<parameter=coordinate>\s*\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)", block)
    if name in CORPUS_KIND:
        kind = CORPUS_KIND[name]
        if co:
            fx = float(co.group(1)) / denom_x
            fy = float(co.group(2)) / denom_y
            return (f"{kind}@{grid(fx, fy)}", kind)
        return (kind, kind)
    if name == "type":
        return ("TYPE", "TYPE")
    if name in ("key", "hotkey", "press"):
        keys = re.findall(r"['\"]([a-zA-Z0-9_+]+)['\"]", block) or \
               re.findall(r"<parameter=keys>\s*([^\n<]+)", block)
        flat = []
        for k in keys:
            flat += re.split(r"[+,\s]+", k.strip("[] '\""))
        flat = [k.lower() for k in flat if k]
        return (f"KEY:{'+'.join(sorted(set(flat)))}" if flat else "KEY:?", "KEY")
    if name == "scroll":
        d = re.search(r"<parameter=direction>\s*([a-z]+)", block)
        if d:
            return (f"SCROLL:{d.group(1)}", "SCROLL")
        px = re.search(r"<parameter=pixels>\s*(-?\d+)", block)
        if px:
            return (f"SCROLL:{'up' if int(px.group(1)) > 0 else 'down'}", "SCROLL")
        return ("SCROLL:?", "SCROLL")
    if name == "wait":
        return ("WAIT", "WAIT")
    if name == "terminate":
        return ("END", "END")
    return (f"OTHER:{name}", "OTHER")

# ---------- loading ----------

def load_corpus(paths):
    """Returns {slug: [(full,kind),...]} from the DEEPEST row per slug."""
    best = {}
    all_coords = []
    raw_rows = {}
    for p in paths:
        for line in open(p, encoding="utf-8"):
            if not line.strip():
                continue
            row = json.loads(line)
            imgs = row.get("images") or []
            slug = None
            for ip in imgs:
                m = re.search(r"images/([^/]+)/obs_", ip)
                if m:
                    slug = m.group(1)
                    break
            if slug is None:
                continue
            a = [m2 for m2 in row["messages"] if m2["role"] == "assistant"]
            if slug not in raw_rows or len(a) > raw_rows[slug][0]:
                raw_rows[slug] = (len(a), a)
    for slug, (_, turns) in raw_rows.items():
        for t in turns:
            for co in re.finditer(r"<parameter=coordinate>\s*\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)", t["content"]):
                all_coords.append((float(co.group(1)), float(co.group(2))))
    mx = max((c[0] for c in all_coords), default=0)
    my = max((c[1] for c in all_coords), default=0)
    if mx > 1100:
        denom_x, denom_y, scale = 1920.0, 1080.0, "ABSOLUTE(1920x1080)"
    else:
        denom_x, denom_y, scale = 1000.0, 1000.0, "RELATIVE(0-1000)"
    print(f"[corpus] coordinate scale decided: {scale}  (max x={mx:.0f}, max y={my:.0f}, {len(all_coords)} coords)")
    seqs = {}
    for slug, (_, turns) in raw_rows.items():
        toks = []
        for t in turns:
            for b in re.findall(r"<tool_call>(.*?)</tool_call>", t["content"], re.S):
                tok = canon_corpus_block(b, denom_x, denom_y)
                if tok:
                    toks.append(tok)
        if toks:
            seqs[slug] = toks
    print(f"[corpus] {len(seqs)} training trajectories, "
          f"{sum(len(v) for v in seqs.values())} actions, "
          f"median len {sorted(len(v) for v in seqs.values())[len(seqs)//2]}")
    return seqs

def load_arm(arm_dir):
    """Returns {task_id: (tokens, score)}."""
    out = {}
    for td in sorted(glob.glob(os.path.join(arm_dir, "*", "*"))):
        if not os.path.isdir(td):
            continue
        tj = os.path.join(td, "traj.jsonl")
        rt = os.path.join(td, "result.txt")
        if not os.path.exists(tj):
            continue
        toks = []
        for line in open(tj, encoding="utf-8"):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            toks += canon_eval_row(str(row.get("action", "")))
        score = 0.0
        if os.path.exists(rt):
            try:
                score = float(open(rt).read().split()[0])
            except (ValueError, IndexError):
                score = 0.0
        out[os.path.basename(td)] = (toks, score)
    return out

# ---------- metrics ----------

def ngrams(seq, k):
    return set(tuple(seq[i:i + k]) for i in range(len(seq) - k + 1))

def sw_sim(a, b):
    """Smith-Waterman local alignment / min(len). match +1, mis/gap -1."""
    if not a or not b:
        return 0.0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            d = prev[j - 1] + (1 if ai == b[j - 1] else -1)
            v = max(0, d, prev[j] - 1, cur[j - 1] - 1)
            cur[j] = v
            if v > best:
                best = v
    # NOTE: python-level DP; fine at eval(<=~300) x train(<=~300) x 444
        prev = cur
    return best / min(len(a), len(b))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", nargs="+", required=True)
    ap.add_argument("--arm", nargs="+", required=True, help="NAME=/path/to/eval50 dir")
    ap.add_argument("--base-arm", default=None, help="NAME of the anchor arm for unique-win split")
    ap.add_argument("--code-hash", default="unknown")
    ap.add_argument("--probe", type=int, default=2, help="N training trajs replayed as sensitivity probes")
    args = ap.parse_args()

    print(f"[flowsim] code={args.code_hash}")
    train = load_corpus(args.corpus)
    train_items = sorted(train.items())
    tr_full = {k: [t[0] for t in v] for k, v in train_items}
    tr_kind = {k: [t[1] for t in v] for k, v in train_items}
    gram_full = {k: set() for k in (3, 4, 5)}
    gram_kind = {k: set() for k in (3, 4, 5)}
    for seq in tr_full.values():
        for k in (3, 4, 5):
            gram_full[k] |= ngrams(seq, k)
    for seq in tr_kind.values():
        for k in (3, 4, 5):
            gram_kind[k] |= ngrams(seq, k)
    # per-trajectory 3-gram index: a high nn_sim needs at least one shared
    # 3-gram, so skip hopeless opponents (pure-python SW over all 444 would
    # cost ~30-50 min; with the prefilter it is minutes). When nothing
    # shares a 3-gram, fall back to the 10 best unigram-bag overlaps so the
    # low end is still populated (approximate there, exact at the top).
    tr3 = {slug: ngrams(seq, 3) for slug, seq in tr_full.items()}
    def nn_over(full_seq):
        g3 = ngrams(full_seq, 3)
        cands = [slug for slug, g in tr3.items() if g & g3]
        if not cands:
            bag = set(full_seq)
            cands = sorted(tr_full, key=lambda sl: -len(bag & set(tr_full[sl])))[:10]
        return max((sw_sim(full_seq, tr_full[sl]) for sl in cands), default=0.0), len(cands)

    # sensitivity probes: training trajectories must score ~1.0
    print("\n=== sensitivity probes (expect nn_sim ~1.0, hits ~100%) ===")
    for slug, seq in list(tr_full.items())[:args.probe]:
        nn, _ = nn_over(seq)
        h4 = (len(ngrams(seq, 4) & gram_full[4]) / max(1, len(ngrams(seq, 4))))
        print(f"  probe {slug[:40]:42s} nn_sim={nn:.3f} 4gram_hit={h4:.2%}")

    arm_data = {}
    for spec in args.arm:
        name, path = spec.split("=", 1)
        arm_data[name] = load_arm(path)
        print(f"[arm {name}] {len(arm_data[name])} tasks loaded from {path}")

    base_scores = {}
    if args.base_arm and args.base_arm in arm_data:
        base_scores = {tid: sc for tid, (tk, sc) in arm_data[args.base_arm].items()}

    for name, tasks in arm_data.items():
        print(f"\n=== arm {name} ===")
        rows = []
        for tid, (toks, score) in sorted(tasks.items()):
            full = [t[0] for t in toks]
            kind = [t[1] for t in toks]
            if not full:
                continue
            nn, ncand = nn_over(full)
            h_full = {k: (len(ngrams(full, k) & gram_full[k]) / max(1, len(ngrams(full, k)))) for k in (3, 4, 5)}
            h_kind = {k: (len(ngrams(kind, k) & gram_kind[k]) / max(1, len(ngrams(kind, k)))) for k in (3, 4, 5)}
            rows.append((tid, score, len(full), nn, h_full, h_kind))
        if not rows:
            continue
        med = lambda xs: sorted(xs)[len(xs) // 2] if xs else 0.0
        avg = lambda xs: sum(xs) / len(xs) if xs else 0.0
        print(f"tasks={len(rows)}  nn_sim mean={avg([r[3] for r in rows]):.3f} median={med([r[3] for r in rows]):.3f}")
        for k in (3, 4, 5):
            print(f"  {k}-gram hit FULL mean={avg([r[4][k] for r in rows]):.2%}   TYPE-ONLY mean={avg([r[5][k] for r in rows]):.2%}")
        if base_scores and name != args.base_arm:
            uw = [r for r in rows if r[1] > 0.5 and base_scores.get(r[0], 1.0) <= 0.5]
            rest = [r for r in rows if r not in uw]
            if uw:
                print(f"  UNIQUE WINS vs {args.base_arm}: n={len(uw)}  "
                      f"nn_sim mean={avg([r[3] for r in uw]):.3f} (rest {avg([r[3] for r in rest]):.3f})  "
                      f"4gram FULL {avg([r[4][4] for r in uw]):.2%} (rest {avg([r[4][4] for r in rest]):.2%})")
                for r in sorted(uw, key=lambda x: -x[3]):
                    print(f"    win {r[0][:8]} steps={r[2]:3d} nn={r[3]:.3f} 4g={r[4][4]:.2%}")
        print("  per-task (tid score steps nn_sim 4gFULL 4gKIND):")
        for r in sorted(rows, key=lambda x: -x[3]):
            print(f"    {r[0][:8]} {r[1]:4.2f} {r[2]:3d} {r[3]:.3f} {r[4][4]:.2%} {r[5][4]:.2%}")

if __name__ == "__main__":
    main()
