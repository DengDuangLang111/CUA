#!/usr/bin/env python3
"""eval_emit_compare.py -- what two arms actually EMIT at eval time, and what
accumulates in their context, task-paired.

Built 2026-08-21 to dissect the prose axis after nocapnp closed it with a
uniform -4..-6pp against the champion: the mechanism question is whether
teacher-style narration between </think> and <tool_call> acts as working
memory. The rendered history keeps EVERY prose segment but only the LAST
think block (verified against real payloads), so an arm that stops emitting
prose is an arm whose past steps go silent -- measuring emission therefore
measures memory.

Counting rules that earlier bit us, baked in:
  - a step spans one traj line PER ACTION, each repeating the same response:
    think/prose are counted once per step_num, never per line
  - the ending is classified from the LAST line's action field, not from file
    counts (tasks used to be called DONE at step 50 by the old method)
  - lengths are CHARACTERS, the unit used by every earlier think-length table

Per arm: think and prose length distributions, share of steps with zero
prose, cumulative prose entering the final step's context, steps per task,
actions per step, repeated-action steps, ending modes, false successes.
Paired: tasks one arm solved and the other did not, bucketed by step count.

Usage (WSL):
  python3 eval_emit_compare.py \
      --arm nocap  DIR_SEEN DIR_HELD \
      --arm nocapnp DIR_100 \
      [--panel-seen verified_eval50_nonproxy.json]
"""
import argparse, glob, json, os, re
from collections import Counter

THINK = re.compile(r"<think>([\s\S]*?)</think>")
TOOL = re.compile(r"<tool_call>[\s\S]*?(?:</tool_call>|$)")


def pct(xs, q):
    if not xs:
        return 0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def read_arm(dirs):
    tasks = {}
    for d in dirs:
        for td in glob.glob(os.path.join(d, "*", "*")):
            rt = os.path.join(td, "result.txt")
            tj = os.path.join(td, "traj.jsonl")
            if not (os.path.exists(rt) and os.path.exists(tj)):
                continue
            try:
                score = float(open(rt).read().split()[0])
            except Exception:
                continue
            steps = {}
            order = []
            for line in open(tj, encoding="utf-8", errors="replace"):
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                sn = r.get("step_num")
                if sn is None:
                    continue
                steps.setdefault(sn, {"resp": r.get("response") or "",
                                      "actions": []})
                a = r.get("action")
                if a is not None:
                    steps[sn]["actions"].append(str(a))
                order.append(sn)
            if not steps:
                continue
            last = steps[order[-1]]
            last_act = (last["actions"][-1] if last["actions"] else "").strip()
            tasks[os.path.basename(td)] = {
                "score": score, "steps": steps, "last_act": last_act}
    return tasks


def arm_stats(tasks):
    th, pr, zero_pr, per_task_prose, nsteps, acts, dup = [], [], 0, [], [], 0, 0
    endings = Counter()
    false_succ = real_succ = 0
    tot_steps = 0
    for t in tasks.values():
        cum = 0
        for sn, s in t["steps"].items():
            resp = s["resp"]
            m = THINK.search(resp)
            think = m.group(1) if m else ""
            tail = resp[m.end():] if m else resp
            prose = TOOL.sub("", tail).strip()
            th.append(len(think))
            pr.append(len(prose))
            cum += len(prose)
            if not prose:
                zero_pr += 1
            tot_steps += 1
            acts += len(s["actions"])
            if len(s["actions"]) > 1 and len(set(s["actions"])) < len(s["actions"]):
                dup += 1
        per_task_prose.append(cum)
        nsteps.append(len(t["steps"]))
        la = t["last_act"]
        if la == "DONE":
            endings["DONE"] += 1
            if t["score"] >= 0.5:
                real_succ += 1
            else:
                false_succ += 1
        elif la == "FAIL":
            endings["FAIL"] += 1
        elif len(t["steps"]) >= 50:
            endings["撞上限"] += 1
        else:
            endings["其他/中断"] += 1
    n = max(len(tasks), 1)
    return {
        "任务数": len(tasks),
        "think字符 p50/p90/p99/max": "%d / %d / %d / %d" % (
            pct(th, .5), pct(th, .9), pct(th, .99), max(th or [0])),
        "散文字符 p50/p90/max": "%d / %d / %d" % (
            pct(pr, .5), pct(pr, .9), max(pr or [0])),
        "零散文步占比": "%.1f%%" % (100 * zero_pr / max(tot_steps, 1)),
        "每步平均散文字符": "%.0f" % (sum(pr) / max(tot_steps, 1)),
        "末步上下文累计散文(均值字符)": "%.0f" % (
            sum(per_task_prose) / n),
        "步数 均值/中位": "%.1f / %d" % (sum(nsteps) / n, pct(nsteps, .5)),
        "动作/步": "%.2f" % (acts / max(tot_steps, 1)),
        "含重复动作的步": dup,
        "收尾": dict(endings),
        "真成功/假报成功": "%d / %d (假报率 %.0f%%)" % (
            real_succ, false_succ,
            100 * false_succ / max(real_succ + false_succ, 1)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", nargs="+", action="append", required=True,
                    metavar="LABEL DIR...", help="label then result dirs")
    ap.add_argument("--panel-seen", default="/mnt/d/research/OSWorld/"
                    "evaluation_examples/verified_eval50_nonproxy.json")
    a = ap.parse_args()

    arms = {}
    for spec in a.arm:
        label, dirs = spec[0], spec[1:]
        arms[label] = read_arm(dirs)
        print(f"\n===== {label}  ({', '.join(os.path.basename(d) for d in dirs)})")
        for k, v in arm_stats(arms[label]).items():
            print(f"   {k}: {v}")

    if len(arms) == 2:
        (la, ta), (lb, tb) = arms.items()
        seen = {t for ts in json.load(open(a.panel_seen)).values() for t in ts}
        common = set(ta) & set(tb)
        flips_a = [t for t in common
                   if ta[t]["score"] >= 0.5 > tb[t]["score"]]
        flips_b = [t for t in common
                   if tb[t]["score"] >= 0.5 > ta[t]["score"]]
        print(f"\n===== 配对({len(common)} 题共有)")
        for label, flips, src in ((f"{la}✓ {lb}✗", flips_a, ta),
                                  (f"{lb}✓ {la}✗", flips_b, tb)):
            steps = [len(src[t]["steps"]) for t in flips]
            half = sum(1 for t in flips if t in seen)
            print(f"   {label}: {len(flips)} 题(已见半 {half})"
                  f"  赢家步数 均值 {sum(steps)/max(len(steps),1):.1f}"
                  f"  其中≥20步 {sum(1 for s in steps if s >= 20)} 题")
            long_side = sorted(flips, key=lambda t: -len(src[t]["steps"]))[:6]
            for t in long_side:
                print(f"      {t[:16]}…  {len(src[t]['steps'])} 步")


if __name__ == "__main__":
    main()
