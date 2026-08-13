"""Convert samples.jsonl to a training framework's dialect.

    python -m ostg.sft.export SAMPLES_DIR --dialect swift

Reads SAMPLES_DIR/samples.jsonl (the neutral format build.py emits) and
writes SAMPLES_DIR/train_<dialect>.jsonl next to it, so relative image
paths keep resolving. Conversion is mechanical on purpose: every decision
about content was made in build.py; this file only reshapes.

swift dialect (ms-swift multimodal SFT):
    {"messages": [{"role": ..., "content": "text with <image> markers"}...,
                  {"role": "assistant", "content": <target>}],
     "images": [path, ...]}         # one path per <image>, in order
Train with loss on the final round only (the sample's whole point --
history assistant turns are context, not labels); in ms-swift that is the
last-round loss setting, verify the flag name against the installed version.
"""
import argparse
import json
from pathlib import Path


def to_swift(sample):
    msgs, images = [], []
    for m in sample["messages"]:
        text = ""
        for p in m["content"]:
            if p.get("type") == "image":
                images.append(p["path"])
                text += "<image>"
            else:
                text += p.get("text", "")
        msgs.append({"role": m["role"], "content": text})
    msgs.append({"role": "assistant", "content": sample["response"]})
    return {"messages": msgs, "images": images}


DIALECTS = {"swift": to_swift}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("samples_dir", type=Path)
    ap.add_argument("--dialect", choices=sorted(DIALECTS), required=True)
    args = ap.parse_args(argv)

    conv = DIALECTS[args.dialect]
    src = args.samples_dir / "samples.jsonl"
    dst = args.samples_dir / ("train_%s.jsonl" % args.dialect)
    n = 0
    with src.open(encoding="utf-8") as fin, dst.open("w", encoding="utf-8") as fout:
        for line in fin:
            if line.strip():
                fout.write(json.dumps(conv(json.loads(line)), ensure_ascii=False) + "\n")
                n += 1
    print("%d sample(s) -> %s" % (n, dst))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
