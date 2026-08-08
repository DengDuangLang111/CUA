"""Office-file readers for task probes. Pure stdlib.

This module is uploaded into the VM with every generated task and imported by
the probe. The guest has lxml, PIL, requests and Xlib but NOT openpyxl,
python-docx or python-pptx, so OOXML is parsed here from the zip directly.

    import sys; sys.path.insert(0, "/home/user/.tg")
    from tghelp import read_xlsx, read_docx, read_pptx, norm

Values are returned as they appear on disk. A formula cell yields its CACHED
value, which is what LibreOffice writes on save; a formula written by a host
script that never opened the file has no cached value and yields "".
"""
import re
import zipfile
import xml.etree.ElementTree as ET

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _col(ref):
    """'BC12' -> 28 (zero-based column index)."""
    letters = re.match(r"([A-Z]+)", ref or "A").group(1)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_xlsx(path):
    """-> {sheet_name: [[cell, ...], ...]}  Cells are str; blanks are ""."""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")):
                shared.append("".join(t.text or "" for t in si.iter(_MAIN + "t")))

        rels = {}
        for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")):
            target = r.get("Target", "")
            rels[r.get("Id")] = "xl/" + target.lstrip("/").replace("xl/", "", 1)

        out = {}
        for sh in ET.fromstring(z.read("xl/workbook.xml")).iter(_MAIN + "sheet"):
            part = rels.get(sh.get(_REL + "id"))
            if not part or part not in z.namelist():
                continue
            rows = []
            for row in ET.fromstring(z.read(part)).iter(_MAIN + "row"):
                cells = []
                for c in row.iter(_MAIN + "c"):
                    i = _col(c.get("r"))
                    while len(cells) <= i:
                        cells.append("")
                    v = c.find(_MAIN + "v")
                    if c.get("t") == "s" and v is not None:
                        cells[i] = shared[int(v.text)]
                    elif c.get("t") == "inlineStr":
                        cells[i] = "".join(t.text or "" for t in c.iter(_MAIN + "t"))
                    elif v is not None:
                        cells[i] = v.text or ""
                rows.append(cells)
            # openpyxl writes no <c> element at all for a None cell, so a row
            # ending in blanks comes back short and a probe indexing r[4] raises
            # IndexError -- which surfaces as an empty stdout and a silent 0.
            # Pad every row to the widest one so sheets are rectangular.
            w = max((len(r) for r in rows), default=0)
            for r in rows:
                r.extend([""] * (w - len(r)))
            out[sh.get("name")] = rows
        return out


def read_docx(path):
    """-> [paragraph_text, ...] in document order, blanks included."""
    with zipfile.ZipFile(path) as z:
        doc = ET.fromstring(z.read("word/document.xml"))
    return ["".join(t.text or "" for t in p.iter(_W + "t")) for p in doc.iter(_W + "p")]


def read_pptx(path):
    """-> [[shape_text, ...], ...] one inner list per slide, in slide order."""
    with zipfile.ZipFile(path) as z:
        names = sorted(
            (n for n in z.namelist()
             if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
            key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)),
        )
        slides = []
        for n in names:
            root = ET.fromstring(z.read(n))
            texts = []
            for sp in root.iter():
                if sp.tag.endswith("}txBody"):
                    # One a:p is one visual line; joining every a:t blindly would
                    # glue "Budget" and "Hiring" into "BudgetHiring".
                    paras = ["".join(t.text or "" for t in p.iter(_A + "t"))
                             for p in sp.iter(_A + "p")]
                    texts.append("\n".join(paras))
            slides.append(texts)
        return slides


def norm(v):
    """Compare-friendly form: collapse whitespace, drop a trailing .0 on ints."""
    s = str(v).strip()
    s = re.sub(r"\s+", " ", s)
    if re.fullmatch(r"-?\d+\.0+", s):
        s = s.split(".")[0]
    return s


def num(v, default=None):
    """Parse a cell as float, tolerating $ and thousands separators."""
    s = re.sub(r"[,$\s]", "", str(v))
    try:
        return float(s)
    except (TypeError, ValueError):
        return default
