"""Prompt and schema for the spec generator. ROLE -> TASK -> RULES, then the
schema and one worked example carry the format.

Nothing here validates anything. The generator emits freely; quality is decided
downstream by the two host-side controls in emit.py and by the score==1.0
filter after the rollouts.
"""
import json
import random

from pathlib import Path

from ostg.contam import tokens

# The prose lives in prompts/*.txt, not in this file. It is the part a human
# actually edits and reviews, and burying 6 KB of it between two Python string
# literals made that harder than it needed to be. Read at import: the files ship
# with the package and a missing one is a broken install, not a runtime case.
PROMPTS = Path(__file__).resolve().parent / "prompts"


def _sections(name="prompt.txt"):
    """Split prompts/prompt.txt on [SECTION] headers, dropping # comment lines.

    One file rather than three because that is what a person edits, but the
    sections stay separate: ROLE and RULES go in the cached system message and
    TASK opens the user message, which is rebuilt every batch. Concatenating them
    into one blob would quietly move 5 KB out of the cache and into every request.
    """
    out, key = {}, None
    for line in (PROMPTS / name).read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            continue
        if line.startswith("[") and line.rstrip().endswith("]"):
            key = line.strip()[1:-1]
            out[key] = []
        elif key is not None:
            out[key].append(line)
    return {k: "\n".join(v).strip("\n") + "\n" for k, v in out.items()}


_S = _sections()
ROLE, TASK, RULES = _S["ROLE"], _S["TASK"], _S["RULES"]
EXAMPLE = json.loads((PROMPTS / "example.json").read_text(encoding="utf-8"))


def relevant(pool, brief, k):
    """The k instructions in `pool` most like the brief we are about to send.

    Was rng.sample. With 27 chrome tasks already written and 8 shown at random,
    the chance of missing the one that matters is 70% -- and v4 duly produced two
    IRS e-Postcard tasks from different shards that invented the same fictional
    food bank, scoring 0.64 against each other while the batch-level numbers
    improved. An avoid list that shows the wrong eight is not an avoid list.

    Content-word overlap is enough here and keeps this module stdlib-only. The
    brief has no prose to match on, so it is spelled out as its coordinates:
    'nonprofit info_seeking browser_tab chrome' does retrieve the IRS one.
    """
    q = tokens(brief)
    if not q:
        return pool[:k]
    scored = sorted(pool, key=lambda t: -len(q & tokens(t)))
    return scored[:k]

APPS = {
    "libreoffice_calc": ("libreoffice_calc", "LibreOffice Calc"),
    "libreoffice_writer": ("libreoffice_writer", "LibreOffice Writer"),
    "libreoffice_impress": ("libreoffice_impress", "LibreOffice Impress"),
    "chrome": ("chrome", "Google Chrome"),
    "gimp": ("gimp", None),
    "vlc": ("vlc", None),
    "thunderbird": ("thunderbird", None),
    "vscode": ("vscode", "Visual Studio Code"),
    "files": ("os", None),
    "terminal": ("os", None),
}

ARTIFACTS = [
    "spreadsheet", "text_document", "slide_deck", "raster_image", "media_file",
    "pdf_or_archive", "source_code", "terminal_output", "filesystem",
    "preference_store", "app_data_store", "email_store", "desktop_session",
    # 31 official tasks carry this artifact and 29 of them are graded on where
    # the browser ended up. It was missing from this list, so drawing one handed
    # the model an artifact its own schema rejected.
    "browser_tab",
]

SOURCES = ["self", "prompt_literal", "second_local_artifact", "live_web"]

# How a task is graded. Only `file` is graded by a probe we write; the other two
# hand the job to machinery OSWorld already ships, so for them there is nothing
# to write and nothing the host-side controls could check.
#
# The distinction matters because both controls run on the HOST, where there is
# no VM: they can only reach state solve_py can produce by writing files. The
# first batch that hit this produced vlc-set-loop-mode, whose probe checks
# ~/.config/vlc/vlcrc (a file solve_py wrote correctly) AND `pgrep -x vlc`. On the
# host both seed and solved print FAIL, so `positive` read "wrong:FAIL" and
# `negative` read "ok" without having tested anything. Marking the kind lets the
# report say "not applicable" instead of a failure that is not one, or -- worse --
# a green tick that verified nothing.
GOLD_KINDS = {
    "file": "probe_py reads files the agent created or edited. solve_py can "
            "reproduce the finished state on the host, so both controls are real.",
    "browser_state": "the answer is WHERE CHROME ENDED UP, not a file. Graded by "
                     "OSWorld's own url matcher against a list of regexes you "
                     "supply in url_patterns, so there is no probe_py and no "
                     "solve_py -- emit \"\" for both. Give start_url too.",
    "infeasible": "the task cannot be done in this environment and the correct "
                  "behaviour is to refuse. There is no probe and no solve_py: "
                  "OSWorld grades it from the agent's own FAIL signal.",
}

