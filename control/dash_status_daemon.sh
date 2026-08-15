#!/bin/bash
# Live dashboard updater -- ZERO-CONFIG pipeline (2026-08-15 rewrite).
#
# Discovery: every dir under results_generated/*/ that contains args.json is a
# run. Its tasks dir (for instructions/slugs) comes from args.json's own
# test_config_base_dir; its config columns from args.json + MODEL_BOUNDARY.json.
# A NEW CAMPAIGN NEEDS NO EDIT HERE: it appears in status.json's "runs" table
# on the next cycle and gets trajectory viewers once it has >= MIN_SCORED
# results. Until then the page shows it as not-yet-run.
#
# Perf fix carried in this rewrite: screenshots are immutable once written, so
# they sync with --ignore-existing. The old cycle re-copied and re-compressed
# every png every round (PIL changed the staged file, the next rsync saw a
# mismatch, forever): ~26 min/cycle doing nothing.
#
#   status.json                    -> every cycle (tiny; the page reads this)
#   traj/<modeldir>/<rundir>/      -> at most every 30 min, per discovered run
REPO=/mnt/d/research/cua-dash
P=/mnt/d/research/OSWorld/.venv/bin/python
BRANCH=main
RG=/mnt/d/research/OSWorld/results_generated
MIN_SCORED=10
export GIT_SSH_COMMAND="ssh -i ~/.ssh/id_ed25519_cua -o IdentitiesOnly=yes"
cd $REPO
set +e
git config user.email "jy050706@uw.edu"; git config user.name "dash-updater"
LAST_TRAJ=0
while true; do
  DID_TRAJ=0
  git rebase --abort 2>/dev/null; git merge --abort 2>/dev/null
  git checkout -q -- . 2>/dev/null
  git fetch -q --depth=1 origin $BRANCH 2>/dev/null && git reset -q --hard FETCH_HEAD
  $P - <<'PY'
import glob, json, os, collections, datetime
RG = "/mnt/d/research/OSWorld/results_generated"
REPO = "/mnt/d/research/cua-dash"
TG = "/mnt/d/research/os-simple-taskgen-v8"

def scores_of(rd):
    out = []
    for rt in glob.glob(rd + "/*/*/result.txt"):
        try: out.append((rt.split("/")[-3], float(open(rt).read().strip())))
        except Exception: pass
    return out

# ---- generic per-run rows: THE pipeline. args.json == a run. -----------------
runs = []
for aj in sorted(glob.glob(RG + "/*/*/args.json")):
    rd = os.path.dirname(aj)
    model_dir, run_dir = rd.split("/")[-2], rd.split("/")[-1]
    try: args = json.load(open(aj))
    except Exception: args = {}
    tasks = args.get("test_config_base_dir") or ""
    total = None
    try:
        total = sum(len(v) for v in json.load(open(tasks + "/manifest.json")).values())
    except Exception:
        pass
    mb = {}
    try: mb = json.load(open(rd + "/MODEL_BOUNDARY.json"))
    except Exception: pass
    sc = scores_of(rd)
    slug = "traj/%s/%s" % (model_dir, run_dir)
    runs.append({
        "model": mb.get("model") or model_dir,
        "batch": run_dir,
        "scored": len(sc), "total": total,
        "passed": sum(1 for _, s in sc if s == 1.0),
        "mean": round(sum(s for _, s in sc)/len(sc), 4) if sc else None,
        "max_steps": args.get("max_steps"),
        "temperature": (mb.get("sampling") or {}).get("temperature", args.get("temperature")),
        "sleep": args.get("sleep_after_execution"),
        "history_n": args.get("history_n"),
        "traj": slug + "/index.html",
        "traj_published": os.path.exists(os.path.join(REPO, "dashboard", slug, "index.html")),
    })

# ---- legacy blocks, kept verbatim so existing page sections still work ------
RUN = RG + "/qwen36-27b-bf16-local/v11-all-ms50-think-nopreserve-20260809"
band = collections.defaultdict(lambda: [0, 0]); tot = pas = 0
for dom, s in scores_of(RUN):
    ok = s == 1.0
    band[dom][1] += 1; band[dom][0] += ok; tot += 1; pas += ok
final = set()
try:
    for _p in glob.glob(TG + "/out/runs/v11-500-final/examples/*/*.json"):
        final.add(json.load(open(_p))["ostg"]["slug"])
except Exception:
    pass
verdict = {}
_files = (sorted(glob.glob(TG + "/out/runs/v500-all/control_report_*.jsonl"))
          + sorted(glob.glob(TG + "/out/runs/v11-500-recheck/report.jsonl"))
          + sorted(glob.glob(TG + "/out/runs/v11-500-recheck2/report.jsonl")))
for f in _files:
    for l in open(f):
        if not l.strip(): continue
        r = json.loads(l)
        verdict[r["slug"]] = bool(r.get("ok"))
ctl_done = sum(1 for s_ in final if s_ in verdict)
ctl_bad = sum(1 for s_ in final if verdict.get(s_) is False)
try:
    corpus = sum(len(v) for v in json.load(open(TG + "/out/runs/v11-500-final/manifest.json")).values())
