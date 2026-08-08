"""Duplication report for a finished run, against a baseline run.

    python -m ostg.report out/runs/v3s*/specs.jsonl --baseline out/runs/v2/specs.jsonl \
        --corpus osworld=/mnt/d/research/OSWorld-upstream \
        --corpus cuagym=/mnt/d/research/cua-gym/tasks.jsonl

ostg.contam answers "is this one spec close to something that exists". This
answers the question a whole run raises: did the countermeasures work, and where
is what remains.

Three sections, because the v2 post-mortem needed all three and doing them by
hand took longer than the generation:

  distribution  cosine against the reference corpora, as quantiles, next to the
                baseline's. A run is better if the whole curve moved down, not if
                its single worst case did -- one lucky maximum says nothing.
  by axis       the same, split by intent. v2's duplicates were not spread out:
                5 of 7 were single-property `configure`-shaped tasks, because the
                space of settings worth writing a task about is small. A run that
                halves the overall rate while leaving that cell untouched has not
                fixed the thing that was wrong.
  pairs         every spec at or above the flag, printed with the instruction it
                matched. Nothing below decides a duplicate: the only method that
                worked on v2 was reading the pair, and 3 of the 10 highest-scoring
                pairs there were unrelated tasks sharing rare words.

The flag defaults to 0.35 rather than contam's 0.60 because 0.60 caught none of
v2's seven confirmed duplicates. All seven scored cosine >= 0.35, and nothing
below 0.35 was a duplicate; the cost is two false positives in ten.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import statistics
import sys
from pathlib import Path

from ostg.contam import Ref, build_idf, closest, load_corpus, tokens


def load_specs(patterns):
    out = []
    for pat in patterns:
        for p in sorted(glob.glob(pat)) or [pat]:
            f = Path(p)
            if not f.is_file():
                continue
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    d = json.loads(line)
                    if d.get("instruction"):
                        out.append(d)
    return out


def score(specs, ref):
    """(spec, ratio, jaccard, cosine, label) for each spec, nearest reference."""
    return [(s,) + closest(s["instruction"], ref) for s in specs]


def quantiles(xs):
    if not xs:
        return "n/a"
    xs = sorted(xs)
    q = lambda p: xs[min(len(xs) - 1, int(p * len(xs)))]
    return ("median %.2f  p75 %.2f  p90 %.2f  max %.2f  mean %.2f"
            % (statistics.median(xs), q(.75), q(.90), xs[-1], statistics.mean(xs)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("specs", nargs="+")
    ap.add_argument("--baseline", action="append", default=[])
    ap.add_argument("--corpus", action="append", default=[], metavar="NAME=PATH")
    ap.add_argument("--flag", type=float, default=0.35)
    ap.add_argument("--pairs", type=int, default=40, help="max pairs to print")
    args = ap.parse_args()

    specs = load_specs(args.specs)
    base = load_specs(args.baseline) if args.baseline else []
    if not specs:
        print("no specs matched %s" % " ".join(args.specs), file=sys.stderr)
        return 1

    rows, text = [], {}
    for entry in args.corpus:
        name, _, path = entry.partition("=")
        loaded = load_corpus(path or name, name or "corpus")
        if not loaded:
            print("corpus %r resolved to nothing under %s" % (name, path), file=sys.stderr)
            return 1
        for lab, txt, _tk in loaded:
            text[lab] = txt
        rows += loaded
    if not rows:
        print("need at least one --corpus", file=sys.stderr)
        return 1

    allspecs = [(s.get("slug", "?"), s["instruction"], tokens(s["instruction"]))
                for s in specs + base]
    idf, dflt = build_idf(rows + allspecs)
    ref = Ref("all", rows, idf, dflt)

    scored = score(specs, ref)
    bscored = score(base, ref) if base else []

    print("=" * 96)
    print("run: %d spec(s)   baseline: %d   reference: %d task(s)"
          % (len(specs), len(base), len(rows)))
    print("=" * 96)

    print("\n[1] cosine against the reference corpora")
    print("  run       %s" % quantiles([c for _s, _r, _j, c, _l in scored]))
    if bscored:
        print("  baseline  %s" % quantiles([c for _s, _r, _j, c, _l in bscored]))
    over = [x for x in scored if x[3] >= args.flag]
    bover = [x for x in bscored if x[3] >= args.flag]
    print("  at or above %.2f: run %d/%d (%.0f%%)%s"
          % (args.flag, len(over), len(specs), 100.0 * len(over) / len(specs),
             ("   baseline %d/%d (%.0f%%)"
              % (len(bover), len(base), 100.0 * len(bover) / len(base))) if base else ""))

    print("\n[2] by intent  (v2's duplicates were 5/7 single-property configure)")
    by = collections.defaultdict(list)
    for s, _r, _j, c, _l in scored:
        by[s.get("intent") or "-"].append(c)
    for k in sorted(by, key=lambda k: -statistics.median(by[k])):
        v = by[k]
        n = sum(1 for x in v if x >= args.flag)
        print("  %-14s n=%-4d median %.2f  >=%.2f: %d (%.0f%%)"
              % (k, len(v), statistics.median(v), args.flag, n, 100.0 * n / len(v)))
    cby = collections.defaultdict(list)
    for s, _r, _j, c, _l in scored:
        cby[s.get("constraints") or "-"].append(c)
    print("  --")
    for k in sorted(cby, key=str):
        v = cby[k]
        n = sum(1 for x in v if x >= args.flag)
        print("  constraints=%-3s n=%-4d median %.2f  >=%.2f: %d (%.0f%%)"
              % (k, len(v), statistics.median(v), args.flag, n, 100.0 * n / len(v)))

    print("\n[3] pairs at or above %.2f -- READ THESE, the score does not decide"
          % args.flag)
    for s, r, j, c, lab in sorted(over, key=lambda x: -x[3])[:args.pairs]:
        print("-" * 96)
        print("  %s   c%.2f r%.2f j%.2f   intent=%s constraints=%s   <- %s"
              % (s.get("slug", "?"), c, r, j, s.get("intent"), s.get("constraints"), lab))
        print("    ostg : %s" % s["instruction"][:300])
        print("    已有 : %s" % text.get(lab, "?")[:300])
    if len(over) > args.pairs:
        print("\n  ... %d more over the flag, not printed (--pairs to raise)"
              % (len(over) - args.pairs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
