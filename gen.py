"""Generate self-contained OSWorld tasks with Claude, in one pass.

    python -m ostg.gen --n 5 --batches 4 --thinking --out out/runs/v8/specs.jsonl

Each batch: draw taxonomy cells, prompt the model, append specs.jsonl, and
write runnable task JSON (examples/<domain>/<id>.json + manifest.json) next to
it. specs.jsonl doubles as the avoid-list memory across runs.

The task JSON leans on three facts checked against the OSWorld source:
the expected getter reads `rules` (plural); vm_command_line returns raw stdout
(PASS arrives as "PASS\n", which check_include_exclude tolerates and
exact_match does not); and setup exit codes are never checked, so a broken
setup is silent -- ostg.control exists to catch that before rollouts.
"""
import argparse
import collections
import json
import os
import random
import re
import socket
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from ostg import taxonomy as T

HERE = Path(__file__).resolve().parent
PROMPTS = HERE / "prompts"
TOOL = "emit_task_specs"
# v6's namespace: a slug keeps its id across versions, so results can be joined.
NS = uuid.UUID("2f8e41b6-7c05-5d93-9a12-6be0d47cf381")

# app -> OSWorld domain (the examples/ subdirectory and manifest key).
APPS = {
    "libreoffice_calc": "libreoffice_calc",
    "libreoffice_writer": "libreoffice_writer",
    "libreoffice_impress": "libreoffice_impress",
    "chrome": "chrome",
    "gimp": "gimp",
    "vlc": "vlc",
    "thunderbird": "thunderbird",
    "vscode": "vs_code",
    "files": "os",
    "terminal": "os",
}

SCHEMA = {
    "type": "object",
    "required": ["specs"],
    "properties": {
        "specs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["slug", "instruction", "apps"],
                "properties": {
                    "slug": {"type": "string",
                             "description": "unique, lowercase, under 40 characters"},
                    "instruction": {
                        "type": "string",
                        "description": "what the user wants, in their voice. Complete on its "
                                       "own, and it never states the answer the probe checks."},
                    "apps": {"type": "array",
                             "items": {"type": "string", "enum": list(APPS)},
                             "description": "applications the agent must use, PRIMARY FIRST"},
                    "setup": {
                        "type": "string",
                        "description": "ONE shell command, run inside the VM as the desktop "
                                       "user before the agent starts. It creates every file and "
                                       "directory the task begins from. Office files are made by "
                                       "writing CSV and calling soffice --headless --convert-to, "
                                       "because the VM has LibreOffice but not openpyxl."},
                    "probe": {
                        "type": "string",
                        "description": "a python3 program, run inside the VM after the agent "
                                       "stops. It inspects the machine and prints exactly PASS "
                                       "or exactly FAIL. Write it as real lines of Python: it is "
                                       "used verbatim, so a newline is a newline."},
                    "open_path": {
                        "type": "string",
                        "description": "optional absolute path opened in its application before "
                                       "the agent starts, e.g. /home/user/Desktop/sales.xlsx"},
                    "probe_reads": {
                        "type": "string",
                        "description": "the file or setting the probe reads and the value it "
                                       "compares against, in one line. Naming it forces the "
                                       "check to exist before the scenario is written."},
                    "table_target": {
                        "type": "string",
                        "description": "grade=table only: absolute path of the .xlsx under "
                                       "/home/user the finished work lives in"},
                    "table_rules": {
                        "type": "array", "items": {"type": "object"},
                        "description": "grade=table only: check_cell rules judged on the host, "
                                       "e.g. {\"type\":\"check_cell\",\"sheet_idx\":0,"
                                       "\"coordinate\":\"E3\",\"props\":{\"value\":"
                                       "{\"method\":\"approx:0.01\",\"ref\":191.67}}}. "
                                       "Methods: eq, ne, gt, ge, lt, le, approx:THRESHOLD, re."},
                    "start_url": {
                        "type": "string",
                        "description": "grade=browser only: the page Chrome is opened at "
                                       "before the agent starts"},
                    "url_patterns": {
                        "type": "array", "items": {"type": "string"},
                        "description": "grade=browser only: regexes the FINAL url must ALL "
                                       "match (re.search). Escape dots you mean literally."},
                    "url_stability": {
                        "type": "string",
                        "description": "grade=browser only: one sentence arguing why this "
                                       "answer will not change -- stable site structure, "
                                       "historical facts, versioned docs. Never prices, "
                                       "rankings, availability."},
                },
            },
        }
    },
}


def _sections(name):
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


_S = _sections("single_json.txt")
SYSTEM, USER_HEAD = _S["SYSTEM"], _S["USER"]

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


