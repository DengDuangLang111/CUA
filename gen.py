"""Generate task specs with Claude.

    python -m ostg.gen --n 6 --out out/specs.jsonl

Axis targets are drawn at random from the labelled official suite
(taskgen/data/osworld361_labels.json), so the generated batch samples the same
category space OSWorld-Verified actually occupies. Nothing is validated here;
specs are appended as-is and judged by emit.py's controls and by the rollouts.
"""
import argparse
import collections
import json
import os
import random
import sys
import urllib.error
import urllib.request
from pathlib import Path

from ostg import prompt as P
from ostg import taxonomy as TAX

HERE = Path(__file__).resolve().parent
LABELS = HERE / "data" / "osworld361_labels.json"
TOOL = "emit_task_specs"

# Axes worth STRATIFYING on -- i.e. the ones a coverage report can be trusted to
# mean something. The 40-task blind relabel put artifact at 10% disagreement and
# source at 14% (excluding refusals); `operation` came in at 27.5% because
# derive/rewrite/set_value are semantically nested.
AXES = ("artifact", "source")

# Axes worth STEERING on. Not the same list, and the 27.5% is why: that number
# says two annotators disagree about what to CALL a finished task, which
# disqualifies operation as a measurement. It says nothing about whether
# "operation=remove_element" and "operation=set_value" make the model write
# different tasks -- and they plainly do. Measurement needs reliability,
# steering does not.
#
# Adding operation to the brief takes the reachable cell count over the 260
# generatable official tasks from 37 (artifact x source) to 80. Batch-level
# de-duplication deliberately stays at (artifact, source), so the anti-collapse
# guarantee below is unchanged and the extra coverage accrues across batches.
STEER = ("artifact", "source", "operation")


# Blockers we now have a shape for. The label file marks these tasks
# generatable=False, and that was correct while a spec could only ever be "probe
# reads a file solve_py wrote". Each entry says what a spec drawn from such a
# cell has to become instead. subjective_judgement stays out on purpose: 1 task,
# and no deterministic answer exists for it at any gold_kind.
BLOCKER_STRATEGY = {
    "refusal_not_observable": {"gold_kind": "infeasible"},
    # gold_kind is decided per task below, not here: over the 56 official
    # live_web tasks the judging target follows the ARTIFACT, not the blocker.
    # browser_tab is graded on the browser 29 times out of 29; text_document
    # (8/8), source_code (3/3) and spreadsheet (6/7) are graded on a file, with
    # the web page acting only as the source of the data.
    "needs_live_web": {"source": "live_web"},
    "needs_network_install": {"gold_kind": "file", "setup_shell": True},
    # needs_gui_only_state (8 tasks) is deliberately absent. Official grades those
    # with check_accessibility_tree, whose rules are CSS selectors or xpath over
    # the GNOME accessibility XML of a desktop the generator never sees. There is
    # no honest way to have a model guess those, and inventing a probe to replace
    # them would be reimplementing a getter OSWorld already ships.
}


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


# Which application owns a domain's tasks. multi_apps is deliberately absent: it
# names an app COUNT, not an app, so it cannot tell us a primary.
DOMAIN_APP = {
    "chrome": "chrome",
    "gimp": "gimp",
    "libreoffice_calc": "libreoffice_calc",
    "libreoffice_impress": "libreoffice_impress",
    "libreoffice_writer": "libreoffice_writer",
    "os": "files",
    "thunderbird": "thunderbird",
    "vlc": "vlc",
    "vs_code": "vscode",
}


