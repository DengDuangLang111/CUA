#!/usr/bin/env python3
"""Live half of the dashboard's SFT section.

Two jobs, both driven off the tier-3 result dirs
(results_generated/<arm>/valpanel-a1/<domain>/<task>/):

  status   -> dashboard/sft.json   every cycle, cheap
  publish  -> dashboard/traj/sft/<arm>/  once per arm, ~4 MB

sft.json is a SEPARATE file from status.json on purpose: two writers, two
files, so a cycle of one can never clobber a key of the other.

Publishing is once-per-arm because a tier-3 arm is frozen the moment its 9th
result.txt lands -- unlike the live v11-500 rollout, nothing here churns. The
fingerprint (result count + newest traj mtime) is stored inside the published
directory, so a re-run of an arm republishes and a finished one never does.

Screenshots are recompressed (JPEG q30, 1000 px) and then DEDUPED by content
hash: a 50-step loop trajectory is ~50 near-copies of one screen, and dropping
the duplicates cuts a typical arm from 352 files / 77 MB to ~150 files / 4 MB.
Deduping happens AFTER traj_html writes viewer.html, so the surviving file's
name is substituted into the HTML rather than left dangling.

    python3 sft_dash.py status
    python3 sft_dash.py publish
"""
import collections
import datetime
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

BASE = "/mnt/d/research/OSWorld/results_generated"
PANEL = "/mnt/d/research/OSWorld/eval_valpanel_tasks"
REPO = "/home/daniel_yan/cua-dash-sft"
OUT = REPO + "/dashboard/sft.json"
PUBROOT = REPO + "/dashboard/traj/sft"
STAGE = "/tmp/sftpub"
OSTG = "/mnt/d/research/ostg-v11.1"
PY = "/mnt/d/research/OSWorld/.venv/bin/python"