def relevant(pool, brief, k):
    """The k instructions most like the brief, by content-word overlap."""
    q = tokens(brief)
    if not q:
        return pool[:k]
    return sorted(pool, key=lambda t: -len(q & tokens(t)))[:k]


def system_prompt():
    return SYSTEM + ("\n<output>\nThe examples show the shape. Emit your tasks "
                     "through the tool.\n</output>\n")


def user_prompt(n, cells, external=None, own=None, per_app=12, own_per_app=8):
    external = external or {}
    own = own or {}
    lines = []
    for i, c in enumerate(cells):
        lines.append(
            "  spec %d: intent=%s, domain=%s, difficulty=%d, apps=%d, artifact=%s, "
            "source=%s, primary=%s, grade=%s, ambiguity=%d, voice=%s, warm=%s, "
            "limit=%dch(~%dw)"
            % (i + 1, c["intent"], c["domain"], c["difficulty"], c["app_count"],
               c["artifact"], c["source"], c["primary"], c.get("grade", "probe"),
               c["ambiguity"], c["voice"],
               "yes" if c.get("warm") else "no",
               {1: 150, 2: 150, 3: 250}.get(c["difficulty"], 300),
               {1: 150, 2: 150, 3: 250}.get(c["difficulty"], 300) // 6))

    ints = sorted({c["intent"] for c in cells})
    doms = sorted({c["domain"] for c in cells})
    cons = sorted({c["difficulty"] for c in cells})
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
           + "\n".join("  %d = %s" % (c, T.DIFFICULTY[c][0]) for c in cons)
           + "\n\nambiguity is how explicitly the instruction may point at its "
             "objects. The check stays exact at every level -- only the wording "
             "loosens (see <ambiguity>):\n"
           + "\n".join("  %d = %s" % (a, T.AMBIGUITY[a])
                       for a in sorted({c["ambiguity"] for c in cells}))
           + "\n\nvoice is the register the instruction is written in:\n"
           + "\n".join("  %s = %s" % (v, T.VOICES[v])
                       for v in sorted({c["voice"] for c in cells}))
           + "\n\nwarm says whether the workspace starts already open (see "
             "<warm_start>): warm=yes tasks SET open_path and may assume the "
             "document/app is on screen; warm=no tasks set NO open_path and "
             "their instruction must not presume anything is open.")

    def brief_for(app):
        return " ".join(sorted({"%s %s %s %s" % (c["intent"], c["domain"],
                                                 c["artifact"], app)
                                for c in cells if c["primary"] == app}))

    ours = []
    for app in sorted({c["primary"] for c in cells}):
        pool = own.get(app) or []
        if not pool:
            continue
        shown = relevant(pool, brief_for(app), own_per_app)
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
    for app in sorted({c["primary"] for c in cells}):
        pool = external.get(app) or []
        if not pool:
            continue
        shown = relevant(pool, brief_for(app), per_app)
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
        USER_HEAD.format(n=n)
        + "\nPer-spec targets, in order:\n"
        + "\n".join(lines)
        + tax
        + "\n\nartifact is what the probe inspects. source is where the information "
        "needed to do the task comes from: self = inside the artifact itself, "
        "prompt_literal = stated in the instruction, second_local_artifact = a "
        "different local file the agent must also open. Put the primary application "
        "first in apps."
        + own_text
        + ext_text
        + "\n\nMake the batch diverse: different business domains, "
        "different kinds of work. Two specs must not share a business rule.\n"
    )


def tool_definition(name=TOOL):
    return {"name": name,
            "description": "Emit the finished task specs.",
            "input_schema": SCHEMA}


def load_env(path=".env"):
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def call(messages, system_blocks, cfg, timeout=900, tool=None):
    tool = tool or tool_definition()
    payload = {
        "model": cfg["model"],
        "max_tokens": cfg["max_tokens"],
        "system": system_blocks,
        "messages": messages,
        "tools": [tool],
        "tool_choice": {"type": "tool", "name": tool["name"]},
    }
    # Thinking and a forced tool choice are mutually exclusive; auto makes the
    # tool call probable rather than guaranteed, hence the retry in the caller.
    if cfg.get("thinking"):
        payload["thinking"] = {"type": "adaptive"}
        payload["tool_choice"] = {"type": "auto"}
    else:
        # Explicit, not omitted: Opus 5 thinks by default, and the forced tool
        # choice above demands thinking off.
        payload["thinking"] = {"type": "disabled"}
    # Streaming is about the gateway: a batch sends nothing for minutes, nginx
    # hits proxy_read_timeout and answers 504 before Anthropic is ever reached.
    # An event stream keeps bytes moving, so the timeout never arms.
    if cfg.get("stream"):
        payload["stream"] = True
    req = urllib.request.Request(
        cfg["base"] + "/v1/messages",
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json",
                 "anthropic-version": "2023-06-01",
                 "x-api-key": cfg["key"]},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if payload.get("stream"):
                return _assemble(r)
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:600]
        err = RuntimeError("HTTP %d: %s" % (e.code, body))
        err.transient = e.code == 429 or 500 <= e.code < 600
        raise err from None
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        # A timeout or a dropped connection must not kill the remaining batches.
        err = RuntimeError("network: %s" % e)
        err.transient = True
        raise err from None


