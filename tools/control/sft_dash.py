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
    "kD15":      ("r5 full-FT epoch 1.5 · stock (no-split)", "sft",
                  "kD's weights at checkpoint-150 -- epoch 1.501, exactly half"
                  " the 3-epoch schedule. Replaces the planned ~1ep arm: the run"
                  " saved no epoch-1.0 boundary (save_steps 30 does not divide"
                  " 100 steps/epoch), so the user chose the halfway point"),
    "kG":        ("r5-LoRA no-prose e3.00 · stock (no-split)", "sft",
                  "loranp corpus = r5 with ALL inter-think prose stripped (two"
                  " build gates: zero-prose + strip-both-identical); differs from"
                  " r5lora only by prose removal"),
    "vlbase":    ("stock Qwen3-VL-4B-Thinking · (no-split)", "reference",
                  "the baseline for the VL stack experiments: untouched"
                  " Qwen3-VL-4B-Thinking on the same frozen 50 -- every VL SFT"
                  " arm reads against this number, not against the Qwen3.5"
                  " base"),
    "nocap":     ("r5 lr3e-6 e3.00 no-cap · stock (no-split)", "sft",
                  "kE's exact config without the 2048 think-cap: the pair with"
                  " kE isolates the cap, the only quality intervention not yet"
                  " superseded (capped arms overran 2048 MORE, 11.0% vs 2.8%)"),
    "t38":       ("teacher Qwen3.8-27B · stock (no-split)", "teacher",
                  "the ceiling reference: the 27B teacher that generated every r5"
                  " corpus, on the SAME frozen 50 tasks, same harness, same"
                  " sampling protocol as the student arms. How much of the gap"
                  " to the teacher has SFT closed -- and how high is the"
                  " ceiling itself?"),
    "vlsft":     ("Qwen3-VL x r5vl lr3e-6 e3.00 · stock (no-split)", "sft",
                  "the VL-backbone experiment: Qwen3-VL-4B-Thinking fine-tuned"
                  " on the r5vl corpus at lr 3e-6; reads against vlbase, not the"
                  " Qwen3.5 base"),
    "img3":      ("img3 @ 20-img eval · stock (no-split)", "sft",
                  "kE's exact recipe with the TRAINING screenshot window 20->3"
                  " (visual tokens cut to 29%); evaluated on the STANDARD"
                  " 20-image protocol by user order -- the deliberate"
                  " train/eval-skew cell of the history-window 2x2"),
    "img3h3":    ("img3 @ 3-img eval · stock (no-split)", "sft",
                  "same img3 weights evaluated with --image_max 3 --fold_size 1"
                  " -- the matched cell (3-train/3-eval) of the 2x2"),
    "kEh1":      ("kE @ 1-img eval · stock (no-split)", "sft",
                  "kE's weights with only the CURRENT screenshot in context"
                  " (--image_max 1 --fold_size 1): the extreme point of the"
                  " eval-window curve 20/3/1 -- how much history does the"
                  " champion recipe actually need at serve time?"),
    "baseh1":    ("stock 4B @ 1-img eval · stock (no-split)", "reference",
                  "untrained Qwen3.5-4B with only the current screenshot"
                  " (--image_max 1 --fold_size 1): the no-SFT floor of the"
                  " 1-image column for the 1pic-vs-3pic training-window call"),
    "nocapt0":   ("nocap @ greedy t0 · stock (no-split)", "sft",
                  "the champion weights rerun at temperature 0 / top_p 1"
                  " (greedy; vLLM ignores top_k at t=0, and the request never"
                  " carried top_k anyway): how many of the champion's points"
                  " are sampling luck, and does greedy loop a thinking model?"),
    "nocapnp":   ("nocap no-prose e3.00 · stock (no-split)", "sft",
                  "the champion recipe with teacher prose stripped -- PROSE IS"
                  " THE ONLY VARIABLE vs nocap 59.81; prior: kG (LoRA+no-prose)"
                  " beat r5lora by 8pp past the noise floor"),
    "nocapnp2":  ("no-prose @ e2.00 (salvage) · stock (no-split)", "sft",
                  "the 2-epoch checkpoint rescued from the no-prose run that"
                  " died at 73%: an early read on whether stripping teacher"
                  " prose survives at full fine-tune. Two variables vs nocap"
                  " 59.81 (prose AND epochs), so it answers 'did it break'"),
    "t3850b":    ("teacher 27B @ HELD-OUT 50 · stock (no-split)", "teacher",
                  "the 69.81 teacher on the held-out half: the ceiling read"
                  " out of sample, so the champion-to-teacher gap can be"
                  " compared on tasks no decision ever touched"),
    "nocap50b":  ("champion @ HELD-OUT 50 · stock (no-split)", "sft",
                  "the 59.81 champion on the other half of the frozen 100:"
                  " 50 tasks held out since 2026-08-15, never run by any model"
                  " and never seen by any decision -- the out-of-sample paper"),
    "base50b":   ("stock 4B @ HELD-OUT 50 · stock (no-split)", "reference",
                  "the untrained base on the same held-out 50, so the"
                  " champion-vs-base margin can be read out of sample"),
    "base261":   ("stock 4B @ REST 261 · stock (no-split)", "reference",
                  "the untrained base over the 261 of test_nogdrive the frozen"
                  " 100 does not cover; with basekeep and base50b this is the"
                  " base model on the official 361"),
    "nocap261":  ("champion @ REST 261 · stock (no-split)", "sft",
                  "the 59.81 champion over the same remaining 261, completing"
                  " a 361 for the strongest arm"),
    "nocapnp238":("no-prose @ e2.36 (furthest) · ALL 100", "sft",
                  "the furthest checkpoint the no-prose full fine-tune ever"
                  " reached before two hardware failures: epoch 2.356 with the"
                  " learning rate already down to 4.03e-7, i.e. 87% of the"
                  " anneal done -- a much closer stand-in for the 3-epoch"
                  " endpoint than the 55.81 salvage at epoch 2.00"),
    "np1e6":     ("no-prose @ lr 1e-6 · stock (no-split)", "sft",
                  "the nocapnp recipe with lr 3e-6 -> 1e-6 as the only"
                  " variable (cumulative dose 1.5e-4 vs the champion's"
                  " 4.5e-4, a 3x cut): the first sample ever taken left of"
                  " the peak"),
    "vlnocapnp": ("VL nocap+no-prose lr3e-6 · stock (no-split)", "sft",
                  "the VL line re-enters with the winning recipe: r5vlnocapnp"
                  " (think uncapped, teacher prose stripped) at lr 3e-6 gb64;"
                  " reads against vlsft 44.00 with cap+prose changed jointly"),
    "img1":      ("img1 @ 1-img eval · stock (no-split)", "sft",
                  "kE's exact recipe with the TRAINING screenshot window"
                  " 20 -> 1, evaluated at the matched 1-image window"
                  " (--image_max 1 --fold_size 1): the extreme cell of the"
                  " training-window axis (20: 57.81, 3: 53.81 matched)"),
    "kEh3":      ("kE @ 3-img eval · stock (no-split)", "sft",
                  "kE's 20-image-trained weights evaluated with --image_max 3"
                  " --fold_size 1 -- the 20-train/3-eval cell: how much does the"
                  " champion lose when history is starved at eval time?"),
    "gb128":     ("VL img3 @ gb128 · 3-img eval (no-split)", "sft",
                  "VL backbone x 3-image corpus at global batch 128 (8 nodes x"
                  " 1 GPU x bs1 x accum16 after the bs2 OOM); evaluated at its"
                  " matched 3-image window"),
    "vl20":      ("VL 20-img lr1e-5 · stock (no-split)", "sft",
                  "VL backbone x r5vl full-window corpus at lr 1e-5 (kD-recipe"
                  " twin on VL); standard 20-image eval"),
    # ---- the img10 corpus arms (2026-08-22) ----
    # Same 6474 samples as nocap, but a 10-screenshot history window held flat
    # by fold_size=1 instead of 20. Peak memory 136.7 -> 83.74 GiB, and that
    # headroom is what makes a3 and the 9B affordable at all.
    "a1":        ("img10 4B e3.00 · stock (no-split)", "sft",
                  "champion recipe on the 10-image window. Sample count identical"
                  " to nocap and the curation report matches field for field, so"
                  " the window is the only variable. Control: nocap"
                  " (59.81 seen-50 / 47.00 on the official 361)"),
    "a2":        ("img10 9B e3.00 · stock (no-split)", "sft",
                  "a1 with the backbone swapped. Qwen3.5-9B shares the 4B's 32"
                  " layers / 16 heads / 4 KV heads / 248320 vocab; only hidden"
                  " 2560->4096 and intermediate 9216->12288. READ IT AGAINST THE"
                  " 9B BASE, never against the 4B arms"),
    "a3":        ("img10 4B hermes e3.00 · stock (no-split)", "sft",
                  "a1 with loss_scale last_round+hermes, which in ms-swift is"
                  " exactly {tool_call: 2.0}: think falls 70.0% -> 59.5% of"
                  " supervised tokens, tool_call rises 17.8% -> 30.3%. WATCH THE"
                  " FAILURE MODES, NOT THE SCORE ALONE -- terminate is itself a"
                  " tool_call and all 362 corpus terminations are status=success,"
                  " so up-weighting actions may raise the 21% false-DONE rate"),
    "a5v":       ("img10v 4B 5ep lr2e-6 · stock (no-split)", "sft",
                  "5 epochs at lr 2e-6 (cumulative LR held near the 3-epoch"
                  " champion's, 4.6e-4 -> 5.1e-4) and the first arm on this line"
                  " with a validation split. TWO CAVEATS, both structural: its"
                  " endpoint is epoch 5, so it is not a same-epoch peer of"
                  " a1/a2/a3; and the 5% split leaves 6213 training samples,"
                  " not 6474, so the corpus is a second variable. The split also"
                  " moved steps/epoch 102 -> 97, which is why its intermediate"
                  " checkpoints sit at epoch 1.05/2.10/3.15 and its epoch-3"
                  " model does not exist (97 is prime; see TRAINING.md)"),
    "kF":        ("r5-LoRA lean e3.00 · stock (no-split)", "sft",
                  "lean variant of the r5 LoRA, endpoint merge. Dropped from the"
                  " Klone maintenance plan, restored 2026-08-18; with r5lora"
                  " (rich) and kG (no-prose) it completes the three-point prose"
                  " axis on the same corpus and adapter config"),
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