# Every non-file kind maps onto an evaluator shape OSWorld already ships, copied
# from what the official tasks do rather than reimplemented:
#
#   browser_state  func   is_expected_url_pattern_match      (chrome.py:71)
#                  result active_url_from_accessTree
#                  expect rule {"expected": [regex, ...]}    ALL must match
#                  -- 3 official chrome/multi_apps tasks are written exactly so
#   infeasible     func   infeasible, and nothing else       (27 official tasks,
#                  every one of them an evaluator with the single key "func")
#
# Deliberately NOT covered: the 8 needs_gui_only_state tasks. Official grades
# those with check_accessibility_tree, whose rules are CSS selectors or xpath
# over the GNOME accessibility XML. Writing those blind, for a desktop the
# generator never sees, is not something to ask a model to guess at.
EVALUATOR_SHAPE = {
    "browser_state": ("is_expected_url_pattern_match", "active_url_from_accessTree"),
    "infeasible": ("infeasible", None),
}

# Injected ahead of the generated programs, so the model never has to get the
# helper path or the root indirection right.
#
# P() is the guest home directory in ALL THREE programs. On the host it points at
# the build tree, which is laid out exactly like /home/user; in the VM it is
# /home/user itself. That single shared path vocabulary is what lets the same
# probe run as a host-side control and as the real grader. An earlier version had
# setup_py write into a flat directory and remapped basenames on the way out --
# it broke on every directory asset and on every target outside the uploaded set.
PROBE_PREAMBLE = '''import os, sys, traceback
TG_ROOT = os.environ.get("TG_ROOT", "/home/user")
sys.path.insert(0, os.environ.get("TG_HELP", "/tmp"))
def P(*a):
    return os.path.join(TG_ROOT, *a)
from tghelp import read_xlsx, read_docx, read_pptx, norm, num
def _tg_main():
'''

# The probe body is wrapped so that ANY exception becomes a clean FAIL on stdout.
# Without this a probe that raises prints nothing, get_vm_command_line hands the
# metric an empty string, and the task scores 0 -- correct for an idle agent, but
# indistinguishable from a correct agent hitting a probe bug. A probe that raises
# on the SOLVED state now fails the positive control instead of hiding.
PROBE_FOOTER = '''
try:
    _tg_main()
except Exception:
    traceback.print_exc(file=sys.stderr)
    print("FAIL")
'''


def build_probe(spec):
    """The exact probe source used both by the host controls and in the VM."""
    body = spec["probe_py"].rstrip("\n").splitlines() or ["pass"]
    indented = "\n".join(("    " + ln) if ln.strip() else ln for ln in body)
    return PROBE_PREAMBLE + indented + "\n" + PROBE_FOOTER

HOST_PREAMBLE = '''import os, sys
TG_ROOT = os.environ.get("TG_ROOT", ".")
def P(*a):
    p = os.path.join(TG_ROOT, *a)
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    return p
'''





def system_prompt():
    return ROLE + "\n" + RULES + "\nWorked example of one spec:\n\n" + json.dumps(
        EXAMPLE, ensure_ascii=False, indent=1) + "\n\nEmit every spec through the tool.\n"


# What each `operation` token asks the agent to do to the artifact. The label
# file carries the tokens but no glosses, and a bare token steers weakly -- with
# these one-liners the same (artifact, source) cell yields visibly different
# tasks depending on the verb, which is the whole point of adding the axis.
OPERATIONS = {
    "acquire": "locate information that is not present yet and bring it in",
    "derive": "compute new values from data already present",
    "rewrite": "replace existing content with corrected or restructured content",
    "add_element": "add something that is not there yet",
    "remove_element": "take something out",
    "set_value": "set a specific field, setting or property to a stated value",
    "restyle": "change appearance or formatting without changing the content",
    "re_encode": "produce the same content in a different format",
    "organize": "rearrange, group, rename or move things",
    "reach_state": "drive the machine or an application into a particular state",
}