def _assemble(response):
    """Rebuild the non-streaming response shape from an SSE event stream, so
    callers cannot tell the difference. Handles the three block types this
    generator can receive: text, thinking, tool_use (partial_json fragments)."""
    blocks, out = {}, {"content": [], "usage": {}, "stop_reason": None}
    for raw in response:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        try:
            ev = json.loads(line[5:].strip())
        except ValueError:
            continue
        kind = ev.get("type")
        if kind == "message_start":
            out["usage"] = dict(ev.get("message", {}).get("usage") or {})
        elif kind == "content_block_start":
            blocks[ev["index"]] = dict(ev["content_block"])
            blocks[ev["index"]]["_json"] = ""
        elif kind == "content_block_delta":
            b = blocks.setdefault(ev["index"], {"type": "text", "text": "", "_json": ""})
            d = ev.get("delta", {})
            if d.get("type") == "text_delta":
                b["text"] = b.get("text", "") + d.get("text", "")
            elif d.get("type") == "thinking_delta":
                b["thinking"] = b.get("thinking", "") + d.get("thinking", "")
            elif d.get("type") == "input_json_delta":
                b["_json"] += d.get("partial_json", "")
        elif kind == "message_delta":
            out["stop_reason"] = (ev.get("delta") or {}).get("stop_reason")
            out["usage"].update(ev.get("usage") or {})
    for i in sorted(blocks):
        b = blocks[i]
        frag = b.pop("_json", "")
        if b.get("type") == "tool_use":
            try:
                b["input"] = json.loads(frag) if frag else b.get("input") or {}
            except ValueError:
                continue  # truncated tool call: extract() raises, the retry covers it
        out["content"].append(b)
    return out


def extract(resp, name=TOOL, field="specs"):
    for b in resp.get("content", []):
        if b.get("type") == "tool_use" and b.get("name") == name:
            inp = b.get("input", {})
            out = inp.get(field, []) if field else inp
            # The schema is not server-enforced: the model sometimes returns
            # the array (or an element) as a JSON string. Parse it back.
            if isinstance(out, str):
                try:
                    out = json.loads(out)
                except ValueError:
                    return []   # unparseable string: nothing recoverable
            if isinstance(out, list):
                fixed = []
                for x in out:
                    if isinstance(x, str):
                        try:
                            x = json.loads(x)
                        except ValueError:
                            continue
                    if isinstance(x, dict):
                        fixed.append(x)
                out = fixed
            return out
    raise RuntimeError("no tool_use block (stop_reason=%s)" % resp.get("stop_reason"))


def call_and_extract(messages, system_blocks, cfg, tries=3, tool=None, field="specs"):
    for attempt in range(1, tries + 1):
        try:
            resp = call(messages, system_blocks, cfg, tool=tool)
        except RuntimeError as e:
            if attempt == tries or not getattr(e, "transient", False):
                raise
            print("  retry %d/%d after %s" % (attempt, tries - 1, str(e)[:60]))
            continue
        thought = sum(1 for b in resp.get("content", []) if b.get("type") == "thinking")
        try:
            specs = extract(resp, name=(tool or tool_definition())["name"], field=field)
        except RuntimeError as e:
            if attempt == tries:
                raise
            print("  retry %d/%d: %s" % (attempt, tries - 1, e))
            continue
        return specs, resp, thought
    raise AssertionError("unreachable")


# The wrapper exists so an uncaught exception reaches stdout as FAIL instead of
# an empty string a metric cannot tell from an idle agent.
PROBE_WRAPPER = """import sys, traceback
def _main():
%s

try:
    _main()
except Exception:
    traceback.print_exc(file=sys.stderr)
    print("FAIL")
"""


def wrap_probe(body):
    lines = (body or "").rstrip("\n").splitlines()
    return PROBE_WRAPPER % "\n".join(("    " + l) if l.strip() else l for l in lines)