def eval50_tasks(meta_path=None):
    """A frozen 50-task panel, keyed by id; column order = domain, then id.

    Two panels exist. The default is the SEEN 50 every arm has been scored on.
    Arms whose key ends in "50b" run the HELD-OUT 50 -- the other half of the
    frozen 100, never used for any decision -- and their task ids appear in
    neither the seen panel nor each other's. Filtering every arm through the
    seen panel (as this did until 2026-08-20) silently reported the held-out
    arms as scored=0 with a full result directory on disk.
    """
    out = {}
    try:
        meta = json.load(open(meta_path or EVAL50_META, encoding="utf-8"))
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


HELDOUT_META = EVAL50_META.replace("verified_eval50_nonproxy",
                                   "verified_eval50b_nonproxy")
# The other 261 of test_nogdrive's 361. Verified disjoint from the frozen 100
# (100 union 261 == 361 exactly, intersection empty), so a 361 row is a union
# of three runs and never double-counts a task.
REST261_META = EVAL50_META.replace("verified_eval50_nonproxy",
                                   "verified_eval261_rest")


# A model that ran both halves gets a third, synthetic row spanning all 100
# columns, so the frozen-100 accuracy is readable directly instead of being
# added up by hand. Keyed child -> parent; the parent is the run on the SEEN
# half (the untrained base's seen-half run is "basekeep", not "base").
HELDOUT_PAIRS = {"nocap50b": "nocap", "base50b": "basekeep", "t3850b": "t38",
                 "kGh": "kG", "r5lorah": "r5lora"}

