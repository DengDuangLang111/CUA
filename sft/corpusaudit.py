"""Post-build corpus audit: prove a built corpus says what we think it says.

    python -m ostg.sft.corpusaudit --corpus OUT_DIR [--corpus OUT_DIR ...] \
        --results-root RESULTS_GENERATED [--baseline OUT_DIR ...] \
        [--harness /path/to/OSWorld] --json report.json [--text]

`verify` is the SHIP gate: it answers "is this corpus internally consistent"
(images resolve, no dir shared by two tasks, the terminal step survived the
cap, the ending parses as terminate). This module answers the question verify
cannot: "does the corpus still describe the trajectory that the checker
actually approved". That needs the RAW trajectories, so it is a separate,
heavier pass -- run it after build, before ship, whenever a build rewrites or
truncates anything.

It exists because the first version of these checks were one-off scripts, and
one of them silently resolved trajectories by task_id alone. The same task_id
exists under several models and runs
(RESULTS_ROOT/<model>/<run>/<domain>/<task_id>), so that script compared a
qwen3.6 trajectory against a qwen3.8 corpus and reported a defect five times
larger than the real one. Every lookup here is keyed on meta['run'] AND
confirmed against meta['orig_steps']; a trajectory that cannot be confirmed is
reported as unresolved, never silently scored.

Checks, each independently pass/fail:
  composition     trajectories / samples / images, per corpus and per domain
  ending_form     what the HARNESS would do with each final target
  infeasible      final targets that trip looks_infeasible_response (DONE->FAIL)
  images          every reference resolves; no image dir claimed by two tasks
  coverage        steps are 1..n_steps with no gap, no duplicate
  tail_safety     truncated tails: is the terminate screen the approved screen
  invariance      vs a baseline corpus: non-terminal targets byte-identical
  justification   rewritten endings: distinct, short, no canned flood
"""
import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

# The harness's own sentinels for "this step executed no GUI action". They are
# emitted by mm_agents/qwen/actions.py, not invented here; exposed as a flag so
# a future harness rename does not require editing this file.
DEFAULT_NOOP = "WAIT,DONE,FAIL"


def sha(path):
    try:
        b = Path(path).read_bytes()
    except OSError:
        return None
    return hashlib.md5(b).hexdigest() if b else None


def load_corpus(dirs):
    """-> {(domain, task_id): {step: sample}}, over one or more build dirs.

    Image paths inside samples.jsonl are relative to the build dir they came
    from (ship rewrites them to absolute later), so each sample carries the dir
    it was read from -- resolving them against the process cwd instead reports
    every image in the corpus as missing.
    """
    out = defaultdict(dict)
    for d in dirs:
        for name in ("samples.jsonl", "val_samples.jsonl"):
            p = Path(d) / name
            if not p.is_file():
                continue
            for line in p.open(encoding="utf-8"):
                if not line.strip():
                    continue
                s = json.loads(line)
                s["_dir"] = str(d)
                m = s.get("meta") or {}
                out[(m.get("domain"), m.get("task_id"))][m.get("step")] = s
    return out


def images_of(sample):
    for msg in sample.get("messages", []):
        c = msg.get("content")
        if isinstance(c, list):
            for part in c:
                if part.get("type") == "image" and part.get("path"):
                    yield part["path"]


class Harness:
    """The real parser when it is importable, a declared-degraded one if not."""

    def __init__(self, root):
        self.real = False
        if root:
            sys.path.insert(0, str(root))
        try:
            from mm_agents.qwen.parser import (iter_tool_call_params,
                                               looks_infeasible_response)
            self._iter = iter_tool_call_params
            self._infeasible = looks_infeasible_response
            self.real = True
        except Exception:                                    # noqa: BLE001
            self._iter = None
            self._infeasible = None

    def actions(self, response):
        if not self._iter:
            return None
        try:
            return [str(p.get("action")) for p in self._iter(response or "")
                    if p.get("action")]
        except Exception:                                    # noqa: BLE001
            return []

    def ending(self, response):
        a = self.actions(response)
        if a is None:
            return "unparsed(no harness)"
        if not a:
            return "prose->DONE"
        for want in ("terminate", "call_user"):
            if want in a:
                return want
        return "real-action"

    def infeasible(self, response):
        return bool(self._infeasible and self._infeasible(response or ""))


