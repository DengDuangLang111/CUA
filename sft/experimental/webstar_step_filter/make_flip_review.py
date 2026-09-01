"""Build a static human-review site for prompt-induced step flips."""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import html
import io
import json
from pathlib import Path

from PIL import Image

from .common import StepKey, iter_jsonl, load_source_rows, parse_named_paths
from .grade_steps import build_judge_messages, load_instruction, resolve_task_dir

try:
    from ... import traj
except ImportError:  # pragma: no cover
    from sft import traj


def load_scores(path):
    rows = {}
    for row in iter_jsonl(path):
        key = StepKey.from_dict(row)
        if key in rows:
            raise ValueError(f"duplicate score key: {key.text()}")
        rows[key] = row
    return rows


def load_flips(path):
    rows = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            row["step"] = int(row["step"])
            rows.append(row)
    return rows


def derive_flips(old_scores, new_scores):
    if set(old_scores) != set(new_scores):
        missing_old = sorted(key.text() for key in set(new_scores) - set(old_scores))
        missing_new = sorted(key.text() for key in set(old_scores) - set(new_scores))
        raise ValueError(
            f"score key mismatch: missing_old={missing_old[:3]} "
            f"missing_new={missing_new[:3]}")
    flips = []
    for key in sorted(old_scores):
        old_score = int(old_scores[key]["score"])
        new_score = int(new_scores[key]["score"])
        old_decision = "keep" if old_score > 5 else "drop"
        new_decision = "keep" if new_score > 5 else "drop"
        if old_decision == new_decision:
            continue
        flips.append({
            **key.as_dict(),
            "old_prompt_score": old_score,
            "new_prompt_score": new_score,
            "delta": new_score - old_score,
            "transition": f"{old_decision}->{new_decision}",
        })
    return flips


def _safe(value):
    return html.escape(str(value), quote=True)


def _asset_name(key, index):
    digest = hashlib.sha256(key.text().encode()).hexdigest()[:16]
    return f"{digest}_{index:02d}.jpg"


def save_judge_images(messages, key, assets_dir):
    images, caption = [], "Screenshot"
    for part in messages[1]["content"]:
        if part.get("type") == "text" and part.get("text"):
            caption = part["text"].rstrip(":")
        if part.get("type") != "image_url":
            continue
        url = part["image_url"]["url"]
        raw = base64.b64decode(url.split(",", 1)[1])
        with Image.open(io.BytesIO(raw)).convert("RGB") as image:
            if image.width > 1100:
                height = round(image.height * 1100 / image.width)
                image = image.resize((1100, height), Image.Resampling.LANCZOS)
            name = _asset_name(key, len(images))
            image.save(assets_dir / name, "JPEG", quality=78, optimize=True)
        images.append({"src": f"assets/{name}", "caption": caption})
    return images


def build_card(key, flip, source_row, old_score, new_score,
               result_dir, tasks_dir, assets_dir):
    messages, evidence = build_judge_messages(
        key, source_row, result_dir, tasks_dir, judge_prompt="review")
    images = save_judge_images(messages, key, assets_dir)
    instruction = load_instruction(tasks_dir, key)
    task_dir = resolve_task_dir(result_dir, key)
    steps = traj.load_steps(task_dir)
    step = next(item for item in steps if item.num == key.step)
    transition = flip["transition"]
    return {
        "key": key,
        "anchor": hashlib.sha256(key.text().encode()).hexdigest()[:16],
        "transition": transition,
        "old_score": int(old_score["score"]),
        "new_score": int(new_score["score"]),
        "delta": int(new_score["score"]) - int(old_score["score"]),
        "instruction": instruction,
        "actions": evidence["raw_actions"],
        "response": source_row.sample.get("response", ""),
        "old_judge": old_score.get("judge_text", ""),
        "new_judge": new_score.get("judge_text", ""),
        "old_prompt": old_score.get("prompt_sha256", ""),
        "new_prompt": new_score.get("prompt_sha256", ""),
        "images": images,
        "action_budget": int(evidence["action_budget"]),
        "n_steps": int((source_row.sample.get("meta") or {}).get("n_steps") or 0),
    }


