#!/usr/bin/env python3
"""taxonomy_tag.py -- three-layer labels (application / semantic action /
outcome family) over the training corpus, the taskgen candidate pool, and
OSWorld-Verified, and the gap table between them.

Why this exists: coverage_audit.py compares evaluator *functions*, but an
evaluator name never appears in the model's input or SFT target -- it is a
proxy for task shape, not proof an action was or wasn't taught. Quota planning
for targeted data generation (2026-08-20 plan: append ~100 success
trajectories, no downsampling) needs the level the model actually experiences:
which app, doing what, producing what. So:

  layer 1  application      -- OSWorld: the domain directory; generated tasks:
                              related_apps collapsed (files/terminal count as
                              "os"; two or more non-os apps = "multi")
  layer 2  semantic action  -- keyword rules over the instruction text,
                              MULTI-LABEL (one task can hit several), so
                              per-app counts are label occurrences, not a
                              partition. Heuristic: precision unaudited; every
                              gap row prints a sample instruction so a human
                              can eyeball the label before trusting a quota.
  layer 3  outcome family   -- mapped from evaluator function names (the one
                              place the evaluator IS the right signal: it
                              names the artifact being checked)

Output: per-corpus app/outcome mixes, then the gap table -- every app x action
cell with OSWorld count, training count, candidate-pool count, flagged when
OSWorld needs it and training never taught it, split by whether the existing
pool can fill it or generation is required.

Usage (WSL, /tmp holds coverage_audit.py which this imports):
  python3 taxonomy_tag.py --train-instr /tmp/train_instr.json
"""
import argparse, glob, json, os, re, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from coverage_audit import load_corpus, funcs

APP_MAP = {
    "libreoffice_calc": "calc", "libreoffice_impress": "impress",
    "libreoffice_writer": "writer", "vs_code": "vs_code", "vscode": "vs_code",
    "code": "vs_code", "files": "os", "terminal": "os", "os": "os",
    "file_manager": "os", "chrome": "chrome", "gimp": "gimp",
    "thunderbird": "thunderbird", "vlc": "vlc", "multi_apps": "multi",
}
ORDER = ["calc", "impress", "chrome", "gimp", "writer", "multi", "os",
         "vs_code", "thunderbird", "vlc"]

ACTIONS = [
    ("pivot", r"pivot"),
    ("chart_graph", r"\b(chart|graph|plot)\b"),
    ("sheet_ops", r"\b(worksheet|new sheet|sheet (named|called)|(rename|copy|duplicate|move|delete)\b[^.]{0,30}\bsheet)\b"),
    ("formula_compute", r"\b(formula|sum\b|average|total|calculat|comput)"),
    ("sort_filter", r"\b(sort|filter)"),
    ("data_validation", r"\b(validation|drop-?down)"),
    ("char_format", r"\b(bold|italic|underline|strike-?through|font|highlight|text colou?r)"),
    ("para_page_layout", r"\b(paragraph|indent|line spacing|spacing|align|margin|header|footer|page number|orientation|landscape|portrait|page break)"),
    ("references_toc", r"\b(citation|cross-?referen|footnote|endnote|bibliograph|table of contents)"),
    ("slide_design", r"\b(slide|transition|animation)"),
    ("theme_background", r"\b(background|theme|template)"),
    ("speaker_notes", r"\b(speaker note|presenter)"),
    ("layers", r"\blayers?\b"),
    ("transparency", r"\b(transparen|alpha)\b|remove\s+(the\s+)?background"),
    ("select_crop_mask", r"\b(crop|mask\b|selection)"),
    ("color_tone", r"\b(brightness|contrast|saturat|desaturat|hue|gr[ae]yscale)"),
    ("img_transform", r"\b(resize|scale|rotate|flip|mirror)"),
    ("export_convert", r"\b(export|convert|save (it |this )?as)"),
    ("history_cache_cookies", r"\b(history|cache|cookies?)\b"),
    ("privacy_permissions", r"\b(privacy|permission|camera|microphone|location access|notification|pop-?ups?|block)"),
    ("tabs_windows", r"\b(tabs?\b|window|incognito)"),
    ("extensions_addons", r"\b(extension|add-?on|plug-?in)"),
    ("bookmarks", r"\bbookmark"),
    ("downloads", r"\bdownload"),
    ("file_ops", r"\b(move|copy|rename|delete|folder|directory|zip|unzip|archive|compress|extract)"),
    ("system_settings", r"\b(settings?\b|configure|default (app|application)|wallpaper|time ?zone|resolution|keyboard shortcut)"),
    ("install_software", r"\b(install|\bapt\b|package manager)"),
    ("terminal_shell", r"\b(terminal|command[- ]line|shell|bash|script)"),
    ("mail_contacts", r"\b(contacts?\b|address book)"),
    ("mail_filter_rules", r"\b(filter\b.{0,20}\b(mail|message|email)|mail filter)"),
    ("import_export_profile", r"\b(import)\b"),
    ("playback_media", r"\b(play\b|pause|volume|full-?screen|subtitle|playlist)"),
    ("search_find", r"\b(search|look up)"),
]
CACT = [(n, re.compile(p, re.I)) for n, p in ACTIONS]