# Documents where ctrl+s saves silently in the official VM image; anything
# else (GIMP's export dialog, plain text editors) is left alone.
_FLUSH_APP = {".xlsx": "LibreOffice Calc", ".ods": "LibreOffice Calc",
              ".odt": "LibreOffice Writer", ".odp": "LibreOffice Impress"}


def _flush_postconfig(path):
    """The official calc pattern: focus the document window and ctrl+s, so an
    unsaved GUI buffer cannot fail the grade. Every step logs on failure
    instead of raising, so a closed window cannot erase result.txt."""
    app = _FLUSH_APP.get(os.path.splitext(path)[1].lower())
    if not app:
        return None
    return [
        {"type": "activate_window", "parameters": {
            "window_name": "%s - %s" % (os.path.basename(path), app),
            "strict": True}},
        {"type": "sleep", "parameters": {"seconds": 0.5}},
        {"type": "execute", "parameters": {
            "command": ["python", "-c",
                        "import pyautogui; pyautogui.hotkey(\"ctrl\", \"s\");"]}},
        {"type": "sleep", "parameters": {"seconds": 0.5}},
    ]


def task_json(spec, batch):
    apps = spec.get("apps") or ["files"]
    domain = APPS.get(apps[0], "os")
    grade = spec.get("grade") or "probe"

    # shell=True: the setup is one command line with quoting in it, run by
    # /bin/sh. No `until`: a non-zero exit would retry forever (OSWorld
    # counts only HTTP failures toward the cap).
    config = []
    if (spec.get("setup") or "").strip():
        config.append({"type": "execute",
                       "parameters": {"command": spec["setup"], "shell": True}})
    prim = apps[0] if apps else ""
    if spec.get("open_path") and grade != "browser":
        # Warm start, matched to the app the way the official corpus does it.
        # xdg-open hands html to a browser and 500s; gimp/vlc/code cold starts
        # are flaky through /setup/open_file -- launch those directly.
        if "soffice" in (spec.get("setup") or ""):
            # A headless soffice left over from the setup's --convert-to
            # swallows the subsequent open: the document routes into the
            # headless instance and no window ever maps (measured: 0/15 calc
            # in the first v11 rollout). Clear it before opening.
            config.append({"type": "execute", "parameters": {
                "command": "pkill -f soffice.bin; sleep 2; true", "shell": True}})
        p = spec["open_path"]
        low = p.lower()
        if low.endswith((".html", ".htm")):
            config.append({"type": "launch", "parameters": {
                "command": ["google-chrome", "file://" + p]}})
        elif prim == "gimp" or low.endswith((".xcf", ".png", ".jpg", ".jpeg")):
            config.append({"type": "launch", "parameters": {"command": ["gimp", p]}})
        elif prim == "vscode":
            config.append({"type": "launch", "parameters": {"command": ["code", p]}})
        elif prim == "vlc" or low.endswith((".mp4", ".mp3", ".mkv", ".avi")):
            config.append({"type": "launch", "parameters": {"command": ["vlc", p]}})
        else:
            config.append({"type": "open", "parameters": {"path": p}})
    elif spec.get("warm") and grade != "browser" and prim == "thunderbird":
        config.append({"type": "launch", "parameters": {"command": ["thunderbird"]}})

    if grade == "browser":
        # The official chrome template: debug port for chrome_open_tabs, socat
        # so the CDP endpoint is reachable, then the start page.
        config += [
            {"type": "launch", "parameters": {
                "command": ["google-chrome", "--remote-debugging-port=1337"]}},
            {"type": "launch", "parameters": {
                "command": ["socat", "tcp-listen:9222,fork", "tcp:localhost:1337"]}},
            {"type": "chrome_open_tabs", "parameters": {
                "urls_to_open": [spec["start_url"]]}},
            {"type": "activate_window", "parameters": {
                "window_name": "Google Chrome"}},
        ]
        evaluator = {
            "func": "is_expected_url_pattern_match",
            "result": {"type": "active_url_from_accessTree",
                       "goto_prefix": "https://www."},
            "expected": {"type": "rule",
                         "rules": {"expected": spec["url_patterns"]}},
        }
    elif grade == "table":
        target = spec["table_target"]
        evaluator = {
            "func": "compare_table",
            "result": {"type": "vm_file", "path": target,
                       "dest": os.path.basename(target)},
            "options": {"rules": spec["table_rules"]},
        }
        flush = _flush_postconfig(target)
        if flush:
            evaluator["postconfig"] = flush
    else:
        # `rules`, plural: the getter reads config["rules"]. check_include_exclude
        # rather than exact_match because stdout arrives raw, "PASS\n".
        evaluator = {
            "func": "check_include_exclude",
            "result": {"type": "vm_command_line",
                       "command": ["python3", "-c", wrap_probe(spec.get("probe"))]},
            "expected": {"type": "rule",
                         "rules": {"include": ["PASS"], "exclude": ["FAIL"]}},
        }
        # A document the agent edits in a GUI app may sit unsaved when the
        # probe reads the disk; flush it the way official calc tasks do.
        if spec.get("open_path"):
            flush = _flush_postconfig(spec["open_path"])
            if flush:
                evaluator["postconfig"] = flush
        # Chrome writes Web Data / Preferences lazily; a probe reading them
        # while Chrome runs sees stale state (confirmed false-FAIL on a task
        # the agent had done perfectly). Quit Chrome before grading so it
        # flushes -- the browser counterpart of the LibreOffice flush.
        p = spec.get("probe") or ""
        if ".config/google-chrome" in p or "Web Data" in p:
            steps = list(evaluator.get("postconfig") or [])
            steps.append({"type": "execute", "parameters": {
                "command": "pkill -TERM -f google-chrome; sleep 4", "shell": True}})
            evaluator["postconfig"] = steps

    return domain, {
        "id": str(uuid.uuid5(NS, "%s/%s" % (batch, spec["slug"]))),
        "snapshot": domain,
        "instruction": spec["instruction"],
        "source": "generated: ostg/%s#%s" % (batch, spec["slug"]),
        "config": config,
        "related_apps": apps,
        "evaluator": evaluator,
        "ostg": {"slug": spec["slug"], "batch": batch, "grade": grade,
                 "intent": spec.get("intent"), "domain": spec.get("domain"),
                 "difficulty": spec.get("difficulty"),
                 "ambiguity": spec.get("ambiguity"), "voice": spec.get("voice"),
                 "app_count": spec.get("app_count")},
    }