except Exception:
    corpus = 0
r5_scored = r5_passed = 0
r5_band = collections.defaultdict(lambda: [0, 0])
for d in sorted(glob.glob(RG + "/qwen36-27b-bf16-local/v11-500-ms*")):
    for dom, s in scores_of(d):
        ok = s == 1.0
        r5_band[dom][1] += 1; r5_band[dom][0] += ok
        r5_scored += 1; r5_passed += ok
q38 = {}
for d in sorted(glob.glob(RG + "/qwen38-27b-local/*")):
    if not os.path.isdir(d): continue
    band38 = collections.defaultdict(lambda: [0, 0]); sc38 = ps38 = 0
    for dom, s in scores_of(d):
        ok = s == 1.0
        band38[dom][1] += 1; band38[dom][0] += ok; sc38 += 1; ps38 += ok
    if sc38:
        q38[os.path.basename(d)] = {"scored": sc38, "passed": ps38,
                                    "domains": {k: v for k, v in sorted(band38.items())}}

out = {"updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M PT"),
       "runs": runs,
       "qwen38": q38,
       "v11": {"scored": tot, "total": 100, "passed": pas,
               "domains": {d: v for d, v in sorted(band.items())}},
       "v11_500": {"corpus": corpus, "control_checked": ctl_done, "control_bad": ctl_bad,
                  "scored": r5_scored, "passed": r5_passed,
                  "domains": {d: v for d, v in sorted(r5_band.items())}}}
p = REPO + "/dashboard/status.json"
old = {}
try: old = json.load(open(p))
except Exception: pass
if all(old.get(k) == out[k] for k in ("v11", "v11_500", "qwen38", "runs")):
    raise SystemExit(3)
json.dump(out, open(p, "w"), indent=1)
PY
  if [ "$?" = "0" ]; then
    NOW=$(date +%s)
    if [ $((NOW - LAST_TRAJ)) -ge 1800 ]; then
      for AJ in "$RG"/*/*/args.json; do
        SRC=$(dirname "$AJ")
        N=$(find "$SRC" -name result.txt 2>/dev/null | wc -l)
        [ "$N" -ge "$MIN_SCORED" ] || continue
        # viewers only for runs still moving (any result in the last 3 days);
        # finished old runs stay listed in status.json as not-yet-published
        [ -n "$(find "$SRC" -name result.txt -newermt '-3 days' 2>/dev/null | head -1)" ] || continue
        SLUG=$(basename "$(dirname "$SRC")")/$(basename "$SRC")
        TASKS=$($P -c "import json;print(json.load(open('$AJ')).get('test_config_base_dir') or '')" 2>/dev/null)
        STG=/tmp/trajpub/$SLUG
        mkdir -p "$STG"
        # screenshots are immutable once written: never re-copy one we already
        # compressed (this was the 26-min/cycle bug)
        rsync -a --ignore-existing --include='*/' --include='*.png' \
              --exclude='*' "$SRC/" "$STG/" 2>/dev/null
        rsync -a --exclude='*.mp4' --exclude='*.png' --exclude='runtime.log' \
              --exclude='viewer.html' --exclude='index.html' \
              "$SRC/" "$STG/" 2>/dev/null
        if [ -n "$TASKS" ] && [ -d "$TASKS" ]; then
          ( cd /mnt/d/research/ostg-v11.1 && PYTHONPATH=. $P -m ostg.traj_html "$STG" \
              --tasks "$TASKS" >/dev/null 2>&1 )
        else
          ( cd /mnt/d/research/ostg-v11.1 && PYTHONPATH=. $P -m ostg.traj_html "$STG" >/dev/null 2>&1 )
        fi
        STG="$STG" $P - <<'PY'
import glob, os
from PIL import Image
for p in glob.glob(os.environ["STG"] + "/**/*.png", recursive=True):
    if os.path.getsize(p) < 120000: continue
    try:
        im = Image.open(p).convert("RGB")
        if im.width > 1100: im = im.resize((1100, int(im.height*1100/im.width)))
        im.save(p, "JPEG", quality=32, optimize=True)
    except Exception: pass
PY
        mkdir -p "$REPO/dashboard/traj/$SLUG"
        rsync -a --delete "$STG/" "$REPO/dashboard/traj/$SLUG/"
        git add -A "dashboard/traj/$SLUG"
        echo "[$(date +%H:%M)] traj $SLUG: $(find "$STG" -name viewer.html | wc -l) viewers"
      done
      DID_TRAJ=1
    fi
    git add dashboard/status.json
    if git commit -q -m "status: auto-refresh"; then
      git pull --rebase -q origin $BRANCH >/dev/null 2>&1 || git rebase --abort >/dev/null 2>&1
      if git push -q origin HEAD:$BRANCH; then
        [ "$DID_TRAJ" = "1" ] && LAST_TRAJ=$NOW
        echo "[$(date +%H:%M)] pushed"
      else
        git reset -q --soft HEAD~1
        echo "[$(date +%H:%M)] push failed, will retry"
      fi
    fi
  fi
  sleep 300
done