# A model that ALSO ran the remaining 261 gets a fourth synthetic row over the
# whole official 361. Keyed 261-arm -> (seen-half arm, held-out-half arm).
REST_TRIPLES = {"base261": ("basekeep", "base50b"),
                "nocap261": ("nocap", "nocap50b")}

# Arms not scored on the default (seen) panel.
ARM_PANEL = {"nocap50b": "heldout", "base50b": "heldout", "t3850b": "heldout",
             "np1e6": "all100", "nocapnp238": "all100", "nocapnp": "all100",
             "kGh": "heldout", "r5lorah": "heldout", "base9b": "all100",
             "nocapms100": "all100",
             # Without these two the 261 arms intersect the frozen-100 panel to
             # the empty set and read scored=0 forever. They were lost once
             # (2026-08-22, an edit from a stale copy) and the symptom was
             # exactly that: base261/nocap261 showing 0/50 with mean None while
             # 261 scored tasks sat on disk.
             "base261": "rest261", "nocap261": "rest261",
             # The img10 four (2026-08-22). All eval100; a5v's endpoint is
             # epoch 5, not 3 -- keep it out of any same-epoch comparison.
             "a1": "all100", "a2": "all100",
             "a3": "all100", "a5v": "all100"}


def eval50():
    tasks = eval50_tasks()
    heldout = eval50_tasks(HELDOUT_META)
    rest = eval50_tasks(REST261_META)
    # Columns are the full frozen 100: the seen half first, then the held-out
    # half. Arms that ran one half fill their own columns and show "-" in the
    # other, which is what makes the two halves line up task-by-task on screen.
    # Every arm's DENOMINATOR stays its own panel (50), so no existing number
    # moves when the column count doubles.
    order = sorted(tasks.values(), key=lambda t: (t["dom"], t["id"])) + \
            sorted(heldout.values(), key=lambda t: (t["dom"], t["id"]))
    arms = []
    for d in sorted(glob.glob(BASE + "/*/eval50-*")):
        run = os.path.basename(d)
        modeldir = os.path.basename(os.path.dirname(d))
        m = re.match(r"^eval50-([A-Za-z0-9]+)-\d+$", run)
        key = m.group(1) if m else run
        label, group, note = EVAL50_ARMS.get(key, (key, "?", ""))
        # Which frozen panel this arm was scored on. Explicit, not inferred
        # from the name: np1e6 runs the whole 100 in one pass while the "50b"
        # arms run only the held-out half, and getting this wrong silently
        # discards an arm's entire result set (it read scored=0 on 2026-08-20).
        panel = {"heldout": heldout, "all100": dict(tasks, **heldout),
                 "rest261": rest}.get(
            ARM_PANEL.get(key), tasks)
        got = {tid: r for tid, r in read_arm(d).items() if tid in panel}
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
                                    / len(panel), 4) if got else None),
                     "mean_scored": (round(sum(r["score"] or 0 for r in got.values())
                                           / len(got), 4) if got else None),
                     "missing": len(panel) - len(got),
                     "panel_n": len(panel),
                     "tasks": got})
    # synthetic all-100 rows for models that ran both halves
    by_key = {a["key"]: a for a in arms}
    for child, parent in HELDOUT_PAIRS.items():
        c, pa = by_key.get(child), by_key.get(parent)
        if not (c and pa):
            continue
        merged = dict(pa["tasks"]); merged.update(c["tasks"])
        arms.append({
            "key": parent + "100", "run": "", "modeldir": pa["modeldir"],
            "label": pa["label"].split(" · ")[0] + " · ALL 100 (seen + held-out)",
            "group": pa["group"],
            "note": "the same weights over the whole frozen 100: the left half is"
                    " the panel every arm was selected on, the right half was"
                    " never used for any decision. run=\"\" on purpose so cells"
                    " render as plain marks -- the two halves come from two runs"
                    " and a single traj link would point at the wrong one.",
            "scored": len(merged),
            "passed": sum(1 for r in merged.values() if r["score"] == 1.0),
            "mean": round(sum(r["score"] or 0 for r in merged.values()) / 100.0, 4),
            "mean_scored": (round(sum(r["score"] or 0 for r in merged.values())
                                  / len(merged), 4) if merged else None),
            "missing": 100 - len(merged),
            "panel_n": 100,
            "tasks": merged})
    # 361 rows: seen 50 + held-out 50 + rest 261 == test_nogdrive's 361.
    # Denominator is the full 361 from the first task on, so `mean` on a row
    # still in flight understates by design; read scored/panel_n for progress
    # and mean_scored for the current hit rate.
    for child, (seen_k, held_k) in REST_TRIPLES.items():
        c, sa, ha = by_key.get(child), by_key.get(seen_k), by_key.get(held_k)
        if not (c and sa and ha):
            continue
        merged = dict(sa["tasks"]); merged.update(ha["tasks"])
        merged.update(c["tasks"])
        arms.append({
            "key": seen_k + "361", "run": "", "modeldir": sa["modeldir"],
            "label": sa["label"].split(" · ")[0] + " · OFFICIAL 361 (test_nogdrive)",
            "group": sa["group"],
            "note": "the union of three runs on the same weights: the frozen"
                    " 100 (seen 50 + held-out 50) plus the remaining 261. Task"
                    " sets verified disjoint, so no task is counted twice."
                    " Harness is our MODIFIED OSWorld -- comparable across arms"
                    " here, NOT to the public leaderboard without disclosure.",
            "scored": len(merged),
            "passed": sum(1 for r in merged.values() if r["score"] == 1.0),
            "mean": round(sum(r["score"] or 0 for r in merged.values()) / 361.0, 4),
            "mean_scored": (round(sum(r["score"] or 0 for r in merged.values())
                                  / len(merged), 4) if merged else None),
            "missing": 361 - len(merged),
            "panel_n": 361,
            "tasks": merged})
    return {"panel": order, "n": len(order), "arms": arms}


