#!/usr/bin/env python3
"""Select the true multi-app trajectories from the judge-admitted v16 corpora
(mix-v16-main + mix-v16-pilot, the 554 used by mixA/B/C) and write a subset corpus.

true multi-app := task JSON related_apps, minus {os, files, terminal, ...}, has >= 2 apps.
Rows are matched to tasks by the images dir name '<slug>-<id8>' (same rule as
FAILURE_ANATOMY §12). Output: OUT/train_swift.jsonl + train_swift_abs.jsonl (+ ids.jsonl).
Usage: build_truemulti_subset.py OUT_DIR
"""
import json, glob, os, sys, collections, hashlib
V="/mnt/d/research/ostg-v16"
NONAPP={"os","files","terminal","file_manager","nautilus","shell","bash","system"}
runs={"mix-v16-main":("v16-main-1",f"{V}/out/runs/v16-main-1"),"mix-v16-pilot":("v16-pilot-200",f"{V}/out/runs/v16-pilot-200")}
def real(apps): return {a for a in apps if a not in NONAPP}
out=sys.argv[1]; os.makedirs(out,exist_ok=True)
tasks={}
for corp,(run,td) in runs.items():
    for p in glob.glob(f"{td}/examples/*/*.json"):
        t=json.load(open(p)); tid=t.get("id") or os.path.basename(p)[:-5]
        tasks[(run,tid)]=(os.path.basename(os.path.dirname(p)), real(t.get("related_apps") or []))
kept=collections.Counter(); rows_out={"train_swift.jsonl":[],"train_swift_abs.jsonl":[]}; ids=[]; seen=set()
for corp,(run,td) in runs.items():
    for fn in rows_out:
        for line in open(f"{V}/out/sft/{corp}/{fn}",encoding="utf-8"):
            o=json.loads(line); im=(o.get("images") or [""])[0]
            id8=os.path.basename(os.path.dirname(im)).rsplit("-",1)[-1] if im else ""
            hits=[k for k in tasks if k[0]==run and k[1].startswith(id8)]
            if len(hits)!=1: continue
            dom,apps=tasks[hits[0]]
            if len(apps)<2: continue
            rows_out[fn].append(line.rstrip("\n"))
            if fn=="train_swift.jsonl":
                kept[corp]+=1
                if hits[0] not in seen: seen.add(hits[0]); ids.append({"run":run,"domain":dom,"task_id":hits[0][1],"apps":sorted(apps)})
for fn,rows in rows_out.items(): open(f"{out}/{fn}","w",encoding="utf-8").write("\n".join(rows)+"\n")
open(f"{out}/ids.jsonl","w").write("".join(json.dumps(x)+"\n" for x in ids))
combos=collections.Counter(" + ".join(x["apps"]) for x in ids)
rep={"trajectories":len(ids),"samples":sum(kept.values()),"samples_by_source":dict(kept),"combos":len(combos),"top_combos":combos.most_common(8),
     "rule":"related_apps minus os/files/terminal has >=2 apps; source corpora mix-v16-main + mix-v16-pilot (judge-admitted 554)",
     "script_sha256":hashlib.sha256(open(__file__,"rb").read()).hexdigest()[:12]}
json.dump(rep,open(f"{out}/report.json","w"),indent=1,ensure_ascii=False); print(json.dumps(rep,ensure_ascii=False,indent=1))
