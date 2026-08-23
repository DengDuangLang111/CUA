#!/usr/bin/env python3
"""action_acc.py -- offline action accuracy on the held-out split.

Why this exists: the validation loss we already log is token-level cross
entropy, and 97.8% of its mass sits on think tokens (measured 2026-08-22:
tool_call is 16% of tokens but 2.2% of loss). So it mostly scores how well the
model imitates the teacher's PROSE, not whether it picks the right action --
and the two demonstrably diverge here, with a6v sitting at the minimum of its
own validation curve while scoring sixteen tasks below an arm that trained
longer. Suggested by Zixian Ma.

What it measures, per held-out sample, by asking the model for the next move
and comparing to what the teacher actually did:

  produced      did a parsable tool_call appear at all
  action        same action type (left_click / type / key / terminate / ...)
  exact         same action AND same parameters
  click_px      for click actions with both coordinates, the pixel distance
                after mapping the 0-1000 output frame onto 1920x1080
  terminate     confusion on the one action that decides the false-DONE rate

Greedy by default: this is a measurement, and eval-time sampling (t=1.0) adds
variance a 261-sample split cannot absorb. Pass --temperature to match eval
instead. Costs one forward pass per sample -- minutes, no VM -- against the
4.5 hours and three VMs a task eval needs.

Usage (on Tillicum, against a live serve):
  python3 action_acc.py --port 8052 --model img10-9bh-stock \
      --val .../val_swift.jsonl [--limit N] [--temperature 0]
"""
import argparse, base64, json, os, re, sys, urllib.request

TOOL = re.compile(r"<tool_call>([\s\S]*?)(?:</tool_call>|$)")
PARAM = re.compile(r"<parameter=([a-zA-Z_]+)>\s*([\s\S]*?)\s*</parameter>")


def parse_call(text):
    """{param: value} of the first tool_call, or None."""
    m = TOOL.search(text or "")
    if not m:
        return None
    d = {k: v.strip() for k, v in PARAM.findall(m.group(1))}
    return d or None


def coord(v):
    try:
        xy = json.loads(v)
        if isinstance(xy, list) and len(xy) == 2:
            return float(xy[0]), float(xy[1])
    except Exception:
        pass
    return None


def to_openai(messages, images):
    """swift format (<image> placeholders + a parallel images list) -> chat parts."""
    out, idx = [], 0
    for m in messages:
        c = str(m.get("content", ""))
        if "<image>" not in c:
            out.append({"role": m["role"], "content": c})
            continue
        parts, rest = [], c
        while "<image>" in rest and idx < len(images):
            head, rest = rest.split("<image>", 1)
            if head:
                parts.append({"type": "text", "text": head})
            with open(images[idx], "rb") as fh:
                b = base64.b64encode(fh.read()).decode()
            parts.append({"type": "image_url",
                          "image_url": {"url": "data:image/png;base64," + b}})
            idx += 1
        if rest:
            parts.append({"type": "text", "text": rest})
        out.append({"role": m["role"], "content": parts})
    return out


def ask(port, model, msgs, temp, max_tokens, key):
    body = json.dumps({"model": model, "messages": msgs, "temperature": temp,
                       "top_p": 0.95 if temp > 0 else 1.0,
                       "max_tokens": max_tokens}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:%d/v1/chat/completions" % port, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--val", action="append", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--key", default=os.environ.get("OPENAI_API_KEY", "EMPTY"))
    ap.add_argument("--dump", default=None, help="write per-sample rows as jsonl")
    a = ap.parse_args()

    rows = []
    for f in a.val:
        for line in open(f, encoding="utf-8"):
            if line.strip():
                rows.append(json.loads(line))
    if a.limit:
        rows = rows[:a.limit]

    n = produced = act_ok = exact_ok = 0
    dists, term = [], {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    dump = open(a.dump, "w", encoding="utf-8") if a.dump else None
    for i, r in enumerate(rows):
        ms = r["messages"]
        tgt = parse_call(ms[-1].get("content", ""))
        if tgt is None:            # teacher turn without a tool call: nothing to score
            continue
        try:
            pred_text = ask(a.port, a.model, to_openai(ms[:-1], r.get("images") or []),
                            a.temperature, a.max_tokens, a.key)
        except Exception as e:
            print("  sample %d failed: %s" % (i, str(e)[:120]), file=sys.stderr)
            continue
        n += 1
        pred = parse_call(pred_text)
        if pred:
            produced += 1
            same_act = pred.get("action") == tgt.get("action")
            act_ok += same_act
            exact_ok += (pred == tgt)
            if same_act and "click" in (tgt.get("action") or ""):
                pc, tc = coord(pred.get("coordinate", "")), coord(tgt.get("coordinate", ""))
                if pc and tc:
                    dx = (pc[0] - tc[0]) / 1000 * 1920
                    dy = (pc[1] - tc[1]) / 1000 * 1080
                    dists.append((dx * dx + dy * dy) ** 0.5)
        pt = (pred or {}).get("action") == "terminate"
        tt = tgt.get("action") == "terminate"
        term["tp" if (pt and tt) else "fp" if pt else "fn" if tt else "tn"] += 1
        if dump:
            dump.write(json.dumps({"i": i, "target": tgt, "pred": pred},
                                  ensure_ascii=False) + "\n")
        if n % 25 == 0:
            print("  ... %d/%d" % (n, len(rows)), file=sys.stderr)
    if dump:
        dump.close()

    pct = lambda x: 100.0 * x / max(n, 1)
    print("\n=== %s  (n=%d, temperature=%.1f)" % (a.model, n, a.temperature))
    print("  产出 tool_call     %5.1f%%  (%d)" % (pct(produced), produced))
    print("  动作类型正确       %5.1f%%  (%d)" % (pct(act_ok), act_ok))
    print("  参数完全一致       %5.1f%%  (%d)" % (pct(exact_ok), exact_ok))
    if dists:
        d = sorted(dists)
        print("  点击像素误差       中位 %.0f px  p90 %.0f px  (n=%d, 1920x1080)"
              % (d[len(d)//2], d[int(.9*len(d))], len(d)))
    tp, fp, fn = term["tp"], term["fp"], term["fn"]
    print("  terminate          该终止未终止 %d | 不该终止却终止 %d | 都对 %d"
          % (fn, fp, tp))


if __name__ == "__main__":
    main()