def read_own(files):
    """(slugs seen, app -> instructions) across every specs.jsonl given."""
    seen, own = set(), collections.defaultdict(list)
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not r.get("slug"):
                continue
            seen.add(r["slug"])
            app = (r.get("apps") or [None])[0]
            if app and r.get("instruction"):
                own[app].append(r["instruction"])
    return seen, own


_PYC = re.compile(r'^\s*python3?\s+-c\s+(["\'])(.*)\1\s*$', re.S)


def _setup_compiles(setup):
    """SyntaxError in a `python3 -c` setup, or None. Catches the newline
    double-escape (a literal backslash-n between statements) that cost two of
    the first twenty specs their setup, silently, in a real VM."""
    m = _PYC.match(setup)
    if not m:
        return None
    body = m.group(2)
    if m.group(1) == '"':
        body = re.sub(r'\\([\\"$`])', r'\1', body)
    try:
        compile(body, "<setup>", "exec")
    except SyntaxError as e:
        return "setup python SyntaxError: %s" % str(e)[:80]
    return None


REPAIR_TOOL = {
    "name": "repair_instruction",
    "description": "Return the rewritten instruction.",
    "input_schema": {"type": "object",
                     "properties": {"instruction": {"type": "string"}},
                     "required": ["instruction"]},
}

_REPAIRABLE = ("filename in", "absolute path in", "instruction over",
               "terse/sloppy instruction over")


def repair_instruction(spec, why, cfg):
    """One cheap rewrite instead of discarding the whole spec."""
    cap = {1: 150, 2: 150, 3: 250}.get(spec.get("difficulty") or 3, 300)
    ctx = json.dumps({k: spec.get(k) for k in
                      ("setup", "probe", "table_target", "table_rules",
                       "start_url", "url_patterns", "open_path")},
                     ensure_ascii=False)[:1400]
    user = ("This task instruction was rejected: %s\n\n"
            "instruction: %s\n\n"
            "environment (unchangeable, for consistency): %s\n\n"
            "Rewrite ONLY the instruction. Same task, same meaning, consistent "
            "with the environment. ambiguity=%s (at levels 2-4 refer to objects "
            "by what they are -- never a filename or /home/user path). voice=%s. "
            "At most %d characters."
            % (why, spec.get("instruction"), ctx,
               spec.get("ambiguity"), spec.get("voice"), cap))
    try:
        res, _, _ = call_and_extract(
            [{"role": "user", "content": user}],
            [{"type": "text", "text": "You repair task instructions. "
                                      "Answer only through the tool."}],
            cfg, tries=2, tool=REPAIR_TOOL, field=None)
        return (res.get("instruction") or "").strip() or None
    except RuntimeError:
        return None