def user_prompt(n, cells, priors=None, external=None, per_app=12, seed=0,
                own=None, own_per_app=8):
    priors = priors or {}
    external = external or {}
    own = own or {}
    lines = []
    for i, c in enumerate(cells):
        op = c.get("operation") or ""
        extra = ""
        if c.get("needs_setup_shell"):
            extra += ", and it needs setup_shell to install or start something"
        if c.get("intent"):
            # Taxonomy brief: intent/domain/constraints lead, because they are
            # what the model has to invent around. artifact/primary follow as
            # constraints on what it may end in.
            lines.append(
                "  spec %d: intent=%s, domain=%s, difficulty=%d, apps=%d, artifact=%s, "
                "source=%s, apps=%d, primary=%s%s"
                % (i + 1, c["intent"], c["domain"], c.get("difficulty", 0), c.get("app_count", 1),
                   c["artifact"], c["source"], c["app_count"], c["primary"], extra)
            )
        else:
            lines.append(
                "  spec %d: artifact=%s, source=%s, operation=%s, apps=%d, primary=%s, "
                "gold_kind=%s%s"
                % (i + 1, c["artifact"], c["source"], op or "any", c["app_count"],
                   c["primary"], c.get("gold_kind", "file"), extra)
            )

    kinds = sorted({c.get("gold_kind", "file") for c in cells})
    kind_text = ""
    if set(kinds) - {"file"}:
        kind_text = ("\n\ngold_kind for each spec is given above and is NOT yours to "
                     "change:\n" + "\n".join("  %s = %s" % (k, GOLD_KINDS[k])
                                             for k in kinds if k in GOLD_KINDS))

    tax = ""
    if any(c.get("intent") for c in cells):
        from ostg import taxonomy as T
        ints = sorted({c["intent"] for c in cells if c.get("intent")})
        doms = sorted({c["domain"] for c in cells if c.get("domain")})
        cons = sorted({c["difficulty"] for c in cells if c.get("difficulty")})
        tax = ("\n\nintent is what the user is fundamentally trying to get done:\n"
               + "\n".join("  %s = %s" % (i, T.INTENTS[i]) for i in ints)
               + "\n\ndomain is the business setting the scenario is dressed in "
                 "(%s). Invent realistic names, values and rules from that world -- "
                 "it is the main thing keeping two specs apart.\n"
                 % ", ".join(doms)
               + "\ndifficulty is how many APPLICATIONS the task spans and how many "
                 "explicit requirements it imposes. It is not a hint -- the spec must "
                 "match the level it was given, and apps= says how many applications "
                 "to put in the apps list.\n"
               + "\n".join("  %d = %s" % (c, T.DIFFICULTY[c][0]) for c in cons))

    ops = sorted({c.get("operation") for c in cells if c.get("operation")})
    op_text = ""
    if ops:
        op_text = ("\n\noperation is the kind of change the agent must make:\n"
                   + "\n".join("  %s = %s" % (o, OPERATIONS[o])
                               for o in ops if o in OPERATIONS))

    # Same cell, same four coordinates, every draw -- so without an explicit list
    # of what has already been written there the batches converge. Only slugs are
    # sent: they are compact and they are ours, not the official suite's.
    avoid = []
    for c in cells:
        done = priors.get((c["artifact"], c["source"])) or []
        if done:
            avoid.append("  %s / %s: %s"
                         % (c["artifact"], c["source"], ", ".join(sorted(set(done)))))
    avoid_text = ""
    if avoid:
        avoid_text = ("\n\nAlready generated in these cells. Do NOT repeat their "
                      "business scenario or their rule; go somewhere clearly "
                      "different:\n" + "\n".join(sorted(set(avoid))))

    # Real instructions from suites that already exist publicly. Slugs are enough
    # for our own history -- we wrote those and the model can infer the scenario
    # from the name -- but nothing can be inferred from a CUA-Gym id, so these go
    # in as full text. Only the apps this batch actually targets are included; a
    # Writer cell learns nothing from GIMP examples and the budget is finite.
    #
    # Sampled deterministically from `seed` so a rerun of the same batch sends the
    # same prompt, and so successive batches see DIFFERENT examples from the same
    # app rather than the same twelve every time.
    # Our own earlier instructions for the apps in this batch, grouped by
    # APPLICATION rather than by cell. The per-cell list above missed the two
    # closest pairs a 185-spec run produced: a VLC "loop fullscreen unattended"
    # task written once for an estate agency and once for a clinic, and the same
    # VS Code settings repair written twice. Different cells, different business
    # domains, same task -- because VLC has only a handful of settings worth a
    # task, and dressing changes the nouns, not the verb.
    #
    # Full instructions, not slugs: a slug says what we called it, and the model
    # has to recognise what it WAS.
    ours = []
    for app in sorted({c.get("primary") for c in cells if c.get("primary")}):
        pool = own.get(app) or []
        if not pool:
            continue
        brief = " ".join(sorted({"%s %s %s %s" % (c.get("intent") or "", c.get("domain") or "",
                                                   c.get("artifact") or "", app)
                                 for c in cells if c.get("primary") == app}))
        shown = relevant(pool, brief, own_per_app)
        ours.append("  %s (we have written %d; %d shown):\n%s"
                    % (app, len(pool), len(shown),
                       "\n".join("    - " + i.replace("\n", " ")[:200] for i in shown)))
    own_text = ""
    if ours:
        own_text = ("\n\nWE have already written these, for the same applications. "
                    "Do not write any of them again in different clothes: a task is "
                    "the same task if it acts on the same kind of state through the "
                    "same application, however different the industry, the file "
                    "names and the numbers are.\n" + "\n".join(ours))

    ext = []
    for app in sorted({c.get("primary") for c in cells if c.get("primary")}):
        pool = external.get(app) or []
        if not pool:
            continue
        brief = " ".join(sorted({"%s %s %s %s" % (c.get("intent") or "", c.get("domain") or "",
                                                   c.get("artifact") or "", app)
                                 for c in cells if c.get("primary") == app}))
        shown = relevant(pool, brief, per_app)
        ext.append("  %s (%d such tasks exist; %d shown):\n%s"
                   % (app, len(pool), len(shown),
                      "\n".join("    - " + i.replace("\n", " ")[:220] for i in shown)))
    ext_text = ""
    if ext:
        ext_text = ("\n\nThese tasks ALREADY EXIST in public benchmarks for the apps "
                    "in this batch. They are shown so you do not reinvent them. A "
                    "task that differs from one of these only in a constant -- a "
                    "different font size, a different line spacing, a different "
                    "column name -- counts as the same task and is worthless. Go "
                    "somewhere structurally different: inspect a different property, "
                    "or impose a rule none of these impose.\n" + "\n".join(ext))

    return (
        TASK.format(n=n)
        + "\nPer-spec targets, in order:\n"
        + "\n".join(lines)
        + kind_text
        + tax
        + op_text
        + "\n\nartifact is what the probe inspects. source is where the information "
        "needed to do the task comes from: self = inside the artifact itself, "
        "prompt_literal = stated in the instruction, second_local_artifact = a "
        "different local file the agent must also open. Put the primary application "
        "first in apps."
        + avoid_text
        + own_text
        + ext_text
        + "\n\nMake the batch diverse: different business domains, "
        "different kinds of work. Two specs must not share a business rule.\n"
    )



