"""Acceptance gates for a generated task set. Three detectors, three blind spots:

    jaccard   surface vocabulary   -- catches same-words duplicates
    tf-idf    weighted vocabulary  -- catches shared-discriminative-words pairs
              (vs cua-gym: the pair jaccard scored 0.37 scores 0.52 here)
    signature what the PROBE reads -- catches re-dressed duplicates whose nouns
              all changed; grouping aid at its measured 0.30 knee, not a gate

    External corpora get the text detectors only: signatures were measured not
    to transfer across grader styles (sig.py's own verdict), and OSWorld's
    tasks have no probes to sign anyway.

    python -m ostg.accept <specs.jsonl> [...] --ref cua=<tasks.jsonl> --ref osworld=<examples dir>
"""
import collections
import glob
import itertools
import json
import math
import os
import re
import sys

STOP = set("the a an and or to of in on at for with is are be it its this that "
           "there then so i me my you your we us our please help can could would "
           "should want need make do does did have has from by as into out up "
           "down all any each every file files open save using use new".split())
WORD = re.compile(r"[a-z0-9_]+")
PYSTOP = set("def if else elif for while in not and or is none true false return "
             "print import from try except pass break continue with open os sys "
             "path isfile isdir exists join strip lower split append read write "
             "len str int float list dict set line lines row rows data text file "
             "get keys values items name main home user".split())


def tokens(t):
    return {w for w in WORD.findall(str(t).lower()) if w not in STOP and len(w) > 2}


