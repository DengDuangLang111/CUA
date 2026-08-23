#!/usr/bin/env python3
"""think_degen.py -- is a long think block reasoning, or is it stuck?

Written 2026-08-23 after noticing that SFT lowers the MEDIAN think length
toward the teacher's while raising the MAXIMUM far past it: the 9B base never
exceeds 3,687 characters, its SFT version reaches 93,591, and the 4B's reaches
528,326 against a teacher maximum of 25,924. A single run-of-one-word test
found only one case, which is too blunt -- degeneration usually repeats
PHRASES, not words.

Uses rep-4: the share of 4-grams in a text that are not distinct. Fluent prose
sits near 0.1-0.3; a stuck generation runs to 0.8+. Reported against the
corpus's own teacher thinks, because the question is not "is this text
repetitive" but "is it more repetitive than what the model was trained on".

Usage (WSL):
  python3 think_degen.py --arm LABEL RESULT_DIR... [--corpus JSONL]
"""
import argparse, glob, json, os, re

THINK = re.compile(r"<think>([\s\S]*?)</think>")


def rep4(text):
    w = text.split()
    if len(w) < 8:
        return 0.0
    grams = [" ".join(w[i:i+4]) for i in range(len(w) - 3)]
    return 1.0 - len(set(grams)) / len(grams)


def buckets(vals):
    if not vals:
        return "-"
    v = sorted(vals)
    q = lambda p: v[min(len(v) - 1, int(p * len(v)))]
    return "p50 %.2f p90 %.2f p99 %.2f max %.2f" % (q(.5), q(.9), q(.99), v[-1])


def arm_thinks(dirs):
    out = []
    for d in dirs:
        ds = sorted(glob.glob(d))
        if not ds:
            continue
        for td in glob.glob(os.path.join(ds[-1], "*", "*")):
            tj = os.path.join(td, "traj.jsonl")
            if not os.path.exists(tj):
                continue
            seen = {}
            for line in open(tj, encoding="utf-8", errors="replace"):
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                sn = r.get("step_num")
                if sn is None or sn in seen:
                    continue
                seen[sn] = r.get("response") or ""
            for resp in seen.values():
                m = THINK.search(resp)
                if m:
                    out.append(m.group(1))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", nargs="+", action="append", required=True,
                    metavar="LABEL DIR...")
    ap.add_argument("--corpus", default="/gpfs/scrubbed/jy050706/sft/data/"
                                        "q38-Bhqs2t-r5nocapimg10-v11500/train_swift.jsonl",
                    help="reference: the teacher thinks the students learned from")
    ap.add_argument("--long", type=int, default=20000,
                    help="characters above which a think counts as long")
    a = ap.parse_args()

    ref = []
    if os.path.exists(a.corpus):
        for line in open(a.corpus, encoding="utf-8", errors="replace"):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            for msg in r.get("messages", []):
                if msg.get("role") == "assistant":
                    m = THINK.search(str(msg.get("content", "")))
                    if m:
                        ref.append(m.group(1))
    if ref:
        L = sorted(len(t) for t in ref)
        print("语料里教师的 think(%d 段): 长度 p50 %d p99 %d max %d | rep4 %s"
              % (len(ref), L[len(L)//2], L[int(.99*len(L))], L[-1],
                 buckets([rep4(t) for t in ref[:3000]])))
        print("   语料中超过 %d 字符的: %d 段 (%.2f%%)\n"
              % (a.long, sum(1 for t in ref if len(t) > a.long),
                 100*sum(1 for t in ref if len(t) > a.long)/len(ref)))

    for spec in a.arm:
        label, dirs = spec[0], spec[1:]
        th = arm_thinks(dirs)
        if not th:
            continue
        L = sorted(len(t) for t in th)
        longs = [t for t in th if len(t) > a.long]
        shorts = [t for t in th if len(t) <= 2000]
        print("=== %s (%d 步)" % (label, len(th)))
        print("   长度 p50 %d p99 %d max %d | 超长(>%dk) %d 段 (%.2f%%)"
              % (L[len(L)//2], L[int(.99*len(L))], L[-1], a.long//1000,
                 len(longs), 100*len(longs)/len(th)))
        print("   rep4 短 think(<2k): %s" % buckets([rep4(t) for t in shorts[:2000]]))
        if longs:
            rl = [rep4(t) for t in longs]
            print("   rep4 超长 think:  %s" % buckets(rl))
            print("   超长里 rep4>0.5(明显卡住)的: %d/%d"
                  % (sum(1 for x in rl if x > 0.5), len(rl)))


if __name__ == "__main__":
    main()