# ---------------------------------------------------------------- 361 view --
# The official 361 (test_nogdrive) as three runs on the same weights. Kept OUT
# of the eval-50 matrix on purpose: that table's columns are the frozen 100, so
# a 361 arm has 261 columns it can never fill. Here the unit is the SLICE, not
# the task, so nothing has to line up horizontally.
SFT361 = {
    "base":  ("stock Qwen3.5-4B · untrained", "reference",
              ("basekeep", "base50b", "base261")),
    "nocap": ("champion · r5 lr3e-6 e3.00 no-cap", "sft",
              ("nocap", "nocap50b", "nocap261")),
}
SLICE_N = (("seen50", 50), ("held50", 50), ("rest261", 261))


def proxy_ids():
    """Task ids the official config flags proxy:true.

    These run with enable_proxy=False here, and that is NOT free: the 2026-08-08
    Proxy-49 experiment scored 11% (5/45) on exactly this subset against ~45%
    overall, with failures matching datacenter-IP bot-walls (Amazon, Delta,
    TripAdvisor), not model ability. Reachability is not the test -- a plain
    HEAD returns 200 for most of these hosts. So the 312 non-proxy tasks are
    the honest headline and the 49 are reported beside it, never merged in
    silently.
    """
    ids = set()
    for meta in (EVAL50_META, HELDOUT_META, REST261_META):
        try:
            m = json.load(open(meta, encoding="utf-8"))
        except Exception:
            continue
        for dom, tids in m.items():
            for tid in tids:
                try:
                    cfg = json.load(open(os.path.join(EVAL50_EXAMPLES, dom,
                                                      tid + ".json"),
                                         encoding="utf-8"))
                except Exception:
                    continue
                if cfg.get("proxy"):
                    ids.add(tid)
    return ids


