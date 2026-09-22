#!/usr/bin/env python3
"""taskfit.py -- does the generated training set sit closer to one half of the
frozen eval-100 than the other?

The hypothesis this tests (user, 2026-08-20): the champion's advantage shrank
on the held-out half (+10 tasks seen, +8 held-out) because the generated tasks
happen to resemble the seen half more. The split was stratified by domain with
a fixed seed and never looked at the training corpus, so any gap is chance --
but chance at n=50 is exactly what a winner's-curse story would look like, so
it is worth measuring rather than assuming.

Method: for every eval task, the maximum similarity to any TRAINING task
instruction, using (a) token Jaccard and (b) character 4-gram Dice, which
disagree in useful ways -- Jaccard rewards shared vocabulary, Dice rewards
shared phrasing. Reported per half and per domain, with the two halves'
distributions compared by a permutation test on the difference of means.

Instructions come from the corpus itself (first user turn) rather than from any
side file, so what is measured is what the model was actually trained on.
"""
import json, os, re, sys, glob, random

STOP = set("the a an of to in on for and or with from at by as is are be that this it "
           "then into your you please make sure using use set new".split())

def toks(s):
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 2}

def grams(s, n=4):
    s = re.sub(r"\s+", " ", s.lower())
    return {s[i:i+n] for i in range(max(0, len(s) - n + 1))}

def jaccard(a, b):
    return len(a & b) / len(a | b) if (a or b) else 0.0

def dice(a, b):
    return 2 * len(a & b) / (len(a) + len(b)) if (a or b) else 0.0

def train_instructions(paths):
    out = {}
    for p in paths:
        for line in open(p, encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            slug = None
            for ip in r.get("images") or []:
                m = re.search(r"images/([^/]+)/obs_", ip)
                if m:
                    slug = m.group(1); break
            if slug is None or slug in out:
                continue
            u = [m for m in r["messages"] if m["role"] == "user"]
            if not u:
                continue
            m = re.search(r"Instruction:\s*(.+?)\s*(?:Previous actions:|$)", u[0]["content"], re.S)
            if m:
                out[slug] = m.group(1).strip()
    return out

def eval_instructions(meta_path, examples_root):
    meta = json.load(open(meta_path, encoding="utf-8"))
    out = {}
    for dom, ids in meta.items():
        for tid in ids:
            for cand in (os.path.join(examples_root, "examples", dom, tid + ".json"),
                         os.path.join(examples_root, dom, tid + ".json")):
                if os.path.exists(cand):
                    try:
                        out[tid] = (dom, json.load(open(cand, encoding="utf-8")).get("instruction", ""))
                    except Exception:
                        pass
                    break
    return out

def main():
    root = "/mnt/d/research/OSWorld/evaluation_examples"
    corpus = sys.argv[1:] or glob.glob(
        "/gpfs/scrubbed/jy050706/sft/data/q38-Bhqs2t-r5nocap-v11*/train_swift.jsonl")
    tr = train_instructions(corpus)
    print(f"训练任务 {len(tr)} 条")
    trt = [toks(v) for v in tr.values()]
    trg = [grams(v) for v in tr.values()]

    halves = {}
    for name, meta in (("已见50", "verified_eval50_nonproxy.json"),
                       ("未见50", "verified_eval50b_nonproxy.json")):
        ev = eval_instructions(os.path.join(root, meta), root)
        rows = []
        for tid, (dom, instr) in ev.items():
            a, b = toks(instr), grams(instr)
            rows.append((dom, tid,
                         max((jaccard(a, t) for t in trt), default=0.0),
                         max((dice(b, g) for g in trg), default=0.0)))
        halves[name] = rows
        j = [r[2] for r in rows]; d = [r[3] for r in rows]
        print(f"\n{name}: {len(rows)} 题")
        print(f"  最近邻 Jaccard  均值 {sum(j)/len(j):.4f}  中位 {sorted(j)[len(j)//2]:.4f}  最大 {max(j):.4f}")
        print(f"  最近邻 4gramDice 均值 {sum(d)/len(d):.4f}  中位 {sorted(d)[len(d)//2]:.4f}  最大 {max(d):.4f}")

    A, B = halves["已见50"], halves["未见50"]
    for idx, nm in ((2, "Jaccard"), (3, "Dice")):
        a = [r[idx] for r in A]; b = [r[idx] for r in B]
        obs = sum(a)/len(a) - sum(b)/len(b)
        pool = a + b
        rnd = random.Random(20260820)
        hits = 0
        for _ in range(20000):
            rnd.shuffle(pool)
            if abs(sum(pool[:len(a)])/len(a) - sum(pool[len(a):])/len(b)) >= abs(obs):
                hits += 1
        print(f"\n{nm}: 已见 − 未见 = {obs:+.4f}  置换检验 p = {hits/20000:.4f}")

if __name__ == "__main__":
    main()