# ---- verified eval-50: the frozen OSWorld-Verified sample the SFT arms are
# scored on (TRAINING.md "Verified eval protocol"). Run dirs are discovered as
# BASE/*/eval50-<key>-<date>/; key -> (label, group, note). An unlisted key
# still appears with the raw key as its label -- visible gap, not a dropped row.
EVAL50_META = "/mnt/d/research/OSWorld/evaluation_examples/verified_eval50_nonproxy.json"
EVAL50_EXAMPLES = "/mnt/d/research/OSWorld/evaluation_examples/examples"
EVAL50_ARMS = {
    "base":      ("stock 4B · stock template", "reference",
                  "no SFT. The number every trained arm has to beat."),
    "basekeep":  ("stock 4B · keepthink (base control)", "reference",
                  "STOCK weights under the exact rich/rich serving -- the pair with"
                  " richrich isolates SFT itself; weights are the only difference"),
    "rich150":   ("rich ep1 · keepthink (epochs lever)", "sft",
                  "rich weights at checkpoint-150 (1 epoch) -- does shallower"
                  " training retain more of the base's general skill?"),
    "richrich":  ("rich · keepthink (rich/rich)", "sft",
                  "rich weights (232347, ckpt-450) + keepthink template + --preserve_thinking"),
    "leankeep":  ("lean · keepthink (OpenWebRL-style)", "sft",
                  "lean weights (232348, ckpt-450) evaluated with history think restored"),
    "b1epkeep":  ("B-1ep · keepthink (single-epoch, full anneal)", "sft",
                  "B corpus (312 trajs), ONE epoch with the LR annealed to zero"
                  " -- a true 1-epoch model, not a mid-schedule snapshot;"
                  " quantity lever at minimal depth"),
    "gb128ep2keep": ("B-gb128 ep2 · keepthink (batch-128 salvage)", "sft",
                  "epoch-2 boundary checkpoint salvaged from the dead multinode"
                  " global-128 run (235513); flat-damage law makes ep2 the"
                  " de-facto batch-128 data point"),
    "gb64keep":  ("B-gb64o · keepthink (batch-64, aligned optim)", "sft",
                  "B corpus, global batch 64 (16xH200 x accum 4), 3ep, wd 0.0,"
                  " beta2 0.999 -- optimization-domain lever at the stable"
                  " half-scale after global-128 multinode deaths"),
    "gb128keep": ("B-gb128 · keepthink (batch-128 regime)", "sft",
                  "B corpus (312 trajs), OpenWebRL optimization regime: global"
                  " batch 128 (16xH200 x accum 8), 3ep, cosine warmup 0.1 --"
                  " the optimization-domain lever, same keepthink serving"),
    "richstock": ("rich · stock template (Verified default)", "sft",
                  "same rich ckpt-450 weights as richrich, served on the OFFICIAL"
                  " template (history think stripped at render) -- the"
                  " OSWorld-Verified default; pairs with richrich to isolate"
                  " eval-time history-think visibility"),
    "bskeep":    ("Bs-gb64 · keepthink (tail-clean cap 2048)", "sft",
                  "B corpus with the >2048-token think targets masked out"
                  " (73 steps, 15.6% of target tokens; steps stay in history)"
                  " -- same gb64 config as gb64o, so the cap is the only"
                  " variable"),
    "bhqskeep":  ("Bhqs-gb64 · keepthink (curated corpus)", "sft",
                  "Bhqs = two judge families agreeing (Qwen v2req >=9 + clean"
                  " requirement checklist, Opus >=8), no weak terminal step,"
                  " plus 54 checker-bug trajectories rescued by arbitration."
                  " 304 trajs / 5,367 samples, same cap 2048 and gb64 config"
                  " as Bs -- curation is the only variable"),
    "bhqs2tkeep": ("Bhqs-2-terminal · keepthink (endings canonicalised)", "sft",
                  "rev2 curation PLUS every trajectory ending rewritten to an"
                  " explicit terminate(success) -- the teacher writes the"
                  " task-specific justification, the tool call is appended"
                  " deterministically. Before this, 85% of endings were bare"
                  " prose or call_user, and the 4B student went from 100%"
                  " explicit termination pre-SFT to 0% post-SFT. Two changes"
                  " against Bs (curation + endings): a decomposition needs the"
                  " plain rev2 arm, which was skipped to save eval slots"),
    "bhqs2keep": ("Bhqs-2 · keepthink (curation rev2)", "sft",
                  "corpus curated on EVIDENCE only -- a hard requirement"
                  " defect or an arbitration conviction removes a trajectory;"
                  " the free 0-10 score never gates (it has no ranking power"
                  " inside the good band). Every rescue survived an"
                  " adversarial defence of its checker. Same cap 2048 and"
                  " gb64 config as Bs, so curation is the only variable"),
    "bhqs2lrkeep": ("Bhqs-2 · lr 3e-6 · keepthink (displacement probe)", "sft",
                  "same rev2 corpus at lr 3e-6: cumulative LR 3.78e-4, which"
                  " is 0.6x our best observed point and within 1% of"
                  " OpenWebRL's own SFT budget -- a second point on the"
                  " displacement axis with the corpus held fixed"),
    "lorakeep":  ("Bs-LoRA · keepthink (adapter vs full FT)", "sft",
                  "same Bs corpus, LoRA r=32 alpha=64 on all linear layers"
                  " (lr 1e-4), merged into full weights before serving so the"
                  " inference path matches every other arm -- how the weights"
                  " were produced is the only variable"),
    "leanstock": ("lean · stock (lean/lean)", "sft",
                  "lean weights on the stock template -- trained blind, evaluated blind"),
    "lorastock": ("Bs-LoRA e3.00 · stock (endpoint)", "sft",
                  "Bs-LoRA served at its true 3.00-epoch endpoint under the stock"
                  " template (45.81%); after the template-equivalence finding the"
                  " keepthink twin is a same-config repeat, not a contrast"),
    "bsstock":   ("Bs-gb64 e3.00 · stock (kC, no-split)", "sft",
                  "full-FT Bs corpus at checkpoint-264 (pick_ckpt endpoint) --"
                  " FIRST arm under OSTG_TYPE_NO_SPLIT=1 (multi-line type sent as"
                  " one typewrite; every arm through kD ran under the upstream"
                  " per-line split)"),
    "r5lora":    ("r5-LoRA e3.00 · stock", "sft",
                  "r5 corpus (terminal fix) LoRA at its endpoint: explicit"
                  " terminate 6%->60%, false done 0/7, 41.81% -- failures still"
                  " grind the 50-step cap because the corpus has no failure"
                  " endings"),
    "kD":        ("r5 full-FT e3.00 · stock (Klone)", "sft",
                  "q38Bhqs2t-gb64 endpoint served on Klone L40S through the"
                  " Tillicum maintenance; 48/50 scored, 49.81% 0-filled -- best"
                  " arm to date. 2 tasks abandoned by user call: one stalled"
                  " impress task, one 217-command storm grinder"),
    "kE":        ("r5 lr3e-6 e3.00 · stock (no-split)", "sft",
                  "same r5 corpus at lr 3e-6 (displacement probe), checkpoint-300"
                  " endpoint"),
    "kD1":       ("r5 full-FT ~1ep · stock (no-split)", "sft",
                  "kD's weights at checkpoint-90 (~epoch 1) -- the 1-epoch"
                  " comparator for the 49.81% endpoint"),
    "kG":        ("r5-LoRA no-prose e3.00 · stock (no-split)", "sft",
                  "loranp corpus = r5 with ALL inter-think prose stripped (two"
                  " build gates: zero-prose + strip-both-identical); differs from"
                  " r5lora only by prose removal"),
}

