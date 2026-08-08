"""Measure how close generated instructions sit to existing benchmarks, and to
each other.

    python -m ostg.contam out/runs/v3/specs.jsonl \
        --corpus osworld=/path/to/OSWorld \
        --corpus cuagym=/path/to/CUAGym

An evaluation set is both the thing we score on and the reference library for
what a task looks like. gen borrows only axis COORDINATES from it and never its
content (see SAMPLING.md), but that is a discipline, not a guarantee -- nothing
checks it. This does.

ANY benchmark the generated tasks might later be scored against belongs in
--corpus, not just the one gen sampled coordinates from. Overlap with a suite
nobody sampled from is still contamination at evaluation time; the generator's
intent does not enter into it.

Two numbers per generated instruction, because they fail differently:

  vs_corpus     the closest instruction in ANY supplied corpus, labelled with
                which one. High means the generated task is a paraphrase of
                something in an evaluation set, so training on it and then
                scoring on that set is measuring memorisation.
  vs_siblings   the closest OTHER generated instruction. High means the generator
                collapsed: the previous generation reached 0.987 here before
                anyone noticed (specs/vocab.py).

Both are reported with three metrics, because a paraphrase defeats one and not
the others:

  ratio    difflib.SequenceMatcher over characters -- catches near-verbatim text
  jaccard  overlap of content-word sets -- catches "same task, reworded"
  cosine   TF-IDF over the same words -- catches "same task, reworded, and the
           words it shares are the rare ones". Jaccard cannot: it scores an
           overlap on `spacing` exactly like an overlap on `file`.

WHAT THIS DOES NOT CATCH
------------------------
Instruction text is the only signal here, and all three metrics are bag-of-words
or worse. Two tasks can be the same task with one constant changed -- 1.5 line
spacing versus 2.0 -- and score low on every metric below. Nothing here compares
setup, gold or evaluator, so a low score is evidence of non-copying, not proof of
a distinct task. `ostg.sig` is the structural check that does see those.

Stdlib only, so this runs wherever the specs do.
"""
from __future__ import annotations

import argparse
import collections
import difflib
import glob
import json
import math
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


def build_idf(rows):
    """Inverse document frequency over every reference instruction at once.

    Jaccard weights every surviving word equally, which is wrong for this corpus:
    `spreadsheet` appears in a large fraction of desktop tasks and `levenshtein`
    appears once, yet both move the score by the same amount. The measured effect
    was a pair scoring j0.37 -- under the flagging threshold -- whose shared words
    were all the discriminative ones (spacing, paragraphs, heading) and whose
    unshared words were all boilerplate (open, desktop, save, file).

    Built once over the union of all corpora so the numbers stay comparable
    between them; a per-corpus IDF would make 369 tasks and 10,910 tasks score on
    different scales.
    """
    n = len(rows) or 1
    df = collections.Counter()
    for _, _, tk in rows:
        df.update(tk)
    idf = {w: math.log((n + 1) / (d + 1)) + 1.0 for w, d in df.items()}
    # A word no reference task uses is maximally discriminative, so an unseen
    # term gets the weight of a term seen exactly zero times, not a weight of 0.
    return idf, math.log(n + 1) + 1.0


def vector(toks, idf, default):
    """Unit-normalised TF-IDF vector. TF is binary -- `tokens` returns a set, and
    in one-sentence instructions a repeated word carries no extra signal."""
    v = {w: idf.get(w, default) for w in toks}
    norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
    return v, norm


def cosine(qv, qn, dv, dn):
    small, large = (qv, dv) if len(qv) <= len(dv) else (dv, qv)
    dot = sum(w * large[t] for t, w in small.items() if t in large)
    return dot / (qn * dn)


class Ref:
    """A reference corpus with its TF-IDF vectors precomputed once."""

    def __init__(self, name, rows, idf, default):
        self.name = name
        self.rows = [(lab, txt, tk) + vector(tk, idf, default) for lab, txt, tk in rows]
        self.idf, self.default = idf, default

    def __len__(self):
        return len(self.rows)


def closest(text, ref, k=12):
    """(ratio, jaccard, cosine, label) for the nearest row in `ref`.

    Cheap metrics over the whole corpus, SequenceMatcher only over the top k by
    those. SequenceMatcher is quadratic in the string length and the corpus can be
    11k long; running it against everything turns a 30-spec check into minutes for
    a number the prefilter already ruled out. The prefilter ranks by
    max(jaccard, cosine) rather than jaccard alone, so a pair the weighting finds
    and the raw set overlap misses still reaches the expensive stage.
    """
    if isinstance(ref, list):  # bare rows, no weighting available
        ref = Ref("-", ref, {}, 1.0)
    toks = tokens(text)
    qv, qn = vector(toks, ref.idf, ref.default)
    scored = []
    for lab, other, tk, dv, dn in ref.rows:
        j = jaccard(toks, tk)
        c = cosine(qv, qn, dv, dn)
        scored.append((max(j, c), j, c, lab, other))
    scored.sort(key=lambda x: x[0], reverse=True)
    best = (0.0, 0.0, 0.0, "-")
    for _, j, c, lab, other in scored[:k]:
        r = ratio(text, other)
        if max(r, j, c) > max(best[0], best[1], best[2]):
            best = (r, j, c, lab)
    return best


