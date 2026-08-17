"""Per-checkpoint geometry probe — the offline instrumentation pass.

    python -m ostg.sft.ckptprobe OUT_DIR --base MODEL_DIR [--wandb NAME]

OUT_DIR is a training output dir holding checkpoint-N subdirs (N = global
step, swift convention). For every checkpoint, streaming over safetensors
(one tensor resident at a time — login-node safe, no GPU):

    param_norm        ||theta||
    delta_prev        ||theta_k - theta_{k-1}||   (first ckpt: vs --base)
    delta_base        ||theta_k - theta_base||    (total displacement)
    step_size         delta_prev / steps-in-interval
    update_weight     delta_prev / param_norm

Why: (a) the displacement-damage theory needs ||theta - theta_0|| measured,
not inferred; (b) the permanent-clipping question (TRAINING.md 2026-08-17)
is decided by step_size across arms with different clip factors — Adam's
rescale-invariance predicts near-equal step_size for gb64o (clip ~0.5) vs
3ep (clip ~0.2). Loss-channel probing (think/action CE) is v2: needs a GPU
forward; this file stays CPU-only on purpose.

Results print as JSON and, with --wandb NAME, backfill a run (x = step)
using $WANDB_API_KEY / wandb.env conventions.
"""
import argparse
import json
import math
import re
from pathlib import Path

from safetensors import safe_open


def tensor_files(d):
    fs = sorted(Path(d).glob("*.safetensors"))
    if not fs:
        raise SystemExit(f"no safetensors under {d}")
    return fs


def stream_norms(dir_a, dir_b=None):
    """Return (||A||^2, ||A-B||^2) accumulated tensor-by-tensor in fp32.

    B=None computes only the norm. Keys missing on either side are skipped
    with a warning (frozen towers are present in both, so this is rare).
    """
    import torch
    nn = dd = 0.0
    b_handles = {}
    if dir_b:
        for f in tensor_files(dir_b):
            h = safe_open(f, framework="pt")
            for k in h.keys():
                b_handles[k] = (h, k)
    # Chunked along dim 0: the embedding matrix alone is ~1.5 GB in fp32 and
    # a naive (t, ref, diff) triple peaked near 4.7 GB, which the login
    # node's cgroup killed. ROWS keeps peak in the hundreds of MB, so the
    # probe needs NO allocation at all -- it runs on the login node.
    ROWS = 4096
    for f in tensor_files(dir_a):
        h = safe_open(f, framework="pt")
        for k in h.keys():
            t0 = h.get_tensor(k)
            if not torch.is_floating_point(t0):
                continue
            hb = b_handles.get(k) if dir_b else None
            if dir_b and hb is None:
                print(f"WARN: {k} missing in reference")
            b0 = hb[0].get_tensor(hb[1]) if hb else None
            n = t0.shape[0] if t0.dim() else 1
            for i in range(0, max(n, 1), ROWS):
                a = (t0[i:i + ROWS] if t0.dim() else t0).float()
                nn += float((a * a).sum())
                if b0 is not None:
                    a -= (b0[i:i + ROWS] if b0.dim() else b0).float()
                    dd += float((a * a).sum())
                del a
    return nn, dd


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--base", type=Path, required=True,
                    help="the pre-SFT model dir (displacement origin)")
    ap.add_argument("--wandb", default=None, help="backfill run name")
    ap.add_argument("--json", dest="json_out", default=None)
    a = ap.parse_args(argv)

    cks = sorted((int(re.search(r"checkpoint-(\d+)$", str(p)).group(1)), p)
                 for p in a.out_dir.glob("checkpoint-*") if p.is_dir())
    if not cks:
        raise SystemExit(f"no checkpoints under {a.out_dir}")
    rows, prev = [], (0, a.base)
    for step, ck in cks:
        nn, dd_prev = stream_norms(ck, prev[1])
        _, dd_base = stream_norms(ck, a.base) if prev[1] != a.base else (0, dd_prev)
        interval = step - prev[0]
        row = dict(step=step,
                   param_norm=math.sqrt(nn),
                   delta_prev=math.sqrt(dd_prev),
                   delta_base=math.sqrt(dd_base),
                   step_size=math.sqrt(dd_prev) / max(1, interval),
                   update_weight=math.sqrt(dd_prev) / math.sqrt(nn))
        rows.append(row)
        print(json.dumps(row))
        prev = (step, ck)

    if a.json_out:
        Path(a.json_out).write_text(json.dumps(rows, indent=1))
    if a.wandb:
        import wandb
        run = wandb.init(project="cua-sft", name=a.wandb, reinit=True)
        for r in rows:
            run.log({f"probe/{k}": v for k, v in r.items() if k != "step"},
                    step=r["step"])
        run.finish()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