# What each arm isolates. Anything not listed still appears -- an unlabelled
# row is a visible gap, a dropped row is an invisible one.
#   key: (label, group, data, samples, epochs, preserve_thinking, note)
ARMS = {
    "qwen36-teacher":    ("teacher · Qwen3.6-27B", "teacher", "—", "—", "—", "—",
                          "its own passing trajectories, lifted from the runs that produced "
                          "the SFT data — 9/9 is selection, not a score (see PROVENANCE.json)"),
    "qwen35-4b-base":    ("stock Qwen3.5-4B", "reference", "—", "—", "—", "—",
                          "no SFT. The number every trained arm has to beat."),
    "q35-base-topk":     ("stock + top_k 20", "reference", "—", "—", "—", "—",
                          "same model, sampler matched to Qwen3.5's official recommendation"),
    "owrl-4b-sft":       ("OpenWebRL-4B-SFT", "external", "theirs", 3085, 3, "—",
                          "someone else's corpus at 2.4x our samples — an outside scale reading"),
    "qwen35-4b-v1":      ("v1 · pilotS", "pre-fix", "pilot2", 609, 1, "unset",
                          "first full-FT; ran on 609 of 916 samples (the silent media drop)"),
    "qwen35-4b-pilotS3": ("v2 · pilotS3", "pre-fix", "pilot2", 609, 1, "true",
                          "same data defect, + preserve_thinking"),
    "qwen35-4b-pp15":    ("v2 + presence 1.5", "pre-fix", "pilot2", 609, 1, "true",
                          "sampler ablation on v2 — does penalising repeats break the loop?"),
    "q35-e1":            ("e1", "fixed data", "abs-pilot2", 916, 1, "true",
                          "RECIPE v3: absolute media paths, preflight — the honest 1-epoch point"),
    "q35-e3":            ("e3", "fixed data", "abs-pilot2", 916, 3, "true",
                          "e1 + two more epochs, fully annealed. The only lever that moved."),
    "q35-more":          ("more", "fixed data", "abs-pilot3", 1288, 1, "true",
                          "e1 + 40% more data at 1 epoch — isolates volume"),
}
# The checkpoint pipeline names its arms q35-<run>-ep<k>; derive the rest.
FAMILY = {
    "ep5pt":   ("ep5pt", "abs-pilot3", 1288, 5, "true",
                "5-epoch schedule, preserve on — snapshot at each epoch"),
    "ep5np":   ("ep5np", "abs-pilot3", 1288, 5, "false",
                "5-epoch schedule, preserve off — the same curve without history reasoning"),
    "more3":   ("more3", "abs-pilot3", 1288, 3, "true",
                "3 epochs on the bigger corpus, annealed — vs e3 this is the volume test"),
    "more3np": ("more3np", "abs-pilot3", 1288, 3, "false",
                "more3 without preserve_thinking — the flag's effect on a clean annealed point"),
}
GROUPS = ["teacher", "reference", "external", "pre-fix", "fixed data", "epoch curve"]


