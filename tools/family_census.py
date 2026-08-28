#!/usr/bin/env python3
"""Family census: evaluator-family distribution over task-JSON trees.

The canonical 117-func -> 11-family mapping lives HERE; the prose mirror is
reference/EVAL_FAMILY_TAXONOMY.md. Actions are annotation, never a metric --
this is the statistics axis.

    python3 tools/family_census.py <dir> [<dir> ...]

A <dir> is anything containing task JSONs two levels down (an official
evaluation_examples/examples, or an ostg out/runs/<set>/examples).
"""
import collections
import json
import sys
from pathlib import Path

# Order matters: earlier rows win (compare_pdf_images is image, not pdf).
PREFIX = [
    ("infeasible", ("infeasible",)),
    ("deck_property", ("compare_pptx", "check_slide", "check_transition",
                       "check_presenter", "evaluate_presentation",
                       "check_textbox", "audio_in_slide")),
    ("doc_property", ("compare_docx", "compare_line_spacing", "check_font",
                      "compare_font", "is_first_line", "check_highlighted",
                      "evaluate_strike", "evaluate_colored",
                      "contains_page_break", "check_tabstops",
                      "has_page_numbers", "compare_subscript",
                      "check_page_number", "find_default_font",
                      "check_continuation", "check_italic")),
    ("table_property", ("compare_table", "compare_csv", "check_csv",
                        "compare_unique", "compare_conference")),
    ("image_property", ("compare_image", "check_image", "check_brightness",
                        "check_saturation", "check_contrast", "check_palette",
                        "check_structure", "check_green", "check_triangle",
                        "compare_pdf_images", "check_file_exists_and_struct")),
    ("pdf_property", ("compare_pdf", "check_pdf")),
    ("media_state", ("compare_audio", "compare_video", "check_mp3", "is_vlc",
                     "check_play", "check_qt", "check_global_key",
                     "check_one_instance")),
    ("browser_state", ("is_expected_url", "is_expected_active_tab",
                       "is_expected_tabs", "is_expected_bookmarks",
                       "is_cookie", "check_history", "is_expected_search",
                       "is_added_to", "check_url_and_content",
                       "is_expected_installed", "is_extension_installed")),
    ("config_state", ("check_json", "check_config", "check_thunderbird",
                      "compare_config", "check_auto_saving", "check_gnome",
                      "is_utc", "check_accessibility", "check_left_panel",
                      "is_shortcut", "check_line_number",
                      "check_direct_json")),
]


def family(func):
    for fam, prefixes in PREFIX:
        if func.startswith(prefixes):
            return fam
    return "text_or_shell"


def census(root):
    c, n = collections.Counter(), 0
    for p in sorted(Path(root).glob("**/*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        ev = t.get("evaluator") if isinstance(t, dict) else None
        if not isinstance(ev, dict) or not ev.get("func"):
            continue
        f = ev["func"]
        c[family(f if isinstance(f, str) else f[0])] += 1
        n += 1
    return c, n


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    for root in argv:
        c, n = census(root)
        print("== %s  (%d tasks)" % (root, n))
        for fam, k in c.most_common():
            print("  %-16s %5d  %5.1f%%" % (fam, k, k / n * 100))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
