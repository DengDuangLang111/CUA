"""samples.jsonl -> ms-swift training format.

    python -m ostg.sft.to_swift OUT_DIR

Writes OUT_DIR/train_swift.jsonl (and val_swift.jsonl when val samples
exist): swift wants flat string contents with an `<image>` placeholder per
picture plus a parallel `images` list, where our build emits structured
content parts. The final assistant turn (the loss target) is appended from
`response`.

Fixed as a module 2026-08-17: the arm-A/B ships did this with an ad-hoc
one-liner, which is exactly what the pipeline rule forbids (data-generating
code must be in git before it runs, with its hash in the log). Validated by
regenerating a prior dataset and diffing byte-for-byte.
"""
import json
import sys
from pathlib import Path


def flatten(content):
    """Structured parts -> (text, [image paths]) with <image> placeholders."""
    if not isinstance(content, list):
        return str(content), []
    out, imgs = [], []
    for part in content:
        if part.get("type") == "image":
            out.append("<image>")
            imgs.append(part["path"])
        else:
            out.append(part.get("text", ""))
    return "".join(out), imgs


def convert(sample):
    msgs, images = [], []
    for m in sample.get("messages", []):
        text, imgs = flatten(m.get("content"))
        msgs.append({"role": m["role"], "content": text})
        images.extend(imgs)
    msgs.append({"role": "assistant", "content": sample["response"]})
    row = {"messages": msgs}
    if images:
        row["images"] = images
    ch = (sample.get("meta") or {}).get("domain")
    if ch:
        row["channel"] = ch
    return row


def main(argv=None):
    argv = argv or sys.argv[1:]
    if len(argv) != 1:
        print(__doc__)
        return 2
    out = Path(argv[0])
    for src, dst in (("samples.jsonl", "train_swift.jsonl"),
                     ("val_samples.jsonl", "val_swift.jsonl")):
        p = out / src
        if not p.is_file():
            continue
        n = 0
        with (out / dst).open("w", encoding="utf-8") as f:
            for line in p.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                f.write(json.dumps(convert(json.loads(line)),
                                   ensure_ascii=False) + "\n")
                n += 1
        print("to_swift: %s -> %s (%d rows)" % (src, dst, n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