def arm_meta(key):
    if key in ARMS:
        lab, grp, data, n, ep, pt, note = ARMS[key]
        return dict(label=lab, group=grp, data=data, samples=n,
                    epochs=ep, preserve=pt, note=note)
    m = re.match(r"^q35-(.+)-ep(\d+)$", key)
    if m and m.group(1) in FAMILY:
        run, data, n, tot, pt, note = FAMILY[m.group(1)]
        k = int(m.group(2))
        return dict(label="%s · epoch %d" % (run, k), group="epoch curve",
                    data=data, samples=n, epochs="%d of %d" % (k, tot),
                    preserve=pt, note=note)
    # `-final` is the annealed product: the run's last checkpoint, LR at 0.
    # Distinct from an epoch-k snapshot of a longer run, which is mid-schedule.
    m = re.match(r"^q35-(.+)-final$", key)
    if m and m.group(1) in FAMILY:
        run, data, n, tot, pt, note = FAMILY[m.group(1)]
        return dict(label="%s · final" % run, group="fixed data",
                    data=data, samples=n, epochs="%d, annealed" % tot,
                    preserve=pt, note=note)
    return dict(label=key, group="epoch curve", data="?", samples="?",
                epochs="?", preserve="?", note="")


def panel():
    """The 9 held-out tasks, in a fixed order (easiest first, then by domain)."""
    out = {}
    for f in glob.glob(PANEL + "/examples/*/*.json"):
        j = json.load(open(f, encoding="utf-8"))
        o = j.get("ostg") or {}
        out[j["id"]] = {"id": j["id"], "slug": o.get("slug", j["id"]),
                        "dom": os.path.basename(os.path.dirname(f)),
                        "diff": o.get("difficulty"),
                        "apps": j.get("related_apps") or [],
                        "instr": j.get("instruction", "")}
    return out


def read_arm(d):
    """Per-task score + the behavioural counters that loss curves never saw."""
    tasks = {}
    for rt in glob.glob(d + "/*/*/result.txt"):
        td = os.path.dirname(rt)
        tid = os.path.basename(td)
        try:
            score = float(open(rt).read().strip())
        except ValueError:
            score = None
        acts, steps = [], set()
        tj = os.path.join(td, "traj.jsonl")
        if os.path.isfile(tj):
            for l in open(tj, encoding="utf-8"):
                if not l.strip():
                    continue
                try:
                    r = json.loads(l)
                except ValueError:      # torn line, runner mid-write
                    continue
                steps.add(r.get("step_num"))
                acts.append(str(r.get("action")))
        c = collections.Counter(acts)
        tasks[tid] = {"score": score, "steps": len(steps), "actions": len(acts),
                      "distinct": len(c),
                      "maxrep": (c.most_common(1)[0][1] if c else 0),
                      "term": any(a.strip() == "DONE" for a in acts),
                      "dom": os.path.basename(os.path.dirname(td))}
    return tasks