def _records(path):
    """Every dict in a .json or .jsonl file, whatever it is wrapped in.

    Deliberately shape-agnostic. OSWorld stores one task per .json; other suites
    ship a list, a jsonl, or a dict of id -> task. Guessing wrong here means a
    corpus silently contributes zero instructions and the report says "clean"
    because it compared against nothing.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    if path.endswith(".jsonl"):
        for line in text.splitlines():
            line = line.strip()
            if line:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    yield d
        return
    try:
        d = json.loads(text)
    except ValueError:
        return
    if isinstance(d, dict):
        # A single task, or a container keyed by id. Both occur in the wild.
        if "instruction" in d:
            yield d
        else:
            for v in d.values():
                if isinstance(v, dict) and "instruction" in v:
                    yield v
                elif isinstance(v, list):
                    for x in v:
                        if isinstance(x, dict) and "instruction" in x:
                            yield x
    elif isinstance(d, list):
        for x in d:
            if isinstance(x, dict) and "instruction" in x:
                yield x


def load_corpus(root, name):
    """(label, instruction, tokens) for every task found anywhere under root.

    Recursive rather than pinned to evaluation_examples/examples/*/*.json, so a
    benchmark laid out differently still gets read. Instructions are deduplicated
    by exact text: OSWorld-V2 reissues 334 of OSWorld's 369 verbatim, and counting
    those twice would inflate nothing but the runtime.
    """
    out, seen = [], set()
    root = Path(root)
    if root.is_file():
        files = [str(root)]
    else:
        # An OSWorld-shaped checkout is scanned at its task directory, not at its
        # root: results/*/traj.jsonl carries an `instruction` field per rollout,
        # and sweeping those in would compare the specs against copies of the
        # very tasks we already have -- thousands of times over, slowly.
        scan = root / "evaluation_examples" / "examples"
        if not scan.is_dir():
            scan = root
        files = sorted(glob.glob(str(scan / "**/*.json"), recursive=True)
                       + glob.glob(str(scan / "**/*.jsonl"), recursive=True))
    for f in files:
        for d in _records(f):
            instr = d.get("instruction")
            if not isinstance(instr, str) or not instr.strip() or instr in seen:
                continue
            seen.add(instr)
            lab = "%s:%s/%s" % (name, Path(f).parent.name, str(d.get("id", "?"))[:8])
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
    ap.add_argument("--corpus", action="append", default=[], metavar="NAME=PATH",
                    help="a benchmark to compare against; repeat for several. "
                         "PATH is scanned recursively for .json/.jsonl tasks")
    ap.add_argument("--threshold", type=float, default=0.60,
                    help="flag a spec whose closest corpus match exceeds this on "
                         "either metric")
    args = ap.parse_args()

    if not args.corpus:
        args.corpus = ["osworld=/mnt/d/research/OSWorld-upstream"]

    specs = load_specs(args.specs)
    if not specs:
        print("no instructions in %s" % ", ".join(args.specs), file=sys.stderr)
        return 1

    corpora, empty = {}, []
    for entry in args.corpus:
        name, _, path = entry.partition("=")
        if not path:
            name, path = Path(name).name, name
        loaded = load_corpus(path, name)
        # An unreadable or misnamed path must be loud. A corpus that quietly
        # contributes nothing turns this whole report into a false clean bill.
        if not loaded:
            empty.append((name, path))
        corpora[name] = loaded
    if empty:
        for name, path in empty:
            print("no tasks found for corpus %r under %s" % (name, path),
                  file=sys.stderr)
        return 1

    all_rows = [row for rows in corpora.values() for row in rows]
    idf, default = build_idf(all_rows + specs)
    ref = Ref("all", all_rows, idf, default)
    per = {name: Ref(name, rows, idf, default) for name, rows in corpora.items()}
    print("%d generated instruction(s) vs %s\n"
          % (len(specs), ", ".join("%d %s" % (len(v), k) for k, v in corpora.items())))

    flagged = []
    worst = {name: (0.0, 0.0, 0.0, "-") for name in corpora}
    print("%-30s %-19s %-19s %s"
          % ("slug", "vs_corpus", "vs_siblings", "closest match"))
    print("-" * 104)
    for slug, text, _ in specs:
        sib = [(s, t, tk) for s, t, tk in specs if s != slug]
        orat, ojac, ocos, olab = closest(text, ref)
        srat, sjac, scos, _l = (closest(text, Ref("sib", sib, idf, default))
                                if sib else (0.0, 0.0, 0.0, "-"))
        for name, r_ in per.items():
            r, j, c, lab = closest(text, r_)
            if max(r, j, c) > max(worst[name][:3]):
                worst[name] = (r, j, c, "%s <- %s" % (slug[:22], lab))
        mark = " <<<" if max(orat, ojac, ocos) >= args.threshold else ""
        if mark:
            flagged.append((slug, orat, ojac, ocos, olab))
        print("%-30s r%.2f j%.2f c%.2f   r%.2f j%.2f c%.2f   %s%s"
              % (slug[:29], orat, ojac, ocos, srat, sjac, scos, olab, mark))

    print("\nworst case per corpus:")
    for name, (r, j, c, who) in worst.items():
        verdict = "OVER" if max(r, j, c) >= args.threshold else "ok"
        print("  %-12s ratio %.2f jaccard %.2f cosine %.2f  %-4s  %s"
              % (name, r, j, c, verdict, who))

    print()
    if flagged:
        print("%d spec(s) over the %.2f threshold:" % (len(flagged), args.threshold))
        for slug, r, j, c, lab in flagged:
            print("  %-30s ratio %.2f jaccard %.2f cosine %.2f  <- %s"
                  % (slug, r, j, c, lab))
        print("A high score is not proof of copying -- two tasks can share a domain "
              "and a verb. Read the pair before dropping either.")
    else:
        print("nothing over the %.2f threshold against %d corpus/corpora."
              % (args.threshold, len(corpora)))
    print("text similarity cannot see a duplicate that differs only in a constant; "
          "run ostg.sig for that.")
    return 1 if flagged else 0


if __name__ == "__main__":
    raise SystemExit(main())