def cells(n, seed, only_apps=None, blockers=None):
    """Draw n axis targets by sampling real official tasks.

    The primary application is derived from the artifact using the artifact's
    OBSERVED domain spread in the official suite, not from an independent
    rotation -- rotating apps separately produced incoherent targets such as
    artifact=raster_image with primary=libreoffice_calc.

    `blockers` selects which BLOCKER_STRATEGY classes to admit alongside the
    plainly generatable tasks; None means all of them.
    """
    admit = set(BLOCKER_STRATEGY) if blockers is None else set(blockers)
    tasks = json.loads(LABELS.read_text())["tasks"]
    pool = [t for t in tasks
            if t.get("generatable") or t.get("blocker") in admit]
    if not pool:
        raise SystemExit("no generatable tasks in the label file")

    hosts = collections.defaultdict(list)
    for t in pool:
        app = DOMAIN_APP.get(t["domain"])
        if app and (not only_apps or app in only_apps):
            hosts[t["artifact"]].append(app)

    rng = random.Random(seed)
    seen = collections.Counter()
    used_cells = set()
    out = []
    for _ in range(n):
        # No repeated (artifact, source) cell within a batch. The first real batch
        # drew spreadsheet/self three times out of eight and all three came back as
        # "add a derived column and save" -- the same mode collapse that took the
        # previous generation to 0.987 instruction similarity. Sampling the cell
        # without replacement inside a batch costs nothing and prevents it.
        for _try in range(400):
            t = rng.choice(pool)
            # De-duplicate on the source the MODEL will see, not the one in the
            # label. A blocker strategy can rewrite it -- every needs_live_web
            # task is presented as source=live_web whatever its label said -- so
            # keying on the raw value let two tasks with different labels arrive
            # as the same brief, which is exactly what this loop exists to stop.
            strat = BLOCKER_STRATEGY.get(t.get("blocker")) or {}
            eff_src = strat.get("source") or t["source"]
            cell = (t["artifact"], eff_src)
            if hosts.get(t["artifact"]) and cell not in used_cells:
                used_cells.add(cell)
                break
        else:
            continue
        # Spread across the apps that really carry this artifact, most common first.
        opts = [a for a, _ in collections.Counter(hosts[t["artifact"]]).most_common()]
        app = opts[seen[t["artifact"]] % len(opts)]
        seen[t["artifact"]] += 1
        src = eff_src
        gold_kind = strat.get("gold_kind", "file")
        if t.get("blocker") == "needs_live_web":
            gold_kind = "browser_state" if t["artifact"] == "browser_tab" else "file"
        out.append({
            "artifact": t["artifact"],
            "source": src if src in P.SOURCES else "self",
            # Steering only. The label may be arguable (27.5% blind-relabel
            # disagreement) but it still splits one brief into several.
            "operation": t.get("operation") or "",
            "app_count": min(max(int(t.get("app_count") or 1), 1), 3),
            "primary": app,
            # What the blocker forces this spec to be. "file" for everything that
            # was already generatable, so the default path is unchanged.
            "gold_kind": gold_kind,
            "needs_setup_shell": bool(strat.get("setup_shell")),
            "blocker": t.get("blocker") or "",
            "drawn_from": t["id"],
        })
    return out


def call(messages, system_blocks, cfg, timeout=900):
    payload = {
        "model": cfg["model"],
        "max_tokens": cfg["max_tokens"],
        "system": system_blocks,
        "messages": messages,
        "tools": [P.tool_definition(TOOL)],
        "tool_choice": {"type": "tool", "name": TOOL},
    }
    # Extended thinking and a FORCED tool choice are mutually exclusive: naming the
    # tool is itself the decision, so the model has nothing left to think about and
    # the API rejects the pair. Asking for thinking therefore means dropping to
    # tool_choice auto, which turns the structured output from a guarantee into a
    # probability -- hence the retry in generate(), which is the price of thinking,
    # not an optimisation.
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
        # Transient by status, so the caller knows whether a retry is pointless.
        # 429 and 5xx say the gateway or the model was momentarily unavailable;
        # 4xx otherwise says the request itself is wrong and will stay wrong.
        err = RuntimeError("HTTP %d: %s" % (e.code, body))
        err.transient = e.code == 429 or 500 <= e.code < 600
        raise err from None


def extract(resp):
    for b in resp.get("content", []):
        if b.get("type") == "tool_use" and b.get("name") == TOOL:
            return b.get("input", {}).get("specs", [])
    raise RuntimeError("no tool_use block (stop_reason=%s)" % resp.get("stop_reason"))


