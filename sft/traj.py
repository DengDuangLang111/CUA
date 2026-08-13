"""Turn one task's result directory into clean, training-ready steps.

This is the parsing half of the SFT builder: it owns sections 1-2 of
SFT_DATA.md (step reconstruction and filtering) and knows nothing about
message rendering, images, or models. build.py consumes it.

Every rule here has a receipt in SFT_DATA.md; the comments only say WHICH
rule a block implements, not why it exists.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# The internal tools enum the campaign agent declares
# (mm_agents/qwen/prompts.py, build_internal_tools_def, checked 2026-08-13).
# An action name in a response that is NOT here was hallucinated: the parser
# silently degraded it to WAIT, so the recorded response does not describe
# what actually ran.
DECLARED = frozenset((
    "key", "type", "mouse_move", "left_click", "left_click_drag",
    "right_click", "middle_click", "double_click", "triple_click",
    "scroll", "hscroll", "wait", "terminate", "call_user",
    "left_mouse_down", "left_mouse_up", "hold_key",
))

ACTION_TAG = re.compile(r"<parameter=action>\s*([a-z_]+)\s*</parameter>", re.S)


@dataclass
class Step:
    num: int                    # 1-based step_num from the runner
    response: str               # the model's verbatim output = training label
    actions: list = field(default_factory=list)   # executed pyautogui, in order
    screenshot: str = ""        # file taken AFTER this step's LAST action
    hallucinated: bool = False  # response names an undeclared action


def score(task_dir):
    """The exact score, or None when the task never finished."""
    p = Path(task_dir) / "result.txt"
    try:
        return float(p.read_text().strip())
    except (OSError, ValueError):
        return None


def load_steps(task_dir):
    """traj.jsonl -> [Step], applying SFT_DATA.md section 1.

    - keeps only the LAST episode (append-mode files can stack re-runs)
    - aggregates lines by step_num (one model output = one step)
    - screenshot per step = the LAST line's (multi-action steps save several)
    - marks hallucinated steps (undeclared action names in the response)
    """
    rows = []
    p = Path(task_dir) / "traj.jsonl"
    if not p.is_file():
        return []
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    # Last episode only. Two boundary signals, both against the PREVIOUS row:
    # a step_num decrease, or the same step_num with a different response --
    # multi-action lines of one step are byte-identical in `response`
    # (verified 200/200 in v11), so a changed response at the same number is
    # a re-run starting over, not another action of the same step.
    start = 0
    for i in range(1, len(rows)):
        n, pn = rows[i].get("step_num") or 0, rows[i - 1].get("step_num") or 0
        if n < pn or (n == pn and rows[i].get("response") != rows[i - 1].get("response")):
            start = i
    rows = rows[start:]

    steps = {}
    for r in rows:
        n = r.get("step_num")
        if n is None:
            continue
        s = steps.get(n)
        if s is None:
            resp = str(r.get("response") or "")
            named = set(ACTION_TAG.findall(resp))
            s = steps[n] = Step(num=n, response=resp,
                                hallucinated=bool(named - DECLARED))
        s.actions.append(str(r.get("action") or ""))
        s.screenshot = r.get("screenshot_file") or s.screenshot

    return [steps[k] for k in sorted(steps)]


def tail_run(steps):
    """Length of the trailing run of identical action-lists.

    A passing trajectory can end in a degenerate loop the evaluator never
    sees (43x Ctrl+S in v11). The run length lets build.py truncate it.
    """
    if not steps:
        return 0
    n = 1
    for a, b in zip(reversed(steps), list(reversed(steps))[1:]):
        if a.actions == b.actions:
            n += 1
        else:
            break
    return n