SCHEMA = {
    "type": "object",
    "required": ["specs"],
    "properties": {
        "specs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["slug", "instruction", "artifact", "source", "apps",
                             "app_count", "setup_py", "solve_py", "probe_py"],
                "properties": {
                    "slug": {"type": "string", "description": "unique, lowercase, <40 chars"},
                    "gold_kind": {
                        "type": "string", "enum": list(GOLD_KINDS),
                        "description": "how the task is graded, default file. "
                                       + "; ".join("%s = %s" % kv for kv in GOLD_KINDS.items()),
                    },
                    "setup_shell": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "shell commands run INSIDE THE VM before the agent starts, "
                                       "as the desktop user. System changes need sudo with the "
                                       "password piped in: \"echo {CLIENT_PASSWORD} | sudo -S "
                                       "apt-get install -y jq\". Omit unless the task genuinely "
                                       "needs something installed or started.",
                    },
                    "start_url": {
                        "type": "string",
                        "description": "gold_kind=browser_state only: the page Chrome is opened "
                                       "at before the agent starts.",
                    },
                    "url_patterns": {
                        "type": "array", "items": {"type": "string"},
                        "description": "gold_kind=browser_state only: regexes the FINAL url must "
                                       "all match. re.search, so an unanchored fragment matches "
                                       "anywhere; escape dots you mean literally.",
                    },
                    "url_stability": {
                        "type": "string",
                        "description": "required when source=live_web: argue why this answer will "
                                       "not change. Acceptable: stable site structure, historical "
                                       "facts, archived pages, a URL pinned to a version or a "
                                       "Wikipedia oldid. Not acceptable: prices, rankings, "
                                       "availability, anything dated today.",
                    },
                    "instruction": {"type": "string", "description": "what the user wants; complete on its own; never states the answer"},
                    "artifact": {"type": "string", "enum": ARTIFACTS, "description": "what probe_py inspects"},
                    "source": {"type": "string", "enum": SOURCES},
                    "apps": {"type": "array", "items": {"type": "string", "enum": list(APPS)},
                             "description": "applications the agent must open and interact with, PRIMARY FIRST"},
                    "app_count": {"type": "integer", "minimum": 1, "maximum": 3},
                    "open_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "home-relative paths to open in their application before the agent starts, e.g. Desktop/sales.xlsx. Everything setup_py writes is uploaded regardless.",
                    },
                    "save_target": {"type": "string", "description": "home-relative path the agent edits in place, if any; flushed to disk before probing"},
                    "setup_py": {"type": "string", "description": "writes the starting files with P()"},
                    "solve_py": {"type": "string", "description": "turns the starting files into the finished state, in place, with P()"},
                    "probe_py": {"type": "string", "description": "VM program; prints exactly PASS or FAIL"},
                },
            },
        }
    },
}


def tool_definition(name="emit_task_specs"):
    return {
        "name": name,
        "description": "Emit the batch of task specs.",
        "input_schema": SCHEMA,
    }