def call_and_extract(messages, system_blocks, cfg, tries=3):
    """One batch, retried only for a MISSING TOOL CALL.

    Two failures are worth retrying and they are not the same failure.

    Under tool_choice auto the model can answer in prose instead of calling the
    tool, which loses the batch. Retrying is safe because a batch is
    self-contained -- nothing has been written yet -- and the failure was the
    model's choice, so the same prompt can succeed.

    A 429 or a 5xx is the other one. This originally propagated, on the reasoning
    that retrying an HTTP error spends tokens on the same failure -- true of a
    400, false of a gateway timeout, which is exactly what cost one shard a whole
    batch. A deterministic 4xx still propagates; there is nothing to wait for.
    """
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6, help="specs per batch")
    ap.add_argument("--batches", type=int, default=1)
    ap.add_argument("--out", type=Path, default=Path("out/specs.jsonl"))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--model", default=None)
    ap.add_argument("--env", default=".env")
    ap.add_argument("--max-tokens", type=int, default=32000)
    ap.add_argument("--apps", default=None, help="comma-separated primary-app rotation")
    ap.add_argument("--blockers", default=None,
                    help="comma-separated blocker classes to admit beyond the plainly "
                         "generatable tasks; 'none' for none. Default: all of "
                         + ",".join(BLOCKER_STRATEGY))
    ap.add_argument("--priors", default=None,
                    help="glob of earlier specs.jsonl files whose slugs feed the "
                         "per-cell avoid list. Default: */specs.jsonl next to --out, "
                         "so a run stays its own task set but still knows what every "
                         "earlier run already wrote. 'none' to disable.")
    ap.add_argument("--avoid-corpus", action="append", default=[], metavar="PATH",
                    help="a tasks.jsonl of instructions that ALREADY EXIST publicly "
                         "(e.g. CUA-Gym). Per-app samples are shown to the model as "
                         "things not to write. Repeat for several corpora")
    ap.add_argument("--avoid-per-app", type=int, default=12,
                    help="how many existing PUBLIC instructions per app to show")
    ap.add_argument("--avoid-own-per-app", type=int, default=8,
                    help="how many of OUR OWN earlier instructions per app to show. "
                         "Keyed by application rather than by (artifact, source) "
                         "cell, because an app with a small operation space -- VLC, "
                         "GIMP -- produces the same task twice from two different "
                         "cells and the per-cell list never sees it")
    ap.add_argument("--taxonomy", action="store_true",
                    help="draw briefs from the enumerated intent x domain x "
                         "constraints product (ostg/taxonomy.py) instead of "
                         "sampling axis targets out of the official suite")
    ap.add_argument("--thinking", action="store_true",
                    help="extended thinking. Forces tool_choice to auto, since a "
                         "named tool and thinking cannot be combined, so the tool "
                         "call becomes probable rather than guaranteed and batches "
                         "are retried when it is missing")
    ap.add_argument("--cells-from", default=None, metavar="FILE",
                    help="a JSON list of cell dicts to regenerate at EXACTLY those "
                         "coordinates, instead of drawing from the taxonomy. Used to "
                         "replace specs that were rejected downstream without moving "
                         "the run's axis distribution")
    ap.add_argument("--shard", default=None, metavar="I/N",
                    help="take only cells I, I+N, I+2N ... of the taxonomy "
                         "product, so N processes can run at once over disjoint "
                         "cells. Batches inside one process stay sequential")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    shard = None
    if args.shard:
        try:
            i, n_ = (int(x) for x in args.shard.split("/"))
        except ValueError:
            print("--shard wants I/N, e.g. 0/4", file=sys.stderr)
            return 1
        if not 0 <= i < n_:
            print("--shard index must be in [0, N)", file=sys.stderr)
            return 1
        shard = (i, n_)

    # Cells to regenerate verbatim, when replacing specs rejected downstream.
    fixed_cells = None
    if args.cells_from:
        fixed_cells = json.loads(Path(args.cells_from).read_text(encoding="utf-8"))
        print("regenerating %d fixed cell(s) from %s" % (len(fixed_cells), args.cells_from))

    load_env(args.env)
    cfg = {
        "base": os.environ.get("PPAPI_BASE_URL", "https://app-us.ppapi.ai").rstrip("/"),
        "key": os.environ.get("PPAPI_API_KEY", ""),
        "model": args.model or os.environ.get("PPAPI_MODEL", "claude-opus-4-6"),
        "max_tokens": args.max_tokens,
        "thinking": args.thinking,
    }
    only = [a.strip() for a in args.apps.split(",")] if args.apps else None
    if args.blockers is None:
        blockers = None
    elif args.blockers.strip().lower() == "none":
        blockers = []
    else:
        blockers = [b.strip() for b in args.blockers.split(",")]
        unknown = sorted(set(blockers) - set(BLOCKER_STRATEGY))
        if unknown:
            print("unknown blocker class(es): %s; known: %s"
                  % (", ".join(unknown), ", ".join(BLOCKER_STRATEGY)), file=sys.stderr)
            return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)

    # Each run owns its own specs.jsonl, so nothing from an older prompt or an
    # older framework can end up in this run's task set. The avoid list is the one
    # thing that must NOT be per-run: it exists to stop the same cell producing the
    # same business scenario over and over, and that only works if it remembers
    # across runs. So slugs are read from every run, results are written to one.
    prior_files = []
    if args.priors is None:
        prior_files = sorted(args.out.parent.parent.glob("*/" + args.out.name))
    elif args.priors.strip().lower() != "none":
        prior_files = sorted(Path().glob(args.priors))
    prior_files = [f for f in prior_files if f.resolve() != args.out.resolve()]

    def read_priors():
        """(seen, per-cell slugs, per-app instructions), re-read from disk.

        Called before EVERY batch, not once at startup. Four sharded processes
        write to four sibling specs.jsonl files, and reading them once meant each
        process only ever knew what IT had written. The measured cost was two
        near-duplicate pairs across shards -- a VLC loop task written twice, once
        for an estate agency and once for a clinic, and the same VS Code settings
        repair written twice. Disjoint taxonomy cells stop two processes drawing
        the same coordinates; nothing stopped them writing the same task.

        The per-app list is the second fix and a different one. The per-cell list
        is keyed on (artifact, source), which is too fine: those two VLC tasks sat
        in different cells and were still the same task, because VLC has only a
        handful of settings worth writing a task about. Grouping by APPLICATION is
        the granularity at which a small operation space actually bites, and full
        instructions are sent rather than slugs -- a slug does not say what the
        task was, and the whole point is for the model to recognise it.
        """
        seen, cells_, apps_ = set(), collections.defaultdict(list), collections.defaultdict(list)
        for f in prior_files + ([args.out] if args.out.is_file() else []):
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
                    continue      # a sibling mid-write; the next batch will see it
                if not r.get("slug"):
                    continue
                seen.add(r["slug"])
                cells_[(r.get("artifact"), r.get("source"))].append(r["slug"])
                app = (r.get("apps") or [None])[0] or r.get("primary")
                if app and r.get("instruction"):
                    apps_[app].append(r["instruction"])
        return seen, cells_, apps_

    seen, priors, own_by_app = read_priors()
    if seen:
        print("avoid list: %d slug(s) from %d earlier run(s), over %d cell(s), %d app(s)"
              % (len(seen), len(prior_files), len(priors), len(own_by_app)))

    # Instructions from suites that already exist publicly. The per-cell and
    # per-app lists above only know what WE wrote; this is what stops the model
    # reinventing one of CUA-Gym's 9,835 desktop tasks, and it acts before the
    # tokens are spent rather than after.
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
        c = (TAX.cells(args.n, args.seed, DOMAIN_APP, only, shard=shard)
             if args.taxonomy else cells(args.n, args.seed, only, blockers))
        sp = P.system_prompt()
        print("SYSTEM (%d chars, ~%d tok)\n%s\n" % (len(sp), len(sp) // 4, "=" * 60))
        print(sp)
        print("=" * 60, "\nUSER\n",
              P.user_prompt(args.n, c, priors, external, args.avoid_per_app,
                            args.seed, own_by_app, args.avoid_own_per_app), sep="")
        return 0

    if not cfg["key"]:
        print("PPAPI_API_KEY is empty; put it in %s" % args.env, file=sys.stderr)
        return 1

    kept = 0
    # Taxonomy cells already spent this run, so later batches walk the 260-cell
    # product instead of re-drawing its most probable corners.
    spent = set()
    with args.out.open("a", encoding="utf-8") as fh:
        for b in range(args.batches):
            if fixed_cells is not None:
                c = fixed_cells[b * args.n:(b + 1) * args.n]
                if not c:
                    break
            else:
                c = (TAX.cells(args.n, args.seed + b * 1000, DOMAIN_APP, only, spent,
                           shard=shard)
                 if args.taxonomy
                 else cells(args.n, args.seed + b * 1000, only, blockers))
            if args.taxonomy:
                spent.update((x["intent"], x["domain"], x["constraints"]) for x in c)
            # Re-read before every batch so the other shards' work is visible.
            seen, priors, own_by_app = read_priors()
            print("\nbatch %d/%d" % (b + 1, args.batches))
            for x in c:
                if x.get("intent"):
                    print("  %-14s %-18s c=%d  %-18s %-20s avoid=%d"
                          % (x["intent"], x["domain"], x["constraints"],
                             x["artifact"], x["primary"],
                             len(priors.get((x["artifact"], x["source"]), []))))
                    continue
                print("  %-16s %-20s %-14s %-10s apps=%d %-19s avoid=%d %s"
                      % (x["source"], x["artifact"], x["operation"] or "-",
                         x.get("gold_kind", "file"), x["app_count"], x["primary"],
                         len(priors.get((x["artifact"], x["source"]), [])),
                         (x.get("blocker") or "")[:22]))
            system_blocks = [{"type": "text", "text": P.system_prompt(),
                              "cache_control": {"type": "ephemeral"}}]
            msgs = [{"role": "user",
                     "content": P.user_prompt(args.n, c, priors, external,
                                              args.avoid_per_app, args.seed + b,
                                              own_by_app, args.avoid_own_per_app)}]
            try:
                specs, resp, thought = call_and_extract(msgs, system_blocks, cfg)
            except RuntimeError as e:
                print("  failed: %s" % e)
                continue
            kept_before = kept
            u = resp.get("usage", {})
            print("  in=%s out=%s cache_read=%s thinking_blocks=%d"
                  % (u.get("input_tokens"), u.get("output_tokens"),
                     u.get("cache_read_input_tokens"), thought))
            for i, s in enumerate(specs):
                slug = s.get("slug") or ""
                if not slug or slug in seen:
                    print("  skip duplicate/blank slug %r" % slug)
                    continue
                seen.add(slug)
                if i < len(c):
                    s["drawn_from"] = c[i]["drawn_from"]
                    # The model never emits `operation`; it is stamped from the
                    # brief so a later batch can report on what was steered for.
                    s["operation"] = c[i]["operation"]
                    for k in ("intent", "domain", "constraints"):
                        if k in c[i]:
                            s[k] = c[i][k]
                    # gold_kind is dictated by the cell, never by the model: a
                    # blocked cell is drawn precisely because it needs that shape,
                    # and letting the model downgrade it back to "file" would put
                    # the task straight back into the class that cannot be built.
                    s["gold_kind"] = c[i]["gold_kind"]
                    if c[i].get("blocker"):
                        s["blocker"] = c[i]["blocker"]
                # A file-graded task with no probe is unscoreable: emit wires the
                # empty program into a file-reading evaluator, the metric receives
                # an empty string, and the task scores 0 forever while both
                # build-time controls report n/a rather than failing. That is how
                # a mislabelled browser_tab cell put 5 dead tasks into the first
                # 21 of a run without anything complaining. Cheap to assert, and
                # the failure it catches is invisible downstream.
                if s.get("gold_kind") == "file" and not (s.get("probe_py") or "").strip():
                    print("  drop %r: gold_kind=file with empty probe_py" % slug)
                    seen.discard(slug)
                    continue
                # Grow the avoid-list inside the run too, so batch 2 of a
                # --batches 3 call already knows what batch 1 just wrote.
                priors[(s.get("artifact"), s.get("source"))].append(slug)
                fh.write(json.dumps(s, ensure_ascii=False) + "\n")
                kept += 1
            # kept is a running total across batches; this line is about THIS one.
            print("  %d emitted, %d kept (%d so far)"
                  % (len(specs), kept - kept_before, kept))

    n_here = sum(1 for x in args.out.read_text().splitlines() if x.strip()) \
        if args.out.is_file() else 0
    print("\n%d spec(s) in %s (%d slug(s) known across all runs)"
          % (n_here, args.out, len(seen)))
    if seen:
        rows = [json.loads(x) for x in args.out.read_text().splitlines() if x.strip()]
        for ax in AXES + ("app_count",):
            d = collections.Counter(r.get(ax) for r in rows)
            print("  %-11s %s" % (ax, "  ".join("%s=%d" % kv for kv in d.most_common())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