def render_card(card, old_label, new_label):
    key = card["key"]
    screenshots = "".join(
        f'<figure><a href="{_safe(item["src"])}" target="_blank">'
        f'<img loading="lazy" src="{_safe(item["src"])}"></a>'
        f'<figcaption>{_safe(item["caption"])}</figcaption></figure>'
        for item in card["images"])
    actions = "\n".join(card["actions"]) or "[No executed action]"
    search = " ".join((key.domain, key.task_id, str(key.step),
                       str(card["action_budget"]), card["instruction"],
                       actions)).lower()
    return f"""
<article class="card" id="{card['anchor']}" data-transition="{card['transition']}"
         data-search="{_safe(search)}" data-delta="{card['delta']}">
  <header class="card-head">
    <div>
      <span class="transition {card['transition'].replace('->', '-')}">{_safe(card['transition'].replace('->', ' → '))}</span>
      <span class="score old">old {card['old_score']}</span>
      <span class="arrow">→</span>
      <span class="score new">official {card['new_score']}</span>
      <span class="delta">Δ {card['delta']:+d}</span>
    </div>
    <a class="anchor" href="#{card['anchor']}">#</a>
  </header>
  <div class="meta">{_safe(key.domain)} · step {key.step}/{card['n_steps']} · action budget {card['action_budget']} · {_safe(key.task_id)}</div>
  <h2>{_safe(card['instruction'])}</h2>
  <section>
    <h3>Executed action bundle</h3>
    <pre>{_safe(actions)}</pre>
  </section>
  <div class="screens">{screenshots}</div>
  <div class="judges">
    <section class="judge old-judge">
      <h3>{_safe(old_label)} · score {card['old_score']}</h3>
      <div class="hash">{_safe(card['old_prompt'])}</div>
      <pre>{_safe(card['old_judge'])}</pre>
    </section>
    <section class="judge new-judge">
      <h3>{_safe(new_label)} · score {card['new_score']}</h3>
      <div class="hash">{_safe(card['new_prompt'])}</div>
      <pre>{_safe(card['new_judge'])}</pre>
    </section>
  </div>
  <details>
    <summary>Original teacher target response</summary>
    <pre>{_safe(card['response'])}</pre>
  </details>
</article>"""


def render_page(cards, source_hash, old_hash, new_hash, title, subtitle,
                old_label, new_label, compared, old_keep, new_keep):
    keep_drop = sum(card["transition"] == "keep->drop" for card in cards)
    drop_keep = sum(card["transition"] == "drop->keep" for card in cards)
    cards_html = "\n".join(
        render_card(card, old_label, new_label) for card in cards)
    flipped = len(cards)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_safe(title)}</title>