def eval50_tasks():
    """The frozen 50, keyed by id; column order = domain, then id."""
    out = {}
    try:
        meta = json.load(open(EVAL50_META, encoding="utf-8"))
    except Exception:
        return out
    for dom, ids in meta.items():
        for tid in ids:
            instr = ""
            try:
                instr = json.load(open(os.path.join(EVAL50_EXAMPLES, dom, tid + ".json"),
                                       encoding="utf-8")).get("instruction", "")
            except Exception:
                pass
            out[tid] = {"id": tid, "dom": dom, "instr": instr}
    return out


def eval50():
    tasks = eval50_tasks()
    order = sorted(tasks.values(), key=lambda t: (t["dom"], t["id"]))
    arms = []
    for d in sorted(glob.glob(BASE + "/*/eval50-*")):
        run = os.path.basename(d)
        modeldir = os.path.basename(os.path.dirname(d))
        m = re.match(r"^eval50-([A-Za-z0-9]+)-\d+$", run)
        key = m.group(1) if m else run
        label, group, note = EVAL50_ARMS.get(key, (key, "?", ""))
        got = {tid: r for tid, r in read_arm(d).items() if tid in tasks}
        arms.append({"key": key, "run": run, "modeldir": modeldir,
                     "label": label, "group": group, "note": note,
                     "scored": len(got),
                     "passed": sum(1 for r in got.values() if r["score"] == 1.0),
                     # Denominator is the FROZEN PANEL (50), never the number
                     # of tasks that happened to finish: a task the harness
                     # never completed scores 0, per the accounting policy
                     # (OPS.md, 2026-08-17). Dividing by len(got) silently
                     # rewarded arms that lost tasks to VM stalls -- gb64keep
                     # read 44.5% on 47 tasks where the panel score is 41.8%.
                     "mean": (round(sum(r["score"] or 0 for r in got.values())
                                    / len(order), 4) if got else None),
                     "mean_scored": (round(sum(r["score"] or 0 for r in got.values())
                                           / len(got), 4) if got else None),
                     "missing": len(order) - len(got),
                     "tasks": got})
    return {"panel": order, "n": len(order), "arms": arms}


def status():
    pan = panel()
    order = sorted(pan.values(), key=lambda t: (t["diff"] or 9, t["dom"], t["slug"]))
    arms = []
    for key in sorted(os.listdir(BASE)):
        d = os.path.join(BASE, key, "valpanel-a1")
        if not os.path.isdir(d):
            continue
        tasks = read_arm(d)
        if not tasks:
            continue
        m = arm_meta(key)
        m.update(key=key, scored=len(tasks),
                 passed=sum(1 for t in tasks.values() if t["score"] == 1.0),
                 term=sum(1 for t in tasks.values() if t["term"]),
                 capped=sum(1 for t in tasks.values() if t["steps"] >= 50),
                 tasks=tasks,
                 traj=("traj/sft/%s/index.html" % key
                       if os.path.isfile(os.path.join(PUBROOT, key, "index.html"))
                       else None))
        arms.append(m)
    arms.sort(key=lambda a: (GROUPS.index(a["group"]) if a["group"] in GROUPS else 9,
                             -a["passed"], a["key"]))
    # Panel identity. The 9 tasks are a materialised directory, not a live
    # draw, but nothing stopped it from being regenerated silently -- and an
    # arm measured on 9 tasks is not comparable to one measured on 12. This
    # fingerprint makes any change to the panel show up on the page.
    pid = hashlib.md5(",".join(sorted(pan)).encode()).hexdigest()[:8]
    out = {"updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M PT"),
           "panel": order, "panel_id": pid, "panel_n": len(pan),
           "arms": arms, "groups": GROUPS, "eval50": eval50()}
    old = None
    try:
        old = json.load(open(OUT))
    except Exception:
        pass
    if old and {k: v for k, v in old.items() if k != "updated"} == \
               {k: v for k, v in out.items() if k != "updated"}:
        return False
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)
    return True


