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

Both are reported with two metrics, because a paraphrase defeats one and not the
other:

  ratio    difflib.SequenceMatcher over characters -- catches near-verbatim text
  jaccard  overlap of content-word sets -- catches "same task, reworded"

WHAT THIS DOES NOT CATCH
------------------------
Instruction text is the only signal here. Two tasks can share no wording and
still be the same task -- same starting file, same required end state, different
prose. Nothing below compares setup, gold or evaluator, so a low score is
evidence of non-copying, not proof of a distinct task.

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

    ref = [row for rows in corpora.values() for row in rows]
    print("%d generated instruction(s) vs %s\n"
          % (len(specs), ", ".join("%d %s" % (len(v), k) for k, v in corpora.items())))

    flagged = []
    worst = {name: (0.0, 0.0, "-") for name in corpora}
    print("%-34s %-13s %-13s %s" % ("slug", "vs_corpus", "vs_siblings", "closest match"))
    print("-" * 96)
    for slug, text, _ in specs:
        siblings = [(s, t, tk) for s, t, tk in specs if s != slug]
        orat, ojac, olab = closest(text, ref)
        srat, sjac, _slab = closest(text, siblings) if siblings else (0.0, 0.0, "-")
        for name, rows in corpora.items():
            r, j, lab = closest(text, rows)
            if max(r, j) > max(worst[name][0], worst[name][1]):
                worst[name] = (r, j, "%s <- %s" % (slug[:24], lab))
        mark = " <<<" if max(orat, ojac) >= args.threshold else ""
        if mark:
            flagged.append((slug, orat, ojac, olab))
        print("%-34s r%.2f j%.2f   r%.2f j%.2f   %s%s"
              % (slug[:33], orat, ojac, srat, sjac, olab, mark))

    print("\nworst case per corpus:")
    for name, (r, j, who) in worst.items():
        verdict = "OVER" if max(r, j) >= args.threshold else "ok"
        print("  %-12s ratio %.2f jaccard %.2f  %-4s  %s" % (name, r, j, verdict, who))

    print()
    if flagged:
        print("%d spec(s) over the %.2f threshold:" % (len(flagged), args.threshold))
        for slug, r, j, lab in flagged:
            print("  %-34s ratio %.2f jaccard %.2f  <- %s" % (slug, r, j, lab))
        print("A high score is not proof of copying -- two tasks can share a domain "
              "and a verb. Read the pair before dropping either.")
    else:
        print("nothing over the %.2f threshold against %d corpus/corpora."
              % (args.threshold, len(corpora)))
    return 1 if flagged else 0


if __name__ == "__main__":
    raise SystemExit(main())