<style>
:root{{--bg:#f5f6f8;--panel:#fff;--ink:#172026;--muted:#66737c;--line:#dfe4e8;--red:#b42318;--green:#067647;--blue:#175cd3}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,sans-serif}}
.top{{position:sticky;top:0;z-index:10;background:rgba(255,255,255,.96);border-bottom:1px solid var(--line);padding:18px 24px;backdrop-filter:blur(10px)}}
.top h1{{margin:0 0 4px;font-size:22px}} .subtitle,.meta,.hash{{color:var(--muted)}}
.stats{{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}} .stat{{padding:7px 11px;border-radius:10px;background:#eef2f6;font-weight:650}}
.controls{{display:flex;gap:8px;flex-wrap:wrap}} button,input,select{{border:1px solid #cbd3d9;border-radius:9px;background:#fff;padding:9px 12px;font:inherit}}
button.active{{background:#172026;color:#fff}} input{{min-width:280px;flex:1}}
main{{max-width:1480px;margin:24px auto;padding:0 18px 80px}} .card{{background:var(--panel);border:1px solid var(--line);border-radius:16px;margin:0 0 24px;padding:20px;box-shadow:0 2px 8px rgba(16,24,40,.04)}}
.card-head{{display:flex;justify-content:space-between;align-items:center}} .transition,.score,.delta{{display:inline-block;border-radius:999px;padding:5px 9px;margin-right:5px;font-weight:750}}
.keep-drop{{background:#fee4e2;color:var(--red)}} .drop-keep{{background:#dcfae6;color:var(--green)}} .score{{background:#eef4ff;color:var(--blue)}} .delta{{background:#f2f4f7}} .anchor{{text-decoration:none;font-size:20px;color:#98a2b3}}
h2{{font-size:18px;margin:10px 0 15px}} h3{{font-size:14px;margin:8px 0}} pre{{white-space:pre-wrap;word-break:break-word;background:#f8fafb;border:1px solid #e7ebee;border-radius:10px;padding:12px;max-height:470px;overflow:auto}}
.screens{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;margin:16px 0}} figure{{margin:0;background:#111;border-radius:10px;overflow:hidden}} figure img{{display:block;width:100%;height:auto}} figcaption{{background:#20262b;color:#fff;padding:6px 9px;font-size:12px}}
.judges{{display:grid;grid-template-columns:1fr 1fr;gap:14px}} .judge{{min-width:0}} .hash{{font:11px ui-monospace,monospace;overflow-wrap:anywhere}} details{{margin-top:14px}} summary{{cursor:pointer;font-weight:700}}
.hidden{{display:none}} .shown{{font-weight:700;color:var(--muted)}}
@media(max-width:850px){{.judges{{grid-template-columns:1fr}} .top{{position:static}}}}
</style>
</head>
<body>
<header class="top">
  <h1>{_safe(title)}</h1>
  <div class="subtitle">{_safe(subtitle)}</div>
  <div class="stats">
    <span class="stat">{compared} compared</span>
    <span class="stat">{_safe(old_label)} keep: {old_keep}</span>
    <span class="stat">{_safe(new_label)} keep: {new_keep}</span>
    <span class="stat">{flipped} flipped</span>
    <span class="stat">keep → drop: {keep_drop}</span>
    <span class="stat">drop → keep: {drop_keep}</span>
    <span class="stat shown" id="shown">Showing {flipped}</span>
  </div>
  <div class="controls">
    <button data-filter="all" class="active">All</button>
    <button data-filter="keep->drop">Keep → Drop</button>
    <button data-filter="drop->keep">Drop → Keep</button>
    <input id="search" placeholder="Search task, domain, id, step or action">
    <select id="sort"><option value="source">Original order</option><option value="abs">Largest |Δ|</option><option value="delta-up">Delta ascending</option><option value="delta-down">Delta descending</option></select>
    <button id="reset">Reset</button>
  </div>
</header>
<main id="cards">{cards_html}</main>
<script>
const cards=[...document.querySelectorAll('.card')], box=document.querySelector('#cards'); let filter='all';
function apply(){{const q=document.querySelector('#search').value.toLowerCase().trim(); let shown=0; cards.forEach(c=>{{const ok=(filter==='all'||c.dataset.transition===filter)&&(!q||c.dataset.search.includes(q));c.classList.toggle('hidden',!ok);if(ok)shown++}});document.querySelector('#shown').textContent=`Showing ${{shown}}`;}}
document.querySelectorAll('button[data-filter]').forEach(b=>b.onclick=()=>{{filter=b.dataset.filter;document.querySelectorAll('button[data-filter]').forEach(x=>x.classList.toggle('active',x===b));apply()}});
document.querySelector('#search').oninput=apply; document.querySelector('#sort').onchange=e=>{{const mode=e.target.value;const sorted=[...cards];if(mode==='abs')sorted.sort((a,b)=>Math.abs(+b.dataset.delta)-Math.abs(+a.dataset.delta));if(mode==='delta-up')sorted.sort((a,b)=>(+a.dataset.delta)-(+b.dataset.delta));if(mode==='delta-down')sorted.sort((a,b)=>(+b.dataset.delta)-(+a.dataset.delta));sorted.forEach(c=>box.appendChild(c));}};
document.querySelector('#reset').onclick=()=>{{filter='all';document.querySelector('#search').value='';document.querySelector('#sort').value='source';cards.forEach(c=>box.appendChild(c));document.querySelectorAll('button[data-filter]').forEach(x=>x.classList.toggle('active',x.dataset.filter==='all'));apply();}};
</script>
<!-- source={source_hash} old={old_hash} new={new_hash} -->
</body></html>"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--flips", type=Path, default=None,
        help="optional precomputed flip CSV; omitted derives score > 5 flips")
    parser.add_argument("--old-scores", type=Path, required=True)
    parser.add_argument("--new-scores", type=Path, required=True)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--result", action="append", required=True)
    parser.add_argument("--tasks", action="append", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--title", default="WebSTAR prompt flip review")
    parser.add_argument("--subtitle", default="Paired score-manifest comparison")
    parser.add_argument("--old-label", default="Old prompt")
    parser.add_argument("--new-label", default="New prompt")
    args = parser.parse_args(argv)

    source_dirs = parse_named_paths(args.source, "--source")
    result_dirs = parse_named_paths(args.result, "--result")
    task_dirs = parse_named_paths(args.tasks, "--tasks")
    if set(source_dirs) != set(result_dirs) or set(source_dirs) != set(task_dirs):
        raise ValueError("source/result/tasks names must match")
    index, source_reports = load_source_rows(source_dirs)
    old_scores, new_scores = load_scores(args.old_scores), load_scores(args.new_scores)
    flips = (load_flips(args.flips) if args.flips
             else derive_flips(old_scores, new_scores))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = args.out_dir / "assets"
    assets_dir.mkdir(exist_ok=True)
    cards = []
    for position, flip in enumerate(flips, 1):
        key = StepKey.from_dict(flip)
        if key not in index or key not in old_scores or key not in new_scores:
            raise KeyError(f"unresolved flip key: {key.text()}")
        cards.append(build_card(
            key, flip, index[key], old_scores[key], new_scores[key],
            result_dirs[key.source_build], task_dirs[key.source_build], assets_dir))
        print(f"[{position}/{len(flips)}] {key.text()}")

    old_hashes = {row.get("prompt_sha256") for row in old_scores.values()}
    new_hashes = {row.get("prompt_sha256") for row in new_scores.values()}
    old_keep = sum(int(row["score"]) > 5 for row in old_scores.values())
    new_keep = sum(int(row["score"]) > 5 for row in new_scores.values())
    page = render_page(
        cards, source_reports, sorted(old_hashes), sorted(new_hashes),
        args.title, args.subtitle, args.old_label, args.new_label,
        len(old_scores), old_keep, new_keep)
    (args.out_dir / "index.html").write_text(page, encoding="utf-8")
    report = {
        "cards": len(cards),
        "keep_to_drop": sum(card["transition"] == "keep->drop" for card in cards),
        "drop_to_keep": sum(card["transition"] == "drop->keep" for card in cards),
        "assets": len(list(assets_dir.glob("*.jpg"))),
        "compared": len(old_scores),
        "old_label": args.old_label,
        "new_label": args.new_label,
        "old_keep": old_keep,
        "new_keep": new_keep,
        "old_prompt_sha256": sorted(old_hashes),
        "new_prompt_sha256": sorted(new_hashes),
        "source_reports": source_reports,
        "old_score_file": str(args.old_scores.resolve()),
        "new_score_file": str(args.new_scores.resolve()),
    }
    (args.out_dir / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