OUTCOME = [
    ("infeasible", r"infeasible"),
    ("presentation", r"pptx|slide|presentation|presenter"),
    ("pdf", r"pdf"),
    ("document", r"docx|page_number|font|paragraph|line_spacing|tabstops|page_break|strike|highlighted|line_number|centered|epub"),
    ("spreadsheet", r"table|csv|xlsx|sheet"),
    ("image", r"image|png|structure_sim|palette|brightness|contrast|saturation|mirror|stretch|triangle|textbox|green_background|rgb"),
    ("browser_state", r"url|tabs|active_tab|bookmark|cookie|history|search_query|extension|steam_cart|shortcut_on_desktop",),
    ("mail", r"thunderbird|mail"),
    ("media", r"audio|video|vlc|mp3|play"),
    ("config_state", r"config|settings|json|prefs|keybinding|utc|favorite|gnome|installed|qt_|auto_saving|left_panel|clickboard",),
    ("file_or_text", r"include_exclude|text_file|file_contains|diff|exact_match|literal|_list|match|files|archive|sqlite|python|htmls?",),
]
COUT = [(n, re.compile(p, re.I)) for n, p in OUTCOME]


def acts(instr):
    hits = [n for n, rx in CACT if rx.search(instr or "")]
    return hits or ["(untagged)"]


def outcome_of(fs):
    for name, rx in COUT:
        if any(rx.search(f) for f in fs):
            return name
    return "other" if fs else "(no evaluator)"


def app_of_generated(d):
    apps = {APP_MAP.get(a, a) for a in (d.get("related_apps") or [])}
    non_os = apps - {"os"}
    if len(non_os) >= 2:
        return "multi"
    return next(iter(non_os)) if non_os else "os"


def load_osworld(meta_path, root):
    meta = json.load(open(meta_path, encoding="utf-8"))
    out = []
    for dom, ids in meta.items():
        for tid in ids:
            for cand in (os.path.join(root, "examples", dom, tid + ".json"),
                         os.path.join(root, dom, tid + ".json")):
                if os.path.exists(cand):
                    try:
                        d = json.load(open(cand, encoding="utf-8"))
                    except Exception:
                        break
                    out.append((APP_MAP.get(dom, dom), d, None))
                    break
    return out


def load_pool(taskgen_glob, train_instrs):
    def norm(x):
        return re.sub(r"\s+", " ", (x or "").strip().lower())
    tn = {norm(v) for v in train_instrs.values()}
    seen = {}
    for p in glob.glob(taskgen_glob):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        ins = norm(d.get("instruction"))
        if not ins or ins in tn:
            continue
        sl = (d.get("ostg") or {}).get("slug") or os.path.basename(p)
        if (sl, ins) in seen:
            continue
        era = p.split("/out/runs/")[1].split("/")[0] if "/out/runs/" in p else "?"
        seen[(sl, ins)] = (app_of_generated(d), d, era)
    return list(seen.values())


def tag(items):
    out = []
    for app, d, era in items:
        out.append((app, acts(d.get("instruction")),
                    outcome_of(funcs(d.get("evaluator") or {})),
                    (d.get("instruction") or "")[:78], era))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-instr", required=True)
    ap.add_argument("--taskgen-glob",
                    default="/mnt/d/research/os-simple-taskgen-v8/out/runs/*/examples/*/*.json")
    ap.add_argument("--osworld-meta",
                    default="/mnt/d/research/OSWorld/evaluation_examples/test_all.json")
    ap.add_argument("--examples-root",
                    default="/mnt/d/research/OSWorld/evaluation_examples")
    ap.add_argument("--pool-glob", default=None,
                    help="restrict the CANDIDATE POOL to this glob while the "
                         "training corpus keeps matching against the full "
                         "--taskgen-glob (user decree 2026-08-20: only v11+ "
                         "eras are candidates; the data standard is r5's)")
    a = ap.parse_args()

    tr, by_slug, found, _ = load_corpus(a.train_instr, a.taskgen_glob)
    trn = tag([(app_of_generated(d), d, None) for d in found.values()])
    osw = tag(load_osworld(a.osworld_meta, a.examples_root))
    pool_raw = load_pool(a.pool_glob or a.taskgen_glob, tr)
    pool = tag(pool_raw)
    print(f"语料 {len(trn)} | OSWorld {len(osw)} | 候选池(去重、除训练) {len(pool)}")
    eras = Counter(e for *_x, e in pool)
    print("候选池按时代: " + ", ".join(f"{k}×{v}" for k, v in eras.most_common()))

    for name, items in (("语料", trn), ("OSWorld", osw), ("候选池", pool)):
        A = Counter(x[0] for x in items)
        O = Counter(x[2] for x in items)
        n = max(len(items), 1)
        print(f"\n=== {name}: 应用 | 产出")
        print("   " + ", ".join(f"{k} {v}({100*v/n:.0f}%)"
                                for k, v in A.most_common()))
        print("   " + ", ".join(f"{k} {v}({100*v/n:.0f}%)"
                                for k, v in O.most_common()))

    rows = {}
    for src, items in (("osw", osw), ("train", trn), ("pool", pool)):
        for app, alist, _o, ins, _e in items:
            for act in alist:
                r = rows.setdefault((app, act),
                                    {"osw": 0, "train": 0, "pool": 0, "ex": None})
                r[src] += 1
                if src == "osw" and r["ex"] is None:
                    r["ex"] = ins
    print("\n=== 缺口表(动作为多标签,计数是标签命中数;每行 OSWorld|语料|候选池)")
    for app in ORDER:
        sub = sorted(((k[1], v) for k, v in rows.items() if k[0] == app),
                     key=lambda x: -x[1]["osw"])
        sub = [s for s in sub if s[1]["osw"] or s[1]["train"]]
        if not sub:
            continue
        print(f"--- {app}")
        for act, v in sub:
            flag = ""
            if v["osw"] >= 2 and v["train"] == 0:
                flag = ("  <== 缺口·池可补" if v["pool"] else "  <== 缺口·需生成")
            print(f"   {act:24s} {v['osw']:3d} | {v['train']:3d} | {v['pool']:4d}{flag}")
            if flag and v["ex"]:
                print(f"       例: {v['ex']}")


if __name__ == "__main__":
    main()
