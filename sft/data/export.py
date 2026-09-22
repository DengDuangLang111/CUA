"""Convert samples.jsonl to a training framework's dialect.

    python -m ostg.sft.data.export SAMPLES_DIR --dialect swift

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

if __package__:
    from .to_swift import convert
else:  # Preserve direct script invocation as well as python -m.
    from to_swift import convert


def to_swift(sample):
    """Legacy adapter: retain structured-input semantics and explicit defaults."""
    normalized = {**sample, "messages": [
        {"role": message["role"], "content": list(message["content"])}
        for message in sample["messages"]
    ]}
    row = convert(normalized)
    return {"messages": row["messages"], "images": row.get("images", []),
            "channel": row.get("channel", "unknown")}


DIALECTS = {"swift": to_swift}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("samples_dir", type=Path)
    ap.add_argument("--dialect", choices=sorted(DIALECTS), required=True)
    args = ap.parse_args(argv)

    conv = DIALECTS[args.dialect]
    for src_name, dst_name in (("samples.jsonl", "train_%s.jsonl"),
                               ("val_samples.jsonl", "val_%s.jsonl")):
        src = args.samples_dir / src_name
        if not src.is_file():
            continue
        dst = args.samples_dir / (dst_name % args.dialect)
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
