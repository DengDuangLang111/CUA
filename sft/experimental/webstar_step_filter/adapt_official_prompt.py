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
EQUAL_BUDGET_PROFILE = "official-revised-equal-budget-v1"


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


def _add_equal_budget_contract(text, changes):
    marker = (
        "IMPORTANT: The assistant has **not yet executed** the proposed action. "
        "You must judge its value **before it runs**, based on what is visible "
        "on screen.\n\n------------------------"
    )
    contract = """IMPORTANT: The assistant has **not yet executed** the proposed action. You must judge its value **before it runs**, based on what is visible on screen.

STEP-GRANULARITY CONTRACT FOR THIS DESKTOP ADAPTATION:
- The user input supplies `CURRENT_ACTION_BUDGET: N primitive action(s)`, where N is the number of primitive actions in the proposed action bundle.
- Every alternative must be one immediately executable next-action bundle containing at most N primitive actions from the defined action space.
- An alternative may use only the same visible information available to the proposed action. It must not depend on an intermediate screenshot, observation, branch, or later policy step.
- A natural-language plan spanning multiple future steps is not a valid alternative. Do not penalize a correct and necessary intermediate action merely because later steps remain or because a longer future plan could complete more of the task.
- An alternative is strictly better only if an admissible bundle with at most N primitive actions clearly dominates the proposed bundle in immediate correctness, task progress, reliability, safety, or action cost. If an alternative exceeds the budget or needs an intermediate observation, mark it invalid and do not use it to impose the score cap.

------------------------"""
    text = _replace_once(
        text, marker, contract, "add equal-action-budget contract", changes)
    text = _replace_once(
        text,
        "   b. Judge whether this makes sense given the current context and progress.",
        "   b. Judge whether this makes sense given the current context and "
        "progress at the granularity of one next-action bundle. Do not compare "
        "it with a longer future plan.",
        "apply next-step granularity in proposed-action review", changes)
    text = _replace_once(
        text,
        "   a. Propose one or more better actions the assistant could take **now**, choosing only from the defined action space.",
        "   a. Propose one or more alternative action bundles the assistant "
        "could take **now**, choosing only from the defined action space. Each "
        "alternative must contain at most the supplied CURRENT_ACTION_BUDGET "
        "and must be executable without an intermediate observation.",
        "constrain alternatives to equal or smaller action budget", changes)
    text = _replace_once(
        text,
        "   e. If **any alternative** is strictly better, then the proposed action’s score must be ≤6. Otherwise, score may be >6.",
        "   e. If **any admissible alternative within the supplied action "
        "budget** is strictly better, then the proposed action’s score must be "
        "≤6. Otherwise, score may be >6. Never apply this cap for an invalid "
        "multi-step plan or an alternative that exceeds the budget.",
        "limit score cap to admissible alternatives", changes)
    return text


def adapt_prompt(official, equal_budget=False):
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
    if equal_budget:
        text = _add_equal_budget_contract(text, changes)
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
    parser.add_argument(
        "--equal-budget", action="store_true",
        help="add the experimental same-or-lower primitive-action budget contract")
    args = parser.parse_args(argv)

    official, line_start, line_end = extract_constant(args.official_prompts)
    adapted, changes = adapt_prompt(official, equal_budget=args.equal_budget)
    artifact = adapted.strip()
    profile = EQUAL_BUDGET_PROFILE if args.equal_budget else PROFILE
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(artifact + "\n", encoding="utf-8")
    report = {
        "profile": profile,
        "official_commit": OFFICIAL_COMMIT,
        "official_source": str(args.official_prompts.resolve()),
        "official_source_lines": [line_start, line_end],
        "official_prompt_sha256": sha256(official),
        "adapted_prompt_sha256": sha256(artifact),
        "equal_action_budget": args.equal_budget,
        "changes": changes,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.diff:
        diff = difflib.unified_diff(
            (official.rstrip() + "\n").splitlines(keepends=True),
            (artifact + "\n").splitlines(keepends=True),
            fromfile=f"WebSTAR@{OFFICIAL_COMMIT[:8]}:{OFFICIAL_CONSTANT}",
            tofile=profile,
            n=3)
        args.diff.parent.mkdir(parents=True, exist_ok=True)
        args.diff.write_text("".join(diff), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
