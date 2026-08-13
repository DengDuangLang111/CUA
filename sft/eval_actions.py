"""Generation-based action metrics on a fixed val panel.

    python -m ostg.sft.eval_actions CKPT_DIR SAMPLES_DIR \
        [--limit 50] [--wandb-project cua-sft] [--run-name eval-...]

Loss cannot see whether the student clicks the right THING; this can. For
each val sample: generate from the rendered context, parse the action, and
compare against the teacher's response on three axes that matter for a CUA:

  action_type_acc   tool-call name matches (click vs type vs scroll ...)
  coord_mae         mean |dx|+|dy| in the 0-999 space, over samples where
                    both sides produced coordinates for the same action type
  think_len_ratio   student <think> length / teacher's -- collapse detector

Also logs a wandb Table (teacher vs student, per sample) for eyeballing.
Runs on one GPU; a 4B in bf16 needs ~10 GiB.
"""
import argparse
import json
import re
import statistics
from pathlib import Path

ACTION = re.compile(r"<parameter=action>\s*([a-z_]+)\s*</parameter>", re.S)
COORD = re.compile(r"<parameter=coordinate>\s*\[?\s*(\d+)\s*,\s*(\d+)", re.S)


def think_len(text):
    """Reasoning length of the FIRST round only, tag-position agnostic.

    The chat template puts the opening <think> in the generation prompt, so a
    generated continuation has no opening tag (job 227162 raw probe). Requiring
    one scored every trained model 0 while crediting the base model for <think>
    blocks inside its hallucinated post-turn rounds. So: measure text before
    the first </think>, but only if no <tool_call> precedes it (a close-tag
    after the action started is a later round, not first-round reasoning).
    """
    text = text or ""
    end = text.find("</think>")
    if end < 0:
        return 0
    tc = text.find("<tool_call>")
    if 0 <= tc < end:
        return 0
    start = text.find("<think>")
    if 0 <= start < end:
        start += len("<think>")
    else:
        start = 0
    return len(text[start:end].strip())


def parse_action(text):
    a = ACTION.search(text or "")
    c = COORD.search(text or "")
    return (a.group(1) if a else None,
            (int(c.group(1)), int(c.group(2))) if c else None,
            think_len(text))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("ckpt", type=Path)
    ap.add_argument("samples_dir", type=Path,
                    help="build.py output dir (uses val_samples.jsonl + images/)")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--max-new-tokens", type=int, default=2048)
    ap.add_argument("--wandb-project", default=None)
    ap.add_argument("--run-name", default=None)
    args = ap.parse_args(argv)

    import torch
    from PIL import Image
    from transformers import AutoModelForImageTextToText, AutoProcessor

    processor = AutoProcessor.from_pretrained(args.ckpt)
    model = AutoModelForImageTextToText.from_pretrained(
        args.ckpt, torch_dtype=torch.bfloat16, device_map="cuda")
    model.eval()

    rows = []
    src = args.samples_dir / "val_samples.jsonl"
    for line in src.open(encoding="utf-8"):
        if line.strip():
            rows.append(json.loads(line))
        if args.limit and len(rows) >= args.limit:
            break

    type_hits, maes, think_ratios, table = [], [], [], []
    for s in rows:
        msgs, images = [], []
        for m in s["messages"]:
            content = []
            for p in m["content"]:
                if p.get("type") == "image":
                    images.append(Image.open(args.samples_dir / p["path"]))
                    content.append({"type": "image"})
                else:
                    content.append({"type": "text", "text": p.get("text", "")})
            msgs.append({"role": m["role"], "content": content})
        inputs = processor.apply_chat_template(
            msgs, add_generation_prompt=True, tokenize=True,
            return_dict=True, return_tensors="pt").to(model.device)
        with torch.inference_mode():
            out = model.generate(**inputs, max_new_tokens=args.max_new_tokens,
                                 do_sample=False)
        student = processor.decode(out[0][inputs["input_ids"].shape[1]:],
                                   skip_special_tokens=True)
        t_act, t_xy, t_think = parse_action(s["response"])
        s_act, s_xy, s_think = parse_action(student)
        if t_act:
            type_hits.append(s_act == t_act)
        if t_xy and s_xy and s_act == t_act:
            maes.append(abs(t_xy[0] - s_xy[0]) + abs(t_xy[1] - s_xy[1]))
        if t_think:
            think_ratios.append(s_think / t_think)
        # raw text goes into the table: parsed-only logging is why the 08-13
        # think=0 artifact took a forensic dig instead of one glance
        table.append((s["meta"]["slug"], s["meta"]["step"],
                      "%s %s" % (t_act, t_xy or ""), "%s %s" % (s_act, s_xy or ""),
                      student[:1500]))
        print("%-28s step %-3s teacher=%s%s student=%s%s"
              % (s["meta"]["slug"][:28], s["meta"]["step"],
                 t_act, t_xy or "", s_act, s_xy or ""))

    metrics = {
        "eval/action_type_acc": sum(type_hits) / max(len(type_hits), 1),
        "eval/coord_mae": statistics.mean(maes) if maes else None,
        "eval/think_len_ratio": statistics.median(think_ratios) if think_ratios else None,
        "eval/n": len(rows),
    }
    print(json.dumps(metrics, indent=1))

    if args.wandb_project:
        import wandb
        run = wandb.init(project=args.wandb_project,
                         name=args.run_name or ("eval-" + args.ckpt.name),
                         config={"ckpt": str(args.ckpt), "n": len(rows)})
        run.log({k: v for k, v in metrics.items() if v is not None})
        run.log({"eval/examples": wandb.Table(
            columns=["slug", "step", "teacher", "student", "student_raw"],
            data=[list(r) for r in table])})
        run.finish()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