def sft361(ev):
    by = {a["key"]: a for a in ev["arms"]}
    px = proxy_ids()
    models = []
    for key, (label, group, arm_keys) in SFT361.items():
        got, slices = {}, {}
        for (name, n), ak in zip(SLICE_N, arm_keys):
            a = by.get(ak)
            if a is None:                       # not run yet -- show the gap
                slices[name] = {"n": n, "scored": 0, "sum": 0.0, "passed": 0,
                                "arm": ak, "run": "", "modeldir": ""}
                continue
            t = a["tasks"]
            got.update(t)
            slices[name] = {"n": n, "scored": len(t),
                            "sum": round(sum(r["score"] or 0 for r in t.values()), 2),
                            "passed": sum(1 for r in t.values() if r["score"] == 1.0),
                            "arm": ak, "run": a["run"], "modeldir": a["modeldir"]}

        def agg(keep, n):
            sub = {k: v for k, v in got.items() if keep(k)}
            return {"n": n, "scored": len(sub),
                    "sum": round(sum(r["score"] or 0 for r in sub.values()), 2),
                    "passed": sum(1 for r in sub.values() if r["score"] == 1.0),
                    # rate is over the FIXED denominator (unscored == 0, the
                    # standing accounting policy); rate_now is over what has
                    # actually finished, which is what to read mid-run.
                    "rate": (round(sum(r["score"] or 0 for r in sub.values()) / n, 4)
                             if n else None),
                    "rate_now": (round(sum(r["score"] or 0 for r in sub.values())
                                       / len(sub), 4) if sub else None)}
        doms = {}
        for r in got.values():
            d = doms.setdefault(r["dom"], [0.0, 0])
            d[0] += r["score"] or 0
            d[1] += 1
        models.append({
            "key": key, "label": label, "group": group, "slices": slices,
            "complete": all(sl["scored"] == sl["n"] for sl in slices.values()),
            "all361": agg(lambda t: True, 361),
            "nonproxy": agg(lambda t: t not in px, 361 - len(px)),
            "proxy": agg(lambda t: t in px, len(px)),
            "domains": {k: [round(v[0], 2), v[1]] for k, v in sorted(doms.items())},
        })
    return {"proxy_n": len(px), "n": 361, "models": models}


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
    ev = eval50()
    out = {"updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M PT"),
           "panel": order, "panel_id": pid, "panel_n": len(pan),
           "arms": arms, "groups": GROUPS, "eval50": ev, "sft361": sft361(ev)}
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
