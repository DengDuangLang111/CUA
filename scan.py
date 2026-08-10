"""Grader-defect scan -- static heuristics for the defect classes that pass
every mechanical gate AND the VM controls, then surface as wrongful
convictions in the rollout (RUNBOOK section 2, classes 1-5). Wired into ship
as a REVIEW stage: findings are printed for adjudication, not hard-blocked,
because every heuristic here has known benign look-alikes (README.md, same
-basename exports, filter-qualified conversions).

Calibration ledger (v11, 119 specs): class 1 caught 1 real (hr-probation),
class 2 caught 4 real of 13 flagged, class 3 caught 1 real, class 4 caught
1 real of 2 flagged (its sibling had the correct default), class 5 caught 1
real (the course-code inversion -- which VM control also catches, later).
"""
import json
import re
import sys

FLEX = ("glob", "listdir", "walk(", "iglob", "scandir", "rglob", "fnmatch")
CONTENT = (">", "write(", "printf", "curl", "wget", "cp ", "unzip", "tar ",
           "base64", "echo ", "convert", "mv ", "ln -s", "python3 -c",
           "Workbook", "zipfile", "pptx", "docx")
CONVENTIONAL = ("README.md", "content.xml", "Preferences", "prefs.js",
                "settings.json", "vlcrc", "bookmarks", "tasks.json")
SRC = re.compile(r"\b(my|the|from)\s+\w*\s*(notes?|log|sheet|folder|file|doc"
                 r"|list|records?|inbox|csv)\b", re.I)
YEARWORD = re.compile(r"\b(this year|today|current year|this month)\b", re.I)
HARDDATE = re.compile(r"\b20(2[0-9])\b")
CONFIGPATH = re.compile(r"(Preferences|prefs\.js|vlcrc|settings\.json|"
                        r"\.config/|gtk-3\.0)")
GET_TRUE = re.compile(r"\.get\(\s*['\"][\w_]+['\"]\s*,\s*True\s*\)")
INVERTED = re.compile(r"['\"]FAIL['\"]\s*if\s*(hit|found|ok|passed|success|done)\b")


def scan_spec(s):
    """Yield (class, detail) findings for one spec."""
    instr = s.get("instruction") or ""
    setup = s.get("setup") or ""
    probe = s.get("probe") or ""
    browser = (s.get("grade") == "browser")

    # 1 missing source data: instruction cites content the setup never writes
    if not browser and setup and not any(t in setup for t in CONTENT) \
            and SRC.search(instr):
        yield ("missing-source", "setup writes no content yet instruction "
               "references a source (%r)" % SRC.search(instr).group(0))

    # 2 rigid output naming: probe demands an exact name for an artifact the
    #   instruction only describes and the setup does not create
    if not browser and (s.get("ambiguity") or 1) >= 2 and probe \
            and not any(t in probe for t in FLEX):
        names = set(re.findall(
            r"['\"](/home/user/[^'\"]+\.\w{2,4}|[\w-]+\.\w{2,4})['\"]", probe))
        setup_stems = {p.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
                       for p in re.findall(r"[\w/.-]+\.\w{2,4}", setup)}
        for x in sorted(names):
            base = x.rsplit("/", 1)[-1]
            stem = base.rsplit(".", 1)[0]
            if base in CONVENTIONAL or base in setup or x in setup:
                continue
            if base.lower() in instr.lower() \
                    or stem.replace("_", " ").replace("-", " ") in instr.lower():
                continue
            if stem.lower() in setup_stems:      # same-basename export
                continue
            yield ("rigid-name", "probe demands %r; instruction never names "
                   "it and setup never creates it" % x)
            break

    # 3 dated constant vs deictic time
    if YEARWORD.search(instr) and HARDDATE.search(probe):
        yield ("dated-constant", "instruction says %r, probe hard-codes %s"
               % (YEARWORD.search(instr).group(0),
                  sorted(set(HARDDATE.findall(probe)))))

    # 4 absent-key default: .get(key, True) on an app config read judges the
    #   app's factory state (key absent) as a failure
    if CONFIGPATH.search(probe) and GET_TRUE.search(probe):
        yield ("absent-key-default", "probe reads app config with %s -- "
               "verify the app's factory state really is True"
               % GET_TRUE.search(probe).group(0))

    # 5 inverted verdict suspicion
    if INVERTED.search(probe):
        yield ("inverted-verdict?", "probe prints FAIL when %r is truthy"
               % INVERTED.search(probe).group(1))


def main(paths):
    findings = 0
    for path in paths:
        for line in open(path, encoding="utf-8"):
            if not line.strip():
                continue
            s = json.loads(line)
            for cls, why in scan_spec(s):
                findings += 1
                print("  REVIEW %-16s %-38s %s"
                      % (cls, s.get("slug", "?"), why[:90]))
    print("[scan] grader-defect review items: %d "
          "(adjudicate each; none block the ship)" % findings)
    return findings


if __name__ == "__main__":
    main(sys.argv[1:])