def jac(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def build_idf(all_token_sets):
    n = len(all_token_sets) or 1
    df = collections.Counter()
    for tk in all_token_sets:
        df.update(tk)
    idf = {w: math.log((n + 1) / (d + 1)) + 1.0 for w, d in df.items()}
    return idf, math.log(n + 1) + 1.0


def vector(toks, idf, default):
    v = {w: idf.get(w, default) for w in toks}
    return v, math.sqrt(sum(x * x for x in v.values())) or 1.0


def cosine(qv, qn, dv, dn):
    small, large = (qv, dv) if len(qv) <= len(dv) else (dv, qv)
    return sum(w * large[t] for t, w in small.items() if t in large) / (qn * dn)


def signature(spec):
    """Word pieces of what the grader inspects, constants discarded."""
    grade = spec.get("grade", "probe")
    if grade == "probe":
        src = spec.get("probe") or spec.get("probe_py") or ""
    elif grade == "table":
        src = (spec.get("table_target") or "") + " " + " ".join(
            k for r in (spec.get("table_rules") or [])
            for k in (r.get("props") or {}))
    else:
        src = spec.get("start_url", "") + " " + " ".join(spec.get("url_patterns") or [])
    pieces = set()
    for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", src):
        for p in re.split(r"_+", w.lower()):
            if len(p) > 2 and p not in PYSTOP:
                pieces.add(p)
    return pieces


def load_ref(path):
    """Instructions from a jsonl, or from a directory of task JSONs (OSWorld
    examples layout)."""
    out = []
    if os.path.isdir(path):
        for f in glob.glob(os.path.join(path, "*", "*.json")):
            j = json.load(open(f, encoding="utf-8"))
            if j.get("instruction"):
                out.append(j["instruction"])
    else:
        for l in open(path, encoding="utf-8"):
            if l.strip():
                r = json.loads(l)
                if r.get("instruction"):
                    out.append(r["instruction"])
    return out


def main(argv=None):
    """Returns the number of hard-gate failures, so callers can stop a pipeline."""
    argv = list(sys.argv[1:] if argv is None else argv)
    hard_fails = 0
    refs = []
    while "--ref" in argv:
        i = argv.index("--ref")
        name, path = argv[i + 1].split("=", 1)
        refs.append((name, path))
        argv = argv[:i] + argv[i + 2:]
    if "--cua" in argv:  # old spelling
        i = argv.index("--cua")
        refs.append(("cua-gym", argv[i + 1]))
        argv = argv[:i] + argv[i + 2:]

    rows = []
    for path in argv:
        for l in open(path, encoding="utf-8"):
            if l.strip():
                r = json.loads(l)
                r["_src"] = path.rsplit("/", 2)[-2]
                rows.append(r)
    tks = [tokens(r["instruction"]) for r in rows]
    sigs = [signature(r) for r in rows]
    print("== %d specs from %d file(s)" % (len(rows), len(argv)))

    # One idf over everything -- references if given, else our own set -- so
    # internal and external cosines sit on the same scale.
    ref_tokens = {name: [tokens(t) for t in load_ref(path)] for name, path in refs}
    idf, dflt = build_idf([t for ts in ref_tokens.values() for t in ts] + tks)
    qvecs = [vector(t, idf, dflt) for t in tks]

    # 1. surface duplicates, whole set + cross-source
    pairs = sorted(((jac(tks[i], tks[j]), i, j)
                    for i, j in itertools.combinations(range(len(rows)), 2)),
                   reverse=True)
    hi = [p for p in pairs if p[0] >= 0.4]
    hard_fails += len(hi)
    print("\n[1] instruction jaccard: max=%.2f p90=%.2f pairs>=0.4: %d  %s"
          % (pairs[0][0], pairs[len(pairs) // 10][0], len(hi),
             "FAIL" if hi else "ok"))
    for s, i, j in pairs[:5]:
        tag = "CROSS" if rows[i]["_src"] != rows[j]["_src"] else "     "
        print("    %.2f %s %s ~ %s" % (s, tag, rows[i]["slug"], rows[j]["slug"]))

    # 1b. same pairs through the sharper lens: idf downweights boilerplate, so
    #     a pair sharing its DISCRIMINATIVE words scores where jaccard shrugs.
    cpairs = sorted(((cosine(*qvecs[i], *qvecs[j]), i, j)
                     for i, j in itertools.combinations(range(len(rows)), 2)),
                    reverse=True)
    chi = [p for p in cpairs if p[0] >= 0.5]
    hard_fails += len(chi)
    print("\n[1b] instruction tf-idf cosine: max=%.2f p90=%.2f pairs>=0.5: %d  %s"
          % (cpairs[0][0], cpairs[len(cpairs) // 10][0], len(chi),
             "FAIL" if chi else "ok"))
    for s, i, j in cpairs[:5]:
        print("    %.2f (j=%.2f)  %s ~ %s"
              % (s, jac(tks[i], tks[j]), rows[i]["slug"], rows[j]["slug"]))

    # 2. structural duplicates: grader signatures, 0.30 measured knee
    spairs = sorted(((jac(sigs[i], sigs[j]), i, j)
                     for i, j in itertools.combinations(range(len(rows)), 2)
                     if rows[i].get("grade", "probe") == rows[j].get("grade", "probe")),
                    reverse=True)
    flag = [p for p in spairs if p[0] >= 0.30]
    print("\n[2] grader-signature pairs >=0.30 (review, not a gate): %d" % len(flag))
    for s, i, j in flag[:8]:
        print("    %.2f  %s ~ %s" % (s, rows[i]["slug"], rows[j]["slug"]))

    # 3. contamination vs each reference corpus, on the same shared idf.
    if refs:
        for name, _ in refs:
            rvecs = [vector(t, idf, dflt) for t in ref_tokens[name]]
            worst = sorted(((max(cosine(qv, qn, dv, dn) for dv, dn in rvecs),
                             rows[i]["slug"]) for i, (qv, qn) in enumerate(qvecs)),
                           reverse=True)
            n5 = sum(1 for s, _ in worst if s >= 0.5)
            hard_fails += n5
            print("\n[3] vs %s (%d refs) tf-idf cosine: max=%.2f p90=%.2f #>=0.5: %d  %s"
                  % (name, len(rvecs), worst[0][0], worst[len(worst) // 10][0], n5,
                     "FAIL" if n5 else "ok"))
            for s, slug in worst[:5]:
                print("    %.2f  %s" % (s, slug))

    # 4. axis balance of the union
    for ax, target in (("intent", None), ("ambiguity", {1: .10, 2: .30, 3: .30, 4: .30}),
                   ("voice", None),
                   ("difficulty", {1: .15, 2: .25, 3: .25, 4: .20, 5: .15})):
        c = collections.Counter(r.get(ax) for r in rows)
        line = "  ".join("%s=%d" % kv for kv in sorted(c.items(), key=str))
        print("\n[4] %s: %s" % (ax, line))
        if target:
            drift = max(abs(c.get(k, 0) / len(rows) - v) for k, v in target.items())
            print("    max quota drift: %.0f%% %s" % (drift * 100, "ok" if drift < 0.10 else "CHECK"))

    # 5. corpus concentration -- pairwise checks cannot see a MONOCULTURE.
    #    SFT on a narrow corpus teaches the generator's habits, not the skill.
    COMMON = set("chrome desktop documents downloads pictures libreoffice calc "
                 "writer impress code thunderbird gimp vlc python csv pdf the".split())
    ents = collections.Counter()
    for r in rows:
        seen, instr = set(), r["instruction"]
        for m in re.finditer(r"\b[A-Z][a-z]{2,}(?: [A-Z][a-z]{2,})?\b", instr):
            head = instr[:m.start()].rstrip()
            # Sentence-initial capitals are grammar, not entities.
            if not head or head[-1] in ".!?:;\"'":
                continue
            if m.group().lower() not in COMMON:
                seen.add(m.group())
        ents.update(seen)
    reused = [(e, c) for e, c in ents.most_common() if c >= 3]
    print("\n[5] entity reuse across tasks (>=3): %d  %s"
          % (len(reused), "CHECK" if reused else "ok"))
    for e, c in reused[:6]:
        print("    %dx  %s" % (c, e))
    grams = [b for t in (r["instruction"].lower() for r in rows)
             for b in zip(t.split(), t.split()[1:])]
    print("    distinct-bigram ratio: %.2f (higher = more varied phrasing)"
          % (len(set(grams)) / max(len(grams), 1)))
    setups = sum(1 for r in rows if (r.get("setup") or "").lstrip().startswith("python3 -c"))
    print("    setup via python3 -c: %d/%d" % (setups, len(rows)))

    return hard_fails


if __name__ == "__main__":
    sys.exit(min(main(), 1))