def resolve(results_root, run, domain, task_id, orig_steps, load_steps):
    """RESULTS_ROOT/<model>/<run>/<domain>/<task_id>, confirmed by step count.

    Returns (dir, steps, status). status is 'ok' only when the step count
    matches orig_steps -- the model level must never be wildcarded away
    silently, because the same task_id exists under several models.
    """
    root = Path(results_root)
    cands = []
    if root.is_dir():
        for model in sorted(root.iterdir()):
            if not model.is_dir():
                continue
            c = model / str(run) / domain / task_id
            if c.is_dir():
                cands.append(c)
    for c in cands:
        st = load_steps(c)
        if orig_steps is None or len(st) == orig_steps:
            return c, st, "ok"
    if cands:
        return cands[0], load_steps(cands[0]), "step-count-mismatch"
    return None, None, "not-found"


def audit(corpus_dirs, results_root, baseline_dirs, harness_root, noop_names,
          label, load_steps):
    H = Harness(harness_root)
    corpus = load_corpus(corpus_dirs)
    noop = tuple(x.strip() for x in noop_names.split(",") if x.strip())

    def is_noop(a):
        a = (a or "").strip()
        if a in noop:
            return True
        # `screenshot` is undeclared upstream: actions.py logs it and lets it
        # fall through to the WAIT fallback, so it executes nothing.
        return a.lower().startswith("screenshot") or a == ""

    rep = {"label": label, "corpus": [str(d) for d in corpus_dirs],
           "results_root": str(results_root),
           "harness_parser": "real" if H.real else "UNAVAILABLE",
           "checks": {}}

    # ---- composition -----------------------------------------------------
    n_samples = sum(len(v) for v in corpus.values())
    n_imgs = sum(1 for v in corpus.values() for s in v.values()
                 for _ in images_of(s))
    per_domain = Counter(d for d, _ in corpus)
    steps_per = sorted(len(v) for v in corpus.values())
    rep["checks"]["composition"] = {
        "ok": True,
        "trajectories": len(corpus), "samples": n_samples,
        "image_refs": n_imgs,
        "per_domain": dict(sorted(per_domain.items())),
        "steps_median": steps_per[len(steps_per) // 2] if steps_per else 0,
        "steps_mean": round(sum(steps_per) / len(steps_per), 2)
        if steps_per else 0,
        "steps_max": steps_per[-1] if steps_per else 0,
    }

    # ---- ending form + infeasible ----------------------------------------
    endings, infeasible_hits = Counter(), []
    for key, steps in corpus.items():
        last = steps[max(steps)]
        e = H.ending(last.get("response", ""))
        endings[e] += 1
        if H.infeasible(last.get("response", "")):
            infeasible_hits.append({"domain": key[0], "task_id": key[1]})
    rep["checks"]["ending_form"] = {
        "ok": H.real and set(endings) <= {"terminate"},
        "counts": dict(endings.most_common()),
        "note": "ok only when every trajectory ends in an explicit terminate",
    }
    rep["checks"]["infeasible"] = {
        "ok": not infeasible_hits,
        "hits": infeasible_hits,
        "note": "a final target tripping looks_infeasible_response flips the "
                "harness DONE into FAIL",
    }

    # ---- images ----------------------------------------------------------
    missing, empty = [], []
    dir_owner, shared = {}, []
    for key, steps in corpus.items():
        for s in steps.values():
            for p in images_of(s):
                full = p if os.path.isabs(p) else os.path.join(s["_dir"], p)
                if not os.path.exists(full):
                    missing.append(full)
                elif os.path.getsize(full) == 0:
                    empty.append(full)
                # Ownership must be keyed on the ABSOLUTE directory. Two pools
                # built into separate dirs can legitimately hold the same
                # relative path (images/<slug>/...) for two different tasks --
                # those files never overwrite each other, so keying on the
                # relative path invents collisions that do not exist.
                d = os.path.dirname(full)
                own = dir_owner.setdefault(d, key)
                if own != key:
                    shared.append({"dir": d, "a": list(own), "b": list(key)})
    rep["checks"]["images"] = {
        "ok": not (missing or empty or shared),
        "missing": len(missing), "empty": len(empty),
        "shared_dirs": shared[:20], "n_shared": len(shared),
        "examples_missing": missing[:5],
    }

    # ---- step coverage ---------------------------------------------------
    # Two different things, deliberately not conflated. A MISSING TERMINAL STEP
    # is a defect: the corpus never shows the model the moment of stopping.
    # An INTERIOR GAP is intended -- build's think-cap quarantines any step
    # whose reasoning exceeds the budget, and the terminal step is exempt. The
    # gap is still worth counting, because a quarantined step is a
    # (context -> action) pair the model never sees.
    missing_terminal, interior = [], []
    quarantined = 0
    for key, steps in corpus.items():
        nums = sorted(steps)
        n = (steps[nums[-1]].get("meta") or {}).get("n_steps")
        if n is not None and nums[-1] != n:
            missing_terminal.append({"domain": key[0], "task_id": key[1],
                                     "max_step": nums[-1], "n_steps": n})
        span = list(range(1, (n or nums[-1]) + 1))
        gone = [x for x in span if x not in steps]
        if gone:
            quarantined += len(gone)
            interior.append({"domain": key[0], "task_id": key[1],
                             "n_steps": n, "absent": gone})
    rep["checks"]["coverage"] = {
        "ok": not missing_terminal,
        "missing_terminal": missing_terminal,
        "trajectories_with_interior_gaps": len(interior),
        "steps_quarantined_by_cap": quarantined,
        "gap_examples": interior[:8],
        "note": "interior gaps are the think-cap working as designed; only a "
                "missing TERMINAL step is a defect",
    }

    # ---- tail safety -----------------------------------------------------
    truncated, safe, unsafe, unresolved, branch = [], [], [], [], Counter()
    for key, steps in corpus.items():
        meta = steps[max(steps)].get("meta") or {}
        o, n, run = meta.get("orig_steps"), meta.get("n_steps"), meta.get("run")
        if not (o and n) or o <= n:
            continue
        truncated.append(key)
        base, st, status = resolve(results_root, run, key[0], key[1], o,
                                   load_steps)
        if status != "ok" or not st:
            unresolved.append({"domain": key[0], "task_id": key[1],
                               "run": run, "status": status})
            continue
        stop_s, end_s = st[n - 1], st[-1]
        a = sha(base / stop_s.screenshot) if stop_s.screenshot else None
        b = sha(base / end_s.screenshot) if end_s.screenshot else None
        dropped = st[n - 1:]
        real = [{"step": s.num, "action": x[:90]} for s in dropped
                for x in s.actions if not is_noop(x)]
        # Which branch of the stalled-tail heuristic condemned each cut step:
        # `waited` = the step CONTAINS a wait (too loose -- click-then-wait is
        # productive), `same` = the step's post-action screen is unchanged.
        shas = {s.num: (sha(base / s.screenshot) if s.screenshot else None)
                for s in st}
        for i, s in enumerate(st[n - 1:len(st) - 1], start=n - 1):
            waited = any((x or "").strip() in noop for x in s.actions)
            alln = bool(s.actions) and all(is_noop(x) for x in s.actions)
            same = (shas.get(s.num) is not None and i > 0
                    and shas.get(s.num) == shas.get(st[i - 1].num))
            branch["waited_only" if (waited and not same and not alln)
                   else "all_noop" if alln else "same_screen" if same
                   else "neither"] += 1
        rec = {"domain": key[0], "task_id": key[1], "kept": n, "orig": o,
               "real_actions_dropped": len(real), "examples": real[:8]}
        (safe if (a and b and a == b) else unsafe).append(rec)
    harmful = [r for r in unsafe if r["real_actions_dropped"] > 0]
    rep["checks"]["tail_safety"] = {
        "ok": not harmful,
        "truncated": len(truncated),
        "screen_identical": len(safe),
        "screen_differs": len(unsafe),
        "screen_differs_but_no_real_action": len(unsafe) - len(harmful),
        "HARMFUL": len(harmful),
        "real_actions_dropped_total": sum(r["real_actions_dropped"]
                                          for r in harmful),
        "harmful_detail": sorted(harmful,
                                 key=lambda r: -r["real_actions_dropped"]),
        "condemned_step_branch": dict(branch),
        "unresolved": unresolved,
        "note": "HARMFUL = terminate lands on a screen the checker never "
                "approved AND real actions were removed",
    }

    # ---- invariance vs baseline -----------------------------------------
    if baseline_dirs:
        base_c = load_corpus(baseline_dirs)
        same_n = diff_n = 0
        diffs = []
        shared_keys = set(corpus) & set(base_c)
        for key in shared_keys:
            terminal = max(corpus[key])
            for stp, s in corpus[key].items():
                if stp == terminal:
                    continue
                o = base_c[key].get(stp)
                if o is None:
                    continue
                if o.get("response") == s.get("response"):
                    same_n += 1
                else:
                    diff_n += 1
                    if len(diffs) < 10:
                        diffs.append({"domain": key[0], "task_id": key[1],
                                      "step": stp})
        rep["checks"]["invariance"] = {
            "ok": diff_n == 0,
            "baseline": [str(d) for d in baseline_dirs],
            "shared_trajectories": len(shared_keys),
            "non_terminal_identical": same_n,
            "non_terminal_differing": diff_n,
            "examples": diffs,
            "note": "the rewrite must touch the FINAL target only",
        }

    # ---- justification ---------------------------------------------------
    think = []
    for key, steps in corpus.items():
        r = steps[max(steps)].get("response", "")
        think.append(r.split("</think>")[0].replace("<think>", "").strip())
    c = Counter(think)
    words = sorted(len(t.split()) for t in think)
    rep["checks"]["justification"] = {
        "ok": bool(think) and c.most_common(1)[0][1] <= max(10,
                                                            len(think) // 20),
        "n": len(think), "distinct": len(c),
        "words_median": words[len(words) // 2] if words else 0,
        "words_p90": words[int(len(words) * 0.9)] if words else 0,
        "words_max": words[-1] if words else 0,
        "empty": sum(1 for t in think if not t),
        "top_repeats": [{"text": t[:120], "n": k}
                        for t, k in c.most_common(3) if k > 1],
        "note": "a canned template repeated across the corpus teaches the "
                "sentence, not the decision",
    }

    rep["ok"] = all(v.get("ok") for v in rep["checks"].values())
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", action="append", required=True,
                    help="a build output dir (repeat for multi-pool arms)")
    ap.add_argument("--results-root", required=True,
                    help="results_generated root: <model>/<run>/<domain>/<id>")
    ap.add_argument("--baseline", action="append", default=[],
                    help="corpus to compare non-terminal targets against")
    ap.add_argument("--harness", default=None,
                    help="OSWorld root, for the real action parser")
    ap.add_argument("--ostg", default=None,
                    help="ostg root, if not already importable")
    ap.add_argument("--noop-actions", default=DEFAULT_NOOP)
    ap.add_argument("--label", default="corpus")
    ap.add_argument("--json", default=None)
    ap.add_argument("--text", action="store_true")
    a = ap.parse_args(argv)

    if a.ostg:
        sys.path.insert(0, a.ostg)
    from ostg.sft.traj import load_steps

    rep = audit(a.corpus, a.results_root, a.baseline, a.harness,
                a.noop_actions, a.label, load_steps)
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=2, ensure_ascii=False),
                                encoding="utf-8")
        print("wrote", a.json)
    if a.text or not a.json:
        for name, c in rep["checks"].items():
            print("[%s] %s" % ("ok " if c.get("ok") else "FAIL", name))
            for k, v in c.items():
                if k in ("ok", "note"):
                    continue
                s = json.dumps(v, ensure_ascii=False)
                print("      %-34s %s" % (k, s if len(s) < 120
                                          else s[:117] + "..."))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
