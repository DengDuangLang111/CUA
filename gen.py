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
                "required": ["slug", "instruction", "apps", "setup", "probe"],
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
            "source=%s, primary=%s"
            % (i + 1, c["intent"], c["domain"], c["difficulty"], c["app_count"],
               c["artifact"], c["source"], c["primary"]))

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
           + "\n".join("  %d = %s" % (c, T.DIFFICULTY[c][0]) for c in cons))

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


def call(messages, system_blocks, cfg, timeout=900):
    payload = {
        "model": cfg["model"],
        "max_tokens": cfg["max_tokens"],
        "system": system_blocks,
        "messages": messages,
        "tools": [tool_definition()],
        "tool_choice": {"type": "tool", "name": TOOL},
    }
    # Thinking and a forced tool choice are mutually exclusive; auto makes the
    # tool call probable rather than guaranteed, hence the retry in the caller.
    if cfg.get("thinking"):
        payload["thinking"] = {"type": "adaptive"}
        payload["tool_choice"] = {"type": "auto"}
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


def extract(resp):
    for b in resp.get("content", []):
        if b.get("type") == "tool_use" and b.get("name") == TOOL:
            return b.get("input", {}).get("specs", [])
    raise RuntimeError("no tool_use block (stop_reason=%s)" % resp.get("stop_reason"))


def call_and_extract(messages, system_blocks, cfg, tries=3):
    for attempt in range(1, tries + 1):
        try:
            resp = call(messages, system_blocks, cfg)
        except RuntimeError as e:
            if attempt == tries or not getattr(e, "transient", False):
                raise
            print("  retry %d/%d after %s" % (attempt, tries - 1, str(e)[:60]))
            continue
        thought = sum(1 for b in resp.get("content", []) if b.get("type") == "thinking")
        try:
            specs = extract(resp)
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


def task_json(spec, batch):
    apps = spec.get("apps") or ["files"]
    domain = APPS.get(apps[0], "os")
    return domain, {
        "id": str(uuid.uuid5(NS, "%s/%s" % (batch, spec["slug"]))),
        "snapshot": domain,
        "instruction": spec["instruction"],
        "source": "generated: ostg/%s#%s" % (batch, spec["slug"]),
        # shell=True: the setup is one command line with quoting in it, run by
        # /bin/sh. No `until`: a non-zero exit would retry forever (OSWorld
        # counts only HTTP failures toward the cap).
        "config": [{"type": "execute",
                    "parameters": {"command": spec["setup"], "shell": True}}]
                  + ([{"type": "open", "parameters": {"path": spec["open_path"]}}]
                     if spec.get("open_path") else []),
        "related_apps": apps,
        # `rules`, plural: the getter reads config["rules"]. check_include_exclude
        # rather than exact_match because stdout arrives raw, "PASS\n".
        "evaluator": {
            "func": "check_include_exclude",
            "result": {"type": "vm_command_line",
                       "command": ["python3", "-c", wrap_probe(spec.get("probe"))]},
            "expected": {"type": "rule",
                         "rules": {"include": ["PASS"], "exclude": ["FAIL"]}},
        },
        "ostg": {"slug": spec["slug"], "batch": batch,
                 "intent": spec.get("intent"), "domain": spec.get("domain"),
                 "difficulty": spec.get("difficulty"),
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


def gate(spec):
    """Why this spec cannot become a task, or None."""
    if not (spec.get("setup") or "").strip():
        return "no setup"
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

    load_env(args.env)
    cfg = {
        "base": os.environ.get("PPAPI_BASE_URL", "https://app-us.ppapi.ai").rstrip("/"),
        "key": os.environ.get("PPAPI_API_KEY", ""),
        "model": args.model or os.environ.get("PPAPI_MODEL", "claude-opus-4-6"),
        "max_tokens": args.max_tokens,
        "thinking": args.thinking,
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
        c = T.cells(args.n, args.seed, only)
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
    with args.out.open("a", encoding="utf-8") as fh:
        for b in range(args.batches):
            c = T.cells(args.n, args.seed + b * 1000, only, spent)
            if not c:
                break
            spent.update((x["intent"], x["domain"], x["difficulty"]) for x in c)
            seen, own_by_app = priors_now()  # sibling runs may be writing
            print("\nbatch %d/%d" % (b + 1, args.batches))
            for x in c:
                print("  %-14s %-18s d=%d  %-18s %s"
                      % (x["intent"], x["domain"], x["difficulty"],
                         x["artifact"], x["primary"]))
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
                slug = s.get("slug") or ""
                if not slug or slug in seen:
                    print("  skip duplicate/blank slug %r" % slug)
                    continue
                why = gate(s)
                if why:
                    print("  skip %-34s %s" % (slug, why))
                    continue
                seen.add(slug)
                if i < len(c):
                    for k in ("drawn_from", "intent", "domain", "difficulty",
                              "constraints", "artifact", "source", "app_count"):
                        s[k] = c[i][k]
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
