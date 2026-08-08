"""Structural duplicate detection: compare what the grader inspects, not what the
instruction says.

    python -m ostg.sig --index /mnt/d/research/cua-gym/artifacts/cua_gym_tasks_v1.tar.zst \
                       --out /mnt/d/research/cua-gym/rewards_sig.jsonl      # needs pyarrow
    python -m ostg.sig out/runs/v3/specs.jsonl --sigs /mnt/d/research/cua-gym/rewards_sig.jsonl

WHY TEXT SIMILARITY IS NOT ENOUGH
---------------------------------
ostg generated "set all body-text paragraphs to double spacing (2.0), leave
headings unchanged". CUA-Gym already contains "set the body text paragraphs to
1.5 line spacing and keep the heading paragraphs at single spacing". Same
document structure, same inspected property, same grader shape; the only
difference is the constant. ostg.contam scores that pair r0.47 j0.37 -- under any
threshold that does not also flag unrelated pairs.

The two graders express the same check, so the intent was that a signature built
from the ATTRIBUTES a grader reads -- with the CONSTANTS deliberately discarded,
since constants are what a template varies between siblings -- would collapse
them onto each other.

MEASURED RESULT: IT DOES NOT, ACROSS CORPORA
--------------------------------------------
On that exact pair the signature scores 0.097 and ranks 1254th of 10,899. The
token dumps say why:

    ostg  : zipfile parse findall xml word spacing heading style lxml docx
    cuagym: docx float format expected component critical environ ctrl body all

CUA-Gym's grader uses python-docx (`paragraph_format.line_spacing`); ostg's probe
unzips the .docx and reads the raw OOXML (`w:spacing`). Same property, same file,
disjoint vocabulary -- and CUA-Gym's per-task scoring boilerplate (`component`,
`expected`, `critical`) outweighs what little remains. Two graders can agree
completely and share almost no identifiers.

WHERE IT DOES WORK: WITHIN ONE CORPUS
-------------------------------------
Validated against CUA-Gym's own template families as ground truth (3,000 sampled
pairs each, families of >=8 variants):

    same family     median 0.274
    different family median 0.120

    threshold 0.3   43.1% of siblings found,  3.2% false positives
    threshold 0.4   18.2%                     0.6%
    threshold 0.5    6.9%                     0.0%

Real separation, weak recall. Useful for GROUPING a corpus that shares a coding
style; not a gate, and not usable across corpora that do not. For cross-corpus
contamination the working signal is `ostg.contam`'s TF-IDF cosine, which scores
that same pair 0.52 while demoting the string-similarity false positives.

The default threshold is 0.30 because that is the measured knee, not because 0.30
means anything in itself.

CUA-Gym is template-built on purpose: 7,075 of its setup scripts carry a
`TASK_ID` like `osworld_writer_line_spacing_per_paragraph_004`; those resolve to
980 families, 340 with more than one variant, together covering 6,435 tasks.
Landing in one of those families means colliding with up to 120 siblings at once.

WHAT A SIGNATURE IS
-------------------
An AST walk over the grader source collecting three things:

  modules   the libraries it reaches for -- docx, openpyxl, pptx, json, PIL.
            This is the artifact type, stated by the code rather than by a label.
  attrs     dotted attribute suffixes it reads, capped at the last two names:
            `paragraph_format.line_spacing`, `font.size`, `cell.value`. Two names
            rather than the full chain because the receiver is named differently
            in every script (`para`, `p`, `body1`) while the property is not.
  calls     the functions it calls by bare name, filtered to ones that appear in
            enough graders to mean something.

Similarity is Jaccard over `modules | attrs`. `calls` is collected and reported
but kept out of the score: helper names are author-specific noise
(`persist_app_state`, `verify_task`) and dilute a signal that attrs carries
cleanly.

This is a heuristic, not a proof. Two graders can inspect the same property for
genuinely different reasons -- every Writer font task reads `font.name`. Read the
pair before dropping either; the report prints both instructions for that.

Stdlib only in compare mode. --index needs pyarrow, because the CUA-Gym bundle is
zstd and WSL has no zstd binary.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

# Libraries that identify an artifact type. A grader importing `docx` is grading a
# Word document whatever its instruction claims; one importing only `os` and `json`
# is grading a settings file. Anything outside this set is dropped rather than
# guessed at -- `time` and `subprocess` say nothing about what is being checked.
ARTIFACT_MODULES = {
    "docx", "openpyxl", "pptx", "pandas", "csv", "json", "xml", "yaml", "toml",
    "PIL", "pdfplumber", "PyPDF2", "pypdf", "fitz", "zipfile", "tarfile",
    "sqlite3", "configparser", "mutagen", "cv2", "numpy", "bs4", "lxml",
}

# Attribute names too generic to carry signal. Without this every signature shares
# `.text` and `.value` and the floor of the Jaccard rises for everyone equally --
# which is the same disease the STOP list treats in ostg.contam.
GENERIC_ATTRS = {
    "append", "close", "copy", "count", "encode", "decode", "endswith", "exists",
    "extend", "format", "get", "group", "index", "items", "join", "keys", "items",
    "lower", "upper", "read", "readlines", "replace", "search", "split", "strip",
    "startswith", "sort", "sorted", "values", "write", "path", "name", "open",
    "print", "len", "str", "int", "float", "list", "dict", "set", "os", "sys", "re",
}


def signature(src):
    """(modules, attrs, calls) for one grader source. Constants are discarded."""
    mods, attrs, calls, lits = set(), set(), set(), set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        # A grader we cannot parse contributes nothing rather than contributing a
        # regex guess. Silently scoring it as "no overlap with anything" would be
        # the same false-clean-bill failure ostg.contam guards against, so the
        # caller is told how many were skipped.
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module.split(".")[0])
        elif isinstance(node, ast.Attribute):
            chain = []
            cur = node
            while isinstance(cur, ast.Attribute):
                chain.append(cur.attr)
                cur = cur.value
            chain.reverse()
            # Last two names: the receiver is named differently in every script
            # (`para`, `p`, `body1`) but `paragraph_format.line_spacing` is not.
            tail = ".".join(chain[-2:]) if len(chain) >= 2 else chain[-1]
            if not any(p in GENERIC_ATTRS for p in tail.split(".")):
                attrs.add(tail)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id not in GENERIC_ATTRS:
                calls.add(node.func.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # String literals name the inspected thing whenever the library does
            # not: `files.autoSave` in a settings probe, `w:spacing` in an OOXML
            # one. Long ones are prose (docstrings, failure messages) and short
            # ones are punctuation, so both ends are cut.
            v = node.value.strip()
            if 3 <= len(v) <= 48 and "\n" not in v:
                lits.add(v)
    return {
        "modules": sorted(mods & ARTIFACT_MODULES),
        "attrs": sorted(attrs),
        "calls": sorted(calls),
        "literals": sorted(lits),
    }


CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
SPLIT = re.compile(r"[^A-Za-z0-9]+")

# Word pieces that name no property. `line` and `spacing` survive; these do not.
NOISE = {
    "get", "set", "val", "true", "false", "none", "null", "self", "main", "check",
    "verify", "task", "reward", "result", "score", "total", "point", "points",
    "utf", "http", "https", "www", "com", "org", "schemas", "openxmlformats",
    "wordprocessingml", "spreadsheetml", "presentationml", "drawingml", "xmlns",
    "microsoft", "office", "document", "documents", "home", "user", "desktop",
    "tmp", "var", "usr", "etc", "path", "file", "files", "dir", "root", "out",
}


def pieces(text):
    """Word pieces of an identifier or literal, lowercased.

    Comparing whole attribute names does not work across libraries. ostg's probe
    for the double-spacing task reads raw OOXML through lxml (`w:spacing`);
    CUA-Gym's grader for the 1.5-spacing task reads python-docx
    (`paragraph_format.line_spacing`). Same property of the same file, and the
    attribute-name intersection is EMPTY. Splitting both into pieces puts
    `spacing` and `line` on both sides, which is the level at which the two
    actually agree.
    """
    out = set()
    for chunk in SPLIT.split(CAMEL.sub(" ", str(text))):
        w = chunk.lower()
        if len(w) > 2 and not w.isdigit() and w not in NOISE:
            out.add(w)
    return out


def sig_tokens(sig):
    if not sig:
        return set()
    out = set(sig["modules"])
    for a in sig["attrs"]:
        out |= pieces(a)
    for s in sig.get("literals", ()):
        out |= pieces(s)
    return out


# Below this many tokens a signature says nothing and Jaccard saturates on it: a
# probe whose whole signature is {json, load} scores 1.00 against every grader
# that opens a JSON. The first run of this module reported vscode-autosave-
# afterdelay as a 1.00 duplicate of a Jupyter notebook task for exactly that
# reason. Thin signatures are reported as such rather than scored.
MIN_TOKENS = 5


def similarity(a, b):
    ta, tb = sig_tokens(a), sig_tokens(b)
    if len(ta) < MIN_TOKENS or len(tb) < MIN_TOKENS:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# --------------------------------------------------------------------------- #
# index mode: crack the CUA-Gym bundle once into a stdlib-readable jsonl
# --------------------------------------------------------------------------- #

TASK_ID = re.compile(r"TASK_ID\s*=\s*['\"]([^'\"]+)['\"]")


def build_index(archive, out):
    import tarfile
    try:
        import pyarrow as pa
    except ImportError:
        print("--index needs pyarrow (the bundle is zstd and WSL has no zstd "
              "binary). Install it somewhere isolated -- do NOT add it to the "
              "OSWorld venv:\n"
              "  uv pip install --python <osworld-venv>/bin/python "
              "--target /mnt/d/research/cua-gym/.pylib pyarrow", file=sys.stderr)
        return 1
    raw = pa.CompressedInputStream(pa.OSFile(str(archive)), "zstd")
    tf = tarfile.open(fileobj=raw, mode="r|")
    n, bad, wrote = 0, 0, 0
    with open(out, "w", encoding="utf-8") as fh:
        for m in tf:
            # The bundle was packed on a Mac: every real file has a ._ sibling of
            # AppleDouble metadata that parses as garbage.
            if not m.isfile() or "/._" in m.name or not m.name.endswith("reward.py"):
                continue
            n += 1
            src = tf.extractfile(m).read().decode("utf-8", "replace")
            sig = signature(src)
            if sig is None:
                bad += 1
                continue
            fam = TASK_ID.search(src)
            fh.write(json.dumps({
                "id": m.name.split("/")[0],
                "family": re.sub(r"_\d+$", "", fam.group(1)) if fam else None,
                "sig": sig,
            }) + "\n")
            wrote += 1
    print("%d reward.py read, %d indexed, %d unparseable -> %s" % (n, wrote, bad, out))
    return 0


# --------------------------------------------------------------------------- #
# compare mode
# --------------------------------------------------------------------------- #

def load_sigs(path):
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("specs", nargs="*", help="one or more specs.jsonl")
    ap.add_argument("--index", metavar="TAR_ZST",
                    help="build a signature index from a CUA-Gym task bundle")
    ap.add_argument("--out", help="where --index writes its jsonl")
    ap.add_argument("--sigs", action="append", default=[], metavar="NAME=PATH",
                    help="a signature index to compare against; repeat for several")
    ap.add_argument("--instructions", action="append", default=[], metavar="NAME=PATH",
                    help="optional tasks.jsonl to look up instructions for the report")
    ap.add_argument("--threshold", type=float, default=0.30,
                    help="flag a spec whose closest grader signature exceeds this. "
                         "0.30 is the measured knee against CUA-Gym's own template "
                         "families: 43%% of siblings, 3.2%% false positives")
    args = ap.parse_args()

    if args.index:
        if not args.out:
            print("--index requires --out", file=sys.stderr)
            return 1
        return build_index(args.index, args.out)

    if not args.specs or not args.sigs:
        print("need specs and at least one --sigs NAME=PATH", file=sys.stderr)
        return 1

    text = {}
    for entry in args.instructions:
        _, _, path = entry.partition("=")
        for line in Path(path or entry).read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                text[d["id"]] = d.get("instruction", "")

    refs = {}
    for entry in args.sigs:
        name, _, path = entry.partition("=")
        if not path:
            name, path = Path(name).stem, name
        rows = load_sigs(path)
        if not rows:
            print("no signatures in %s" % path, file=sys.stderr)
            return 1
        refs[name] = rows

    specs = []
    unparseable = []
    for p in args.specs:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            probe = d.get("probe_py") or ""
            sig = signature(probe) if probe else None
            if probe and sig is None:
                unparseable.append(d.get("slug", "?"))
            specs.append((d.get("slug", "?"), d.get("instruction", ""), sig))

    print("%d spec(s) vs %s\n"
          % (len(specs), ", ".join("%d %s" % (len(v), k) for k, v in refs.items())))
    if unparseable:
        print("%d probe(s) did not parse and were scored against nothing: %s\n"
              % (len(unparseable), ", ".join(unparseable[:6])))

    flagged = []
    print("%-30s %-6s %-28s %s" % ("slug", "sig", "family", "closest grader"))
    print("-" * 100)
    for slug, instr, sig in specs:
        if not sig:
            print("%-30s   n/a  (no probe_py)" % slug[:29])
            continue
        best, bid, bfam, bname = 0.0, "-", "-", "-"
        for name, rows in refs.items():
            for r in rows:
                s = similarity(sig, r["sig"])
                if s > best:
                    best, bid, bfam, bname = s, r["id"], r.get("family") or "-", name
        mark = " <<<" if best >= args.threshold else ""
        if mark:
            flagged.append((slug, instr, best, bid, bfam, bname))
        print("%-30s %.2f   %-28s %s:%s%s"
              % (slug[:29], best, str(bfam)[:27], bname, bid[:8], mark))

    print()
    if flagged:
        print("%d spec(s) share a grader signature at or above %.2f:\n"
              % (len(flagged), args.threshold))
        for slug, instr, s, bid, fam, name in flagged:
            print("  %s  sig %.2f  <- %s family %s" % (slug, s, name, fam))
            print("    ostg  : %s" % instr[:190])
            if bid in text:
                print("    %-6s: %s" % (name[:6], text[bid][:190]))
            print()
        print("Same inspected property is not automatically the same task -- every "
              "Writer font task reads font.name. Read the pair.")
    else:
        print("no spec shares a grader signature at or above %.2f." % args.threshold)
    return 1 if flagged else 0


if __name__ == "__main__":
    raise SystemExit(main())
