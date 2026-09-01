"""Generate a minimal desktop adaptation from WebSTAR's official prompt.

The official repository had no software license at the pinned commit, so the
prompt text is not vendored here. This tool extracts the official constant from
a user-supplied checkout, verifies its SHA-256, applies a small asserted set of
desktop substitutions, and writes the resulting runtime artifact plus a
provenance report outside Git.
"""
from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
from pathlib import Path


OFFICIAL_COMMIT = "d5c2a34cb7ff193a85c144fdd91f48a0e716da86"
OFFICIAL_CONSTANT = "GPT_STEP_JUDGE_REVISED"
OFFICIAL_SHA256 = "240c77aca3c08b4f862c48d91f35a8a3a22303554eb5f3d584a2df39cb2f7906"
PROFILE = "official-revised-adapted-d5c2a34"


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_constant(path, name=OFFICIAL_CONSTANT):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name
                   for target in node.targets):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value, node.lineno, node.end_lineno
        raise TypeError(f"{name} is not a literal string")
    raise KeyError(f"constant not found: {name}")


def _replace_once(text, old, new, label, changes):
    count = text.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected one source block, found {count}")
    changes.append(label)
    return text.replace(old, new, 1)


def adapt_prompt(official):
    if sha256(official) != OFFICIAL_SHA256:
        raise ValueError(
            "official prompt hash mismatch; use the pinned WebSTAR commit")
    changes = []
    text = official
    text = _replace_once(
        text,
        "- A single PROPOSED_NEXT_ASSISTANT_ACTION.",
        "- A single PROPOSED_NEXT_ASSISTANT_ACTION that may contain an "
        "ordered bundle of desktop actions executed as one model step.",
        "allow ordered desktop action bundle", changes)

    official_actions = """Assistant action space includes:
- `click(x, y)`: click at coordinates (x, y)
- `scroll(x, y, scroll_x, scroll_y)`: scroll at (x, y) by the pixel amounts (scroll_x, scroll_y)
- `keypress(keys)`: press keys like "Enter", "Ctrl+A", etc.
- `type(text)`: type a string (must click on an input first)
- `wait`: wait for page to change or update
- `screenshot`: take a new screenshot
- `final_answer(answer)`: output the final answer to the user (no screenshot will be given with this)"""
    desktop_actions = """Assistant action space includes:
- mouse clicks, including left, right, double, and triple click at pixel coordinates
- mouse movement and drag between pixel coordinates
- vertical or horizontal scroll
- keyboard press and hotkey actions
- type or write text into the focused control
- wait for the desktop state to update
- capture a screenshot
- ask the user when the task requires information or approval
- DONE/terminate when every user requirement is complete

The proposed action text contains the actual ordered pyautogui action bundle
executed by the harness. Its pixel coordinates use the same coordinate frame
as the screenshots and red action markers."""
    text = _replace_once(text, official_actions, desktop_actions,
                         "replace browser action space", changes)

    text = _replace_once(
        text,
        "    - The assistant cannot type in url, go back to the previous website, or sign in to any website.",
        "    - Judge only actions available in the supplied desktop action "
        "space and do not infer hidden application or file-system state.",
        "remove WebVoyager-only restrictions", changes)
    text = _replace_once(
        text,
        "    - For final answer, the answer show on the screenshot may be truncated, so focus on the content of the answer provided in text. Do the analysis as other actions. Give score <=5 for final answer only if you are absolutely certain that the answer is incorrect, do not hallucinate about information not provided on the screenshots.",
        "    - For DONE/terminate, judge whether the supplied progress "
        "supports completion of every user requirement. Do not infer hidden "
        "success, and score <=5 when completion is not adequately supported.",
        "adapt final answer to explicit DONE", changes)
    text = _replace_once(text, "web element", "UI element",
                         "rename web element to UI element", changes)
    if text == official:
        raise AssertionError("adapter made no changes")
    return text, changes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-prompts", type=Path, required=True,
                        help="pinned WebSTAR step_eval/gpt_prompts.py")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--diff", type=Path, default=None)
    args = parser.parse_args(argv)

    official, line_start, line_end = extract_constant(args.official_prompts)
    adapted, changes = adapt_prompt(official)
    artifact = adapted.strip()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(artifact + "\n", encoding="utf-8")
    report = {
        "profile": PROFILE,
        "official_commit": OFFICIAL_COMMIT,
        "official_source": str(args.official_prompts.resolve()),
        "official_source_lines": [line_start, line_end],
        "official_prompt_sha256": sha256(official),
        "adapted_prompt_sha256": sha256(artifact),
        "changes": changes,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.diff:
        diff = difflib.unified_diff(
            (official.rstrip() + "\n").splitlines(keepends=True),
            (artifact + "\n").splitlines(keepends=True),
            fromfile=f"WebSTAR@{OFFICIAL_COMMIT[:8]}:{OFFICIAL_CONSTANT}",
            tofile=PROFILE,
            n=3)
        args.diff.parent.mkdir(parents=True, exist_ok=True)
        args.diff.write_text("".join(diff), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
