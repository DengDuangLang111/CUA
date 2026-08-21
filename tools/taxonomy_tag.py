#!/usr/bin/env python3
"""taxonomy_tag.py v2 -- three-layer labels (application / semantic action /
outcome family) over the training corpus, the taskgen candidate pool, and
OSWorld-Verified, and the gap table between them.

v2 (2026-08-20) rewrites the labeler after an adversarial audit of v1's table
found it unusable for quotas: "computer" fired formula_compute, "sort out
Chrome" fired sort_filter, "phone extension"/"file extensions" fired
extensions_addons, "template" made 13 phantom pool candidates for
vs_code/theme_background, journal volume numbers fired playback_media, and 101
of 369 OSWorld tasks (27%) carried no label at all -- almost all of them real
web navigation, cross-app data transfer, and core spreadsheet editing, so the
quota would have funneled everything into the visible 73%. Changes:

  - every action rule may carry a NEGATIVE pattern; a negative match anywhere
    in the instruction suppresses the label (over-suppresses the rare task
    that genuinely does both -- acceptable for planning)
  - four new families cover the audited untagged mass: web_navigation,
    data_transfer, cell_edit, git_ops
  - infeasible tasks (evaluator func "infeasible") are excluded from action
    cells and reported separately: teaching a refusal needs no action
    demonstration, so they must not consume action-cell quota
  - the gap flag is a coverage threshold (train < max(1, round(osw*0.2))),
    not train==0, so undertaught cells like calc/sheet_ops 13|1 surface
  - flagged demand is ALSO reported per-app deduplicated by task id: cells
    are multi-label so summing them overcounts 13-23%

Still keyword rules with unaudited precision -- every gap row prints a sample
instruction, and任何配额定稿前按格子人工过全文(审计固化的教训:格子计数
只做选题索引,不做配额算术)。

Usage (WSL, /tmp holds coverage_audit.py which this imports):
  python3 taxonomy_tag.py --train-instr /tmp/train_instr.json \
      --pool-glob "/mnt/d/research/os-simple-taskgen-v8/out/runs/v11*/examples/*/*.json"
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

# (label, positive, negative-or-None)
ACTIONS = [
    ("pivot", r"pivot", None),
    ("chart_graph", r"\b(chart|graph|plot)\b", None),
    ("sheet_ops", r"\b(worksheet|new sheet|sheet (named|called)|(rename|copy|duplicate|move|delete)\b[^.]{0,30}\bsheet)\b", None),
    ("formula_compute", r"\b(formula|sum\b|average|total|calculat|comput(e\b|ing|ation))", None),
    ("sort_filter", r"\b(sort\b(?!\s+out)|filter)", None),
    ("data_validation", r"\b(validation|drop-?down)", None),
    ("char_format", r"\b(bold|italic|underline|strike-?through|font|highlight|text colou?r)", None),
    ("para_page_layout", r"\b(paragraph|indent|line spacing|spacing|align|margin|header|footer|page number|orientation|landscape|portrait|page break)", None),
    ("references_toc", r"\b(citation|cross-?referen|footnote|endnote|bibliograph|table of contents)", None),
    ("slide_design", r"\b(slide|transition|animation)", None),
    ("theme_background", r"\b(background|theme)\b",
     r"background (script|music|noise|process)|running in the background|background\.\w{2,4}\b"),
    ("speaker_notes", r"speaker('s)? notes?|presenter (notes?|console|view)", None),
    ("layers", r"\blayers?\b|\bflatten\b", None),
    ("transparency", r"\b(transparen|alpha)\b|remove\s+(the\s+)?background", None),
    ("select_crop_mask", r"\b(crop|mask\b|selection)", None),
    ("color_tone", r"\b(brightness|contrast|saturat|desaturat|hue|gr[ae]yscale)", None),
    ("img_transform", r"\b(resize|scale|rotate|flip|mirror)", None),
    ("export_convert", r"\b(export|convert|save (it |this )?as)", None),
    ("history_cache_cookies", r"\b(history|cache|cookies?)\b", None),
    ("privacy_permissions", r"\b(privacy|permission|camera|microphone|location access|notification|pop-?ups?|block)", None),
    ("tabs_windows", r"\b(tabs?\b|window|incognito)", None),
    ("extensions_addons", r"\b(extension|add-?on|plug-?in)",
     r"(file|phone|clear|lacking|without|no)\s+extensions?\b"),
    ("bookmarks", r"\bbookmark", None),
    ("downloads", r"\bdownload", None),
    ("file_ops", r"\b(move|copy|rename|delete|folder|directory|zip|unzip|archive|compress|extract)", None),
    ("system_settings", r"\b(settings?\b|configure|default (app|application)|wallpaper|time ?zone|resolution|keyboard shortcut)", None),
    ("install_software", r"\b(install|\bapt\b|package manager)", None),
    ("terminal_shell", r"\b(terminal|command[- ]line|shell|bash|script)\b",
     r"background script"),
    ("mail_contacts", r"\baddress book\b|\bcontacts\b",
     r"contact (phone|number|information|info|details)"),
    ("mail_filter_rules", r"\bfilter\b.{0,25}\b(mail|message|email|inbox)|mail filter", None),
    ("import_export_profile", r"\b(import)\b", None),
    ("playback_media", r"\b(play\b|pause|volume|full-?screen|subtitle|playlist)",
     r"volume \d|vol\.\s*\d"),
    ("search_find", r"\b(search|look up)", None),
    # four families the audit showed were invisible (27% of OSWorld untagged)
    ("web_navigation", r"\b(flight|hotel|ticket|cart\b|buy\b|purchase|order (a|an|the|me)\b|book (a|an|the|me)\b|reserv|appointment|price|rent\b|shopping)", None),
    ("data_transfer", r"(from|off) (the |this )?(web ?page|web ?site|internet|pdf|spreadsheet|sheet|document)|into (a|an|the) (spreadsheet|sheet|table|csv|xlsx|report|document|deck|slide)|\btranscribe\b", None),
    ("cell_edit", r"\b(fill (down|in|the)|split .{0,25}column|transpose|duplicate rows|remove duplicates|merge cells|number format|freeze|new column|new row)\b", None),
    ("git_ops", r"\bgit\b|\bclone\b|\bcommit\b|repositor", None),
]
CACT = [(n, re.compile(p, re.I), re.compile(g, re.I) if g else None)
        for n, p, g in ACTIONS]

OUTCOME = [
    ("infeasible", r"infeasible"),
    ("presentation", r"pptx|slide|presentation|presenter"),
    ("pdf", r"pdf"),
    ("document", r"docx|page_number|font|paragraph|line_spacing|tabstops|page_break|strike|highlighted|line_number|centered|epub"),
    ("spreadsheet", r"table|csv|xlsx|sheet"),
    ("image", r"image|png|structure_sim|palette|brightness|contrast|saturation|mirror|stretch|triangle|textbox|green_background|rgb"),
    ("browser_state", r"url|tabs|active_tab|bookmark|cookie|history|search_query|extension|steam_cart|shortcut_on_desktop"),
    ("mail", r"thunderbird|mail"),
    ("media", r"audio|video|vlc|mp3|play"),
    ("config_state", r"config|settings|json|prefs|keybinding|utc|favorite|gnome|installed|qt_|auto_saving|left_panel|clickboard"),
    ("file_or_text", r"include_exclude|text_file|file_contains|diff|exact_match|literal|_list|match|files|archive|sqlite|python|htmls?"),
]
COUT = [(n, re.compile(p, re.I)) for n, p in OUTCOME]


def acts(instr):
    t = instr or ""
    hits = [n for n, rx, neg in CACT
            if rx.search(t) and not (neg and neg.search(t))]
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
                    (d.get("instruction") or "")[:78], era,
                    d.get("id") or (d.get("ostg") or {}).get("slug") or "?"))
    return out


def is_gap(v):
    return v["osw"] >= 2 and v["train"] < max(1, round(v["osw"] * 0.2))


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
    osw_all = tag(load_osworld(a.osworld_meta, a.examples_root))
    pool = tag(load_pool(a.pool_glob or a.taskgen_glob, tr))

    infeas = [x for x in osw_all if x[2] == "infeasible"]
    osw = [x for x in osw_all if x[2] != "infeasible"]
    print(f"语料 {len(trn)} | OSWorld {len(osw_all)}(其中 infeasible {len(infeas)} 条"
          f"已剥离,不占动作格)| 候选池 {len(pool)}")
    print("infeasible 按应用: " + ", ".join(
        f"{k}×{v}" for k, v in Counter(x[0] for x in infeas).most_common()))
    eras = Counter(e for *_x, e, _t in pool)
    print("候选池按时代: " + ", ".join(f"{k}×{v}" for k, v in eras.most_common()))

    for name, items in (("语料", trn), ("OSWorld(可行题)", osw), ("候选池", pool)):
        A = Counter(x[0] for x in items)
        O = Counter(x[2] for x in items)
        n = max(len(items), 1)
        print(f"\n=== {name}: 应用 | 产出")
        print("   " + ", ".join(f"{k} {v}({100*v/n:.0f}%)" for k, v in A.most_common()))
        print("   " + ", ".join(f"{k} {v}({100*v/n:.0f}%)" for k, v in O.most_common()))

    rows = {}
    for src, items in (("osw", osw), ("train", trn), ("pool", pool)):
        for app, alist, _o, ins, _e, _t in items:
            for act in alist:
                r = rows.setdefault((app, act),
                                    {"osw": 0, "train": 0, "pool": 0, "ex": None})
                r[src] += 1
                if src == "osw" and r["ex"] is None:
                    r["ex"] = ins
    print("\n=== 缺口表(多标签,格子计数只做选题索引;配额用文末去重数)")
    for app in ORDER:
        sub = sorted(((k[1], v) for k, v in rows.items() if k[0] == app),
                     key=lambda x: -x[1]["osw"])
        sub = [s for s in sub if s[1]["osw"] or s[1]["train"]]
        if not sub:
            continue
        print(f"--- {app}")
        for act, v in sub:
            flag = ""
            if is_gap(v):
                kind = "未教过" if v["train"] == 0 else "教得少"
                flag = f"  <== 缺口({kind})·" + ("池可补" if v["pool"] else "需生成")
            print(f"   {act:24s} {v['osw']:3d} | {v['train']:3d} | {v['pool']:4d}{flag}")
            if flag and v["ex"]:
                print(f"       例: {v['ex']}")

    flagged = {k for k, v in rows.items() if is_gap(v)}
    uniq = {}
    for app, alist, _o, _i, _e, tid in osw:
        for act in alist:
            if (app, act) in flagged:
                uniq.setdefault(app, set()).add(tid)
    slots = sum(v["osw"] for k, v in rows.items() if k in flagged)
    total = len(set().union(*uniq.values())) if uniq else 0
    print(f"\n=== 缺口需求·按任务去重(格子槽位合计 {slots},去重后 {total} 条任务)")
    for app in ORDER:
        if app in uniq:
            print(f"   {app}: {len(uniq[app])} 条")


if __name__ == "__main__":
    main()
