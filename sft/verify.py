"""Post-build integrity gate: every image referenced by every sample must
exist and be non-empty. Run by sft/pipeline.sh after every build; also fine
standalone:

    python -m ostg.sft.verify OUT_DIR

Exit 0 = clean. Exit 1 = at least one broken reference, all of them listed.
This is the check the training-data rule demands (row counts lie; prove the
media resolves BEFORE training), promoted from an ad-hoc audit script into the
pipeline so nobody has to re-invent it per run.
"""
import json
import os
import sys


def verify(out_dir):
    bad = []
    samples = refs = 0
    for name in ("samples.jsonl", "val_samples.jsonl"):
        p = os.path.join(out_dir, name)
        if not os.path.exists(p):
            continue
        for line in open(p, encoding="utf-8"):
            if not line.strip():
                continue
            s = json.loads(line)
            samples += 1
            for m in s.get("messages", []):
                c = m.get("content")
                if not isinstance(c, list):
                    continue
                for part in c:
                    if part.get("type") != "image":
                        continue
                    refs += 1
                    ip = os.path.join(out_dir, part["path"])
                    if not (os.path.exists(ip) and os.path.getsize(ip) > 0):
                        bad.append((name, s.get("slug", "?"), part["path"]))
    print("verify: %d samples, %d image refs, %d missing-or-empty"
          % (samples, refs, len(bad)))
    for name, slug, path in bad[:50]:
        print("  BAD %s %s -> %s" % (name, slug, path))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(verify(sys.argv[1]))