def gate(spec):
    amb = spec.get("ambiguity") or 1
    _instr = spec.get("instruction") or ""
    if amb >= 2 and "/home/user" in _instr:
        return "absolute path in an ambiguity>=2 instruction"
    if amb >= 2 and spec.get("grade") != "browser" and re.search(
            r"\b[\w-]+\.(xlsx|ods|odt|odp|docx|pptx|csv|txt|pdf|py|md|json|html|htm|png|jpg|mp4)\b",
            _instr):
        return "filename in an ambiguity>=2 instruction"
    if amb == 3 and spec.get("grade") != "browser" and not (spec.get("open_path") or "").strip():
        return "ambiguity=3 without open_path"
    prim0 = (spec.get("apps") or [""])[0]
    if spec.get("grade") != "browser":
        if spec.get("warm") and prim0 not in ("files", "terminal", "thunderbird") \
                and not (spec.get("open_path") or "").strip():
            return "warm task without open_path"
        if not spec.get("warm") and (spec.get("open_path") or "").strip():
            return "cold task with open_path"
        if not spec.get("warm") and re.search(r"\b(is|are) (already )?open\b", _instr):
            return "cold task whose instruction presumes an open workspace"
    if spec.get("voice") in ("terse", "sloppy") and len(_instr.split()) > 40:
        return "terse/sloppy instruction over 40 words"
    _cap = {1: 150, 2: 150, 3: 250}.get(spec.get("difficulty") or 3, 300)
    if len(_instr) > _cap:
        return "instruction over %d chars for d%s" % (_cap, spec.get("difficulty"))
    """Why this spec cannot become a task, or None. Strict on purpose: a bad
    field that slips through either crashes evaluate() (no result.txt) or
    ships a task that can never score."""
    grade = spec.get("grade") or "probe"

    if grade == "browser":
        u = spec.get("start_url") or ""
        if not u.startswith(("http://", "https://")):
            return "bad start_url %r" % u
        pats = spec.get("url_patterns") or []
        if not pats:
            return "no url_patterns"
        for p in pats:
            try:
                re.compile(p)
            except re.error as e:
                return "bad url regex %r: %s" % (p, e)
        if not (spec.get("url_stability") or "").strip():
            return "no url_stability"
        return None

    if not (spec.get("setup") or "").strip():
        return "no setup"
    if re.search(r"--convert-to'?\s*,?\s*'?(odp|pptx|ppt)\b(?!:)(?!')?", spec["setup"]) and \
       not re.search(r"--convert-to'?\s*,?\s*'?(odp|pptx|ppt):", spec["setup"]):
        # BARE `--convert-to odp` fails everywhere: txt loads into Writer,
        # which has no presentation export (v11 control caught 7). The
        # filter-qualified form `odp:impress8` DOES work (2 control-passed
        # tasks prove it) and is allowed; prebuilt binaries remain preferred.
        return "setup converts to a presentation format without an explicit filter (bare odp fails; use odp:impress8 or a prebuilt binary)"
    why = _setup_compiles(spec["setup"])
    if why:
        return why

    if grade == "table":
        t = spec.get("table_target") or ""
        if not (t.startswith("/home/user/") and t.endswith(".xlsx")):
            return "bad table_target %r" % t
        rules = spec.get("table_rules") or []
        if not rules:
            return "no table_rules"
        for r in rules:
            if not isinstance(r, dict):
                return "table rule not an object"
            # check_cell only: it is the one rule type that guards its own
            # errors (returns 0.0); sheet_name/sheet_data need a golden
            # workbook and raise without one.
            if r.get("type") != "check_cell":
                return "table rule type %r not allowed" % r.get("type")
            if not re.fullmatch(r"[A-Z]+[1-9][0-9]*", str(r.get("coordinate", ""))):
                return "bad coordinate %r" % r.get("coordinate")
            if "sheet_idx" not in r:
                return "check_cell without sheet_idx"
            props = r.get("props")
            if not isinstance(props, dict) or not props:
                return "check_cell without props"
            for rule in props.values():
                if not (isinstance(rule, dict) and "method" in rule and "ref" in rule):
                    return "prop rule needs method and ref"
        return None

    probe = (spec.get("probe") or "").strip()
    if not probe:
        return "no probe"
    try:
        compile(wrap_probe(spec["probe"]), spec.get("slug", "?"), "exec")
    except SyntaxError as e:
        return "probe SyntaxError: %s" % e
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5, help="specs per batch")
    ap.add_argument("--batches", type=int, default=1)
    ap.add_argument("--out", type=Path, default=Path("out/runs/v8/specs.jsonl"))
    ap.add_argument("--batch", default=None,
                    help="batch name for task ids; default: the --out directory name")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--model", default=None)
    ap.add_argument("--env", default=".env")
    ap.add_argument("--max-tokens", type=int, default=48000)
    ap.add_argument("--apps", default=None, help="comma-separated primary-app filter")
    ap.add_argument("--thinking", action="store_true")
    ap.add_argument("--stream", action="store_true",
                    help="stream the response; the gateway 504s any request "
                         "that sends nothing for minutes, which is every batch")
    ap.add_argument("--shard", default=None, metavar="I/N",
                    help="take only cells I, I+N, I+2N ... of the taxonomy "
                         "product, so N processes can generate at once over "
                         "disjoint coordinates; cross-process duplication is "
                         "held down by the sibling-run avoid list, re-read "
                         "before every batch")
    ap.add_argument("--spent-from", action="append", default=[],
                    help="specs.jsonl file(s) whose kept coordinates seed the "
                         "quota ledger, so a top-up run corrects axis deficits")
    ap.add_argument("--start-batch", type=int, default=0,
                    help="resume: skip the first N batches (seeds stay aligned)")
    ap.add_argument("--refill", type=int, default=2,
                    help="extra batches drawn from fresh cells when a batch is "
                         "lost (no tool call after retries) or its specs are "
                         "rejected, until n*batches specs are kept")
    ap.add_argument("--priors", default=None,
                    help="glob of earlier specs.jsonl feeding the avoid list; "
                         "default: sibling runs next to --out; 'none' to disable")
    ap.add_argument("--avoid-corpus", action="append", default=[], metavar="PATH",
                    help="tasks.jsonl of PUBLIC instructions (app_type + "
                         "instruction) the model must not reinvent; repeatable")
    ap.add_argument("--avoid-per-app", type=int, default=12)
    ap.add_argument("--avoid-own-per-app", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    shard = None
    if args.shard:
        try:
            i, n_ = (int(x) for x in args.shard.split("/"))
        except ValueError:
            print("--shard wants I/N, e.g. 0/2", file=sys.stderr)
            return 1
        if not 0 <= i < n_:
            print("--shard index must be in [0, N)", file=sys.stderr)
            return 1
        shard = (i, n_)

    load_env(args.env)
    cfg = {
        "base": os.environ.get("PPAPI_BASE_URL", "https://app-us.ppapi.ai").rstrip("/"),
        "key": os.environ.get("PPAPI_API_KEY", ""),
        "model": args.model or os.environ.get("PPAPI_MODEL", "claude-opus-4-6"),
        "max_tokens": args.max_tokens,
        "thinking": args.thinking,
        "stream": args.stream,
    }
    only = [a.strip() for a in args.apps.split(",")] if args.apps else None
    batch_name = args.batch or args.out.parent.name
    args.out.parent.mkdir(parents=True, exist_ok=True)

    if args.priors is None:
        prior_files = sorted(args.out.parent.parent.glob("*/" + args.out.name))
    elif args.priors.strip().lower() == "none":
        prior_files = []
    else:
        prior_files = sorted(Path().glob(args.priors))
    prior_files = [f for f in prior_files if f.resolve() != args.out.resolve()]

    def priors_now():
        return read_own(prior_files + ([args.out] if args.out.is_file() else []))

    seen, own_by_app = priors_now()
    if seen:
        print("avoid list: %d slug(s), %d app(s) with instructions"
              % (len(seen), len(own_by_app)))

    external = collections.defaultdict(list)
    for path in args.avoid_corpus:
        p = Path(path)
        if not p.is_file():
            print("--avoid-corpus not found: %s" % path, file=sys.stderr)
            return 1
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            app = (r.get("app_type") or r.get("primary") or "").strip()
            instr = (r.get("instruction") or "").strip()
            if app and instr:
                external[app].append(instr)
    if external:
        print("external avoid corpus: %d instruction(s) over %d app(s)"
              % (sum(len(v) for v in external.values()), len(external)))

    if args.dry_run:
        c = T.cells(args.n, args.seed, only, shard=shard)
        sp = system_prompt()
        print("SYSTEM (%d chars, ~%d tok)\n%s\n" % (len(sp), len(sp) // 4, "=" * 60))
        print(sp)
        print("=" * 60, "\nUSER\n",
              user_prompt(args.n, c, external, own_by_app,
                          args.avoid_per_app, args.avoid_own_per_app), sep="")
        return 0

    if not cfg["key"]:
        print("PPAPI_API_KEY is empty; put it in %s" % args.env, file=sys.stderr)
        return 1

    tasks_dir = args.out.parent / "examples"
    manifest = collections.defaultdict(list)
    for f in sorted(tasks_dir.glob("*/*.json")):
        manifest[f.parent.name].append(f.stem)

    kept = 0
    spent = set()
    for pf in args.spent_from:
        for line in Path(pf).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                spent.add((r.get("intent"), r.get("domain"),
                           r.get("difficulty"), r.get("ambiguity")))
    target = args.n * args.batches
    b = args.start_batch
    with args.out.open("a", encoding="utf-8") as fh:
        # A lost batch (thinking means tool_choice auto, so no tool call is
        # possible even after retries) or a rejected spec leaves the run short;
        # refill batches draw FRESH cells until the quota is met or the extras
        # run out.
        while b < args.batches or (kept < target and b < args.batches + args.refill):
            c = T.cells(args.n, args.seed + b * 1000, only, spent, shard=shard)
            label = " (refill)" if b >= args.batches else ""
            b += 1
            if not c:
                break
            seen, own_by_app = priors_now()  # sibling runs may be writing
            print("\nbatch %d/%d%s" % (b, args.batches, label))
            for x in c:
                print("  %-14s %-18s d=%d  %-18s %-19s %s"
                      % (x["intent"], x["domain"], x["difficulty"],
                         x["artifact"], x["primary"], x.get("grade", "probe")))
            system_blocks = [{"type": "text", "text": system_prompt(),
                              # 1h: a batch takes longer than the 5m default TTL.
                              "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
            msgs = [{"role": "user",
                     "content": user_prompt(args.n, c, external, own_by_app,
                                            args.avoid_per_app,
                                            args.avoid_own_per_app)}]
            try:
                specs, resp, thought = call_and_extract(msgs, system_blocks, cfg)
            except RuntimeError as e:
                print("  failed: %s" % e)
                continue
            u = resp.get("usage", {})
            print("  in=%s out=%s cache_read=%s thinking_blocks=%d"
                  % (u.get("input_tokens"), u.get("output_tokens"),
                     u.get("cache_read_input_tokens"), thought))
            kept_before = kept
            for i, s in enumerate(specs):
                if not isinstance(s, dict):
                    print("  skip non-object spec entry %r" % str(s)[:60])
                    continue
                slug = s.get("slug") or ""
                if not slug or slug in seen:
                    print("  skip duplicate/blank slug %r" % slug)
                    continue
                # The cell dictates the grade; stamp before gate so the gate
                # judges the spec against the contract it was asked for.
                if i < len(c):
                    for k in ("drawn_from", "intent", "domain", "difficulty",
                              "constraints", "artifact", "source", "app_count",
                              "grade", "ambiguity", "voice", "warm"):
                        s[k] = c[i][k]
                why = gate(s)
                if why and why.startswith(_REPAIRABLE):
                    fixed = repair_instruction(s, why, cfg)
                    if fixed:
                        s["instruction"] = fixed
                        why2 = gate(s)
                        if not why2:
                            print("  repaired %-30s (%s)" % (slug, why[:40]))
                        why = why2
                if why:
                    print("  skip %-34s %s" % (slug, why))
                    continue
                seen.add(slug)
                # Quota accounting happens on KEEP: a gate-rejected spec must
                # return its cell to the pool, or the high-difficulty quotas
                # bleed out through rejections (measured: d4+d5 at 21% of a
                # 35% target).
                spent.add((s["intent"], s["domain"], s["difficulty"], s["ambiguity"]))
                fh.write(json.dumps(s, ensure_ascii=False) + "\n")
                fh.flush()
                domain, tj = task_json(s, batch_name)
                d = tasks_dir / domain
                d.mkdir(parents=True, exist_ok=True)
                (d / ("%s.json" % tj["id"])).write_text(
                    json.dumps(tj, ensure_ascii=False, indent=1), encoding="utf-8")
                manifest[domain].append(tj["id"])
                kept += 1
            (args.out.parent / "manifest.json").write_text(
                json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
            print("  %d emitted, %d kept (%d so far)"
                  % (len(specs), kept - kept_before, kept))

    rows = [json.loads(x) for x in args.out.read_text().splitlines() if x.strip()] \
        if args.out.is_file() else []
    print("\n%d spec(s) in %s, %d task json under %s"
          % (len(rows), args.out, sum(len(v) for v in manifest.values()), tasks_dir))
    for ax in ("intent", "domain", "difficulty", "artifact"):
        d = collections.Counter(r.get(ax) for r in rows)
        print("  %-11s %s" % (ax, "  ".join("%s=%d" % kv for kv in d.most_common())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
