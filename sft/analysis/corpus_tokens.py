#!/usr/bin/env python3
"""corpus_tokens.py -- token/length distribution of SFT corpora, split into the
three parts that actually drive sequence length: think, non-think text, images.

Why the split: for a VL corpus the image budget (IMAGE_MAX_TOKEN_NUM per image
x image count) can dominate everything else, so a single "sample length" number
hides which knob is doing the work. The think column is what --think-cap moves;
the prose column is what strip_prose moves.

Text is tokenized with the model's real tokenizer. Image tokens are NOT
tokenized (they are injected at encode time); they are estimated as
n_images * IMAGE_TOKENS and reported separately, never mixed into the text
column. Both are summed for the max_length comparison, which is the number
that decides whether truncation_strategy=delete drops the sample.

Usage:
  python3 corpus_tokens.py --tokenizer /path/to/model \
      NAME=/path/to/train_swift.jsonl [NAME=... ...] [--image-tokens 2048]
"""
import argparse, json, re, statistics as st, sys

THINK = re.compile(r"<think>[\s\S]*?</think>")

def pct(xs, p):
    if not xs: return 0
    xs = sorted(xs)
    k = min(len(xs) - 1, int(round(p / 100.0 * (len(xs) - 1))))
    return xs[k]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tokenizer", required=True)
    ap.add_argument("--image-tokens", type=int, default=2048)
    ap.add_argument("--max-length", type=int, nargs="+", default=[65536, 81920])
    ap.add_argument("corpora", nargs="+", help="NAME=/path/to/train_swift.jsonl")
    a = ap.parse_args()

    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.tokenizer, trust_remote_code=True)

    for spec in a.corpora:
        name, path = spec.split("=", 1)
        think_t, prose_t, text_t, imgs, total = [], [], [], [], []
        rows = 0
        for line in open(path, encoding="utf-8"):
            if not line.strip(): continue
            row = json.loads(line)
            msgs = row["messages"]
            # whole-sample text = every message; think measured on the TARGET
            # (last assistant) turn, which is the only turn loss_scale=last_round
            # actually trains.
            whole = "".join(m.get("content") or "" for m in msgs)
            asst = [m for m in msgs if m["role"] == "assistant"]
            tgt = asst[-1]["content"] if asst else ""
            m = THINK.search(tgt)
            th = m.group(0) if m else ""
            rest = tgt.replace(th, "") if th else tgt
            n_img = len(row.get("images") or [])
            tt = len(tok(whole, add_special_tokens=False)["input_ids"])
            think_t.append(len(tok(th, add_special_tokens=False)["input_ids"]) if th else 0)
            prose_t.append(len(tok(rest, add_special_tokens=False)["input_ids"]))
            text_t.append(tt)
            imgs.append(n_img)
            total.append(tt + n_img * a.image_tokens)
            rows += 1
        print(f"\n=== {name}  ({rows} samples)")
        def line(label, xs):
            print(f"  {label:22s} median={pct(xs,50):7d}  p90={pct(xs,90):7d}  "
                  f"p99={pct(xs,99):7d}  max={max(xs):7d}  mean={int(st.mean(xs)):7d}")
        line("目标轮 think tok", think_t)
        line("目标轮 其余 tok", prose_t)
        line("全样本 文本 tok", text_t)
        line("图片张数", imgs)
        line("估计总长 tok", total)
        print(f"  图片 token 占比(中位样本): "
              f"{100.0*pct(imgs,50)*a.image_tokens/max(1,pct(total,50)):.1f}%")
        for ml in a.max_length:
            over = sum(1 for t in total if t > ml)
            print(f"  超过 max_length {ml}: {over} 条 ({100.0*over/max(1,rows):.2f}%)")

if __name__ == "__main__":
    main()