def fingerprint(d):
    n = len(glob.glob(d + "/*/*/result.txt"))
    t = max([os.path.getmtime(p) for p in glob.glob(d + "/*/*/traj.jsonl")] or [0])
    return "%d:%d" % (n, int(t))


def squash(root):
    """JPEG-recompress every screenshot, then drop content duplicates and point
    the viewer at the survivor. Loop trajectories are mostly duplicates."""
    from PIL import Image
    for p in glob.glob(root + "/**/step_*.png", recursive=True) + \
             glob.glob(root + "/**/initial_state.png", recursive=True):
        try:
            im = Image.open(p).convert("RGB")
            if im.width > 1000:
                im = im.resize((1000, int(im.height * 1000 / im.width)))
            im.save(p, "JPEG", quality=30, optimize=True)
        except Exception:
            pass
    for td in glob.glob(root + "/*/*/"):
        seen, sub = {}, {}
        for p in sorted(glob.glob(td + "*.png")):
            h = hashlib.md5(open(p, "rb").read()).hexdigest()
            b = os.path.basename(p)
            if h in seen:
                sub[b] = seen[h]
                os.remove(p)
            else:
                seen[h] = b
        v = os.path.join(td, "viewer.html")
        if sub and os.path.isfile(v):
            s = open(v, encoding="utf-8").read()
            for dup, keep in sub.items():
                s = s.replace('src="%s"' % dup, 'src="%s"' % keep)
            open(v, "w", encoding="utf-8").write(s)


def publish():
    """Complete arms publish once. The one arm still rolling refreshes at most
    every 30 min -- the same rule (and the same reason) as the live rollout's
    viewer: JPEGs do not delta-compress, so republishing on every 5-minute cycle
    would add its full weight to git history each time."""
    npanel = len(glob.glob(PANEL + "/examples/*/*.json")) or 9
    done = []
    for key in sorted(os.listdir(BASE)):
        src = os.path.join(BASE, key, "valpanel-a1")
        if not os.path.isdir(src):
            continue
        n = len(glob.glob(src + "/*/*/result.txt"))
        if n < 1:
            continue
        dst = os.path.join(PUBROOT, key)
        fp = fingerprint(src)
        stamp = os.path.join(dst, ".fingerprint")
        if os.path.isfile(stamp):
            if open(stamp).read().strip() == fp:
                continue
            if n < npanel and time.time() - os.path.getmtime(stamp) < 1800:
                continue          # still rolling, refreshed recently enough
        stg = os.path.join(STAGE, key)
        shutil.rmtree(stg, ignore_errors=True)
        os.makedirs(stg, exist_ok=True)
        subprocess.run(["rsync", "-a", "--exclude=*.mp4", "--exclude=viewer.html",
                        "--exclude=index.html", src + "/", stg + "/"], check=False)
        subprocess.run([PY, "-m", "ostg.traj_html", stg, "--tasks", PANEL],
                       cwd=OSTG, env=dict(os.environ, PYTHONPATH="."),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        squash(stg)
        open(os.path.join(stg, ".fingerprint"), "w").write(fp)
        os.makedirs(dst, exist_ok=True)
        subprocess.run(["rsync", "-a", "--delete", stg + "/", dst + "/"], check=False)
        shutil.rmtree(stg, ignore_errors=True)
        n = len(glob.glob(dst + "/*/*/viewer.html"))
        mb = sum(os.path.getsize(p) for p in
                 glob.glob(dst + "/**/*", recursive=True) if os.path.isfile(p)) / 1e6
        print("published %s: %d viewers, %.1f MB" % (key, n, mb))
        done.append(key)
    return done


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "publish":
        got = publish()
        sys.exit(0 if got else 3)          # 3 = nothing new, same idiom as status
    changed = status()
    sys.exit(0 if changed else 3)
