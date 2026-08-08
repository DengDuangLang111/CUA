"""Measure how close generated instructions sit to the official suite, and to
each other.

    python -m ostg.contam out/runs/v2/specs.jsonl --osworld /path/to/OSWorld

361 official tasks are both the evaluation set and the reference library for what
a task looks like. gen borrows only axis COORDINATES from them and never their
content (see SAMPLING.md), but that is a discipline, not a guarantee -- nothing
checks it. This does.

Two numbers per generated instruction, because they fail differently:

  vs_official   the closest official instruction. High means the generated task
                is a paraphrase of something in the evaluation set, so training
                on it and then scoring on that set is measuring memorisation.
  vs_siblings   the closest OTHER generated instruction. High means the generator
                collapsed: the previous generation reached 0.987 here before
                anyone noticed (specs/vocab.py).

Both are reported with two metrics, because a paraphrase defeats one and not the
other:

  ratio    difflib.SequenceMatcher over characters -- catches near-verbatim text
  jaccard  overlap of content-word sets -- catches "same task, reworded"

Stdlib only, so this runs wherever the specs do.
"""
from __future__ import annotations

import argparse
import difflib
import glob
import json
import re
import sys
from pathlib import Path

# Words carrying no task identity. Kept deliberately short: the point is to stop
# "the", "file" and "please" from floating every pair upwards, not to build a
# stopword list that quietly deletes the signal.
STOP = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "at", "for", "with",
    "is", "are", "be", "it", "its", "this", "that", "there", "then", "so",
    "i", "me", "my", "you", "your", "we", "us", "our", "please", "help", "can",
    "could", "would", "should", "want", "need", "make", "do", "does", "did",
    "have", "has", "from", "by", "as", "into", "out", "up", "down", "all", "any",
    "each", "every", "file", "files", "open", "save", "using", "use", "new",
}

WORD = re.compile(r"[a-z0-9_]+")


def tokens(text):
    return {w for w in WORD.findall(str(text).lower()) if w not in STOP and len(w) > 2}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def ratio(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def closest(text, corpus, k=12):
    """(best_ratio, best_jaccard, best_label) against a corpus of (label, text).

    Jaccard over the whole corpus first, SequenceMatcher only over its top k.
    SequenceMatcher is quadratic in the string length and the corpus is 369 long;
    running it against everything makes a 1000-spec check take minutes for a
    number the prefilter already told us cannot be the maximum.
    """
    toks = tokens(text)
    scored = sorted(((jaccard(toks, t), lab, s) for lab, s, t in corpus), reverse=True)
    best = (0.0, 0.0, "-")
    for j, lab, other in scored[:k]:
        r = ratio(text, other)
        if max(r, j) > max(best[0], best[1]):
            best = (r, j, lab)
    return best


def load_official(root):
    out = []
    for f in sorted(glob.glob(str(Path(root) / "evaluation_examples/examples/*/*.json"))):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except ValueError:
            continue
        instr = d.get("instruction")
        if instr:
            lab = "%s/%s" % (Path(f).parent.name, d.get("id", "?")[:8])
            out.append((lab, instr, tokens(instr)))
    return out


def load_specs(paths):
    out = []
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            if d.get("instruction"):
                out.append((d.get("slug", "?"), d["instruction"], tokens(d["instruction"])))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("specs", nargs="+", help="one or more specs.jsonl")
    ap.add_argument("--osworld", default="/mnt/d/research/OSWorld-upstream",
                    help="an OSWorld checkout, for evaluation_examples/examples")
    ap.add_argument("--threshold", type=float, default=0.60,
                    help="flag a spec whose closest official match exceeds this on "
                         "either metric")
    args = ap.parse_args()

    specs = load_specs(args.specs)
    official = load_official(args.osworld)
    if not specs:
        print("no instructions in %s" % ", ".join(args.specs), file=sys.stderr)
        return 1
    if not official:
        print("no official tasks under %s" % args.osworld, file=sys.stderr)
        return 1
    print("%d generated instruction(s) vs %d official\n" % (len(specs), len(official)))

    flagged = []
    print("%-34s %-13s %-13s %s" % ("slug", "vs_official", "vs_siblings", "closest official"))
    print("-" * 96)
    for slug, text, _ in specs:
        siblings = [(s, t, tk) for s, t, tk in specs if s != slug]
        orat, ojac, olab = closest(text, official)
        srat, sjac, slab = closest(text, siblings) if siblings else (0.0, 0.0, "-")
        mark = " <<<" if max(orat, ojac) >= args.threshold else ""
        if mark:
            flagged.append((slug, orat, ojac, olab))
        print("%-34s r%.2f j%.2f   r%.2f j%.2f   %s%s"
              % (slug[:33], orat, ojac, srat, sjac, olab, mark))

    print()
    if flagged:
        print("%d spec(s) over the %.2f threshold against the evaluation set:"
              % (len(flagged), args.threshold))
        for slug, r, j, lab in flagged:
            print("  %-34s ratio %.2f jaccard %.2f  <- %s" % (slug, r, j, lab))
        print("A high score is not proof of copying -- two tasks can share a domain "
              "and a verb. Read the pair before dropping either.")
    else:
        print("nothing over the %.2f threshold against the evaluation set."
              % args.threshold)
    return 1 if flagged else 0


if __name__ == "__main__":
    raise SystemExit(main())
