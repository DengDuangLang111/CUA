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


def identical_runs(steps, min_run=7):
    """Target-drop indices for mid-episode grinding: in any maximal run of
    >= min_run consecutive steps with identical action lists, every step
    after the FIRST is dropped as a training target (attempting once is
    legitimate behavior; repeating it 54 times is not). History keeps them.
    Calibrated 2026-08-13 on 51 passing trajectories: longest legitimate
    identical run observed was 6 (file-drag cycles), pathological ones 15-55.

    min_run was 8 until 2026-08-14. The audit that lowered it found
    libreoffice_calc/768f4c21 grinding `moveTo(743,697)+scroll(-10)` exactly
    SEVEN times -- one short of the gate, so all seven became targets and the
    model was trained to scroll again seven times over. 7 is the tight value:
    it catches that and can never fire on the longest run the calibration
    calls legitimate (6). The 72-trajectory corpus contains no 5- or 6-runs at
    all, so the change costs nothing beyond the case it was made for.
    """
    drops = set()
    i = 0
    while i < len(steps):
        j = i
        while j + 1 < len(steps) and steps[j + 1].actions == steps[i].actions:
            j += 1
        if j - i + 1 >= min_run:
            drops.update(range(i + 1, j + 1))
        i = j + 1
    return drops


def low_diversity_runs(steps, max_distinct=3, min_len=8):
    """Target-drop indices for mid-episode OSCILLATION -- the shape
    identical_runs is blind to, because its steps are not consecutive-identical.

    In any maximal window of >= min_len consecutive steps drawn from
    <= max_distinct distinct action lists, keep the FIRST occurrence of each
    distinct action and drop the rest as targets. Same philosophy as
    identical_runs: trying a thing is legitimate, cycling it is not. History
    keeps every step -- the surviving target after such a window is a RECOVERY
    demonstration and is the most valuable sample shape in this corpus.

    Why this is separate from low_diversity_tail rather than a parameter of it:
    that function trims steps off the trajectory entirely, and is gated on the
    episode having hit the step cap because a normally-terminated episode ends
    with meaningful finishing actions that must never be cut. That argument is
    about the TAIL. It says nothing about a window in the middle, so this one
    carries no cap gate. Found gimp/e16448e3 (37 steps, ended normally) cycling
    typewrite("DONE") / press("return") four times in its middle -- invisible to
    both existing filters.
    """
    keys = [tuple(s.actions) for s in steps]
    drops = set()
    i, n = 0, len(keys)
    while i < n:
        seen, j = [], i
        while j < n:
            if keys[j] not in seen:
                if len(seen) == max_distinct:
                    break
                seen.append(keys[j])
            j += 1
        if j - i >= min_len:
            first = {}
            for x in range(i, j):
                if keys[x] in first:
                    drops.add(x)
                else:
                    first[keys[x]] = x
            i = j
        else:
            i += 1
    return drops


def low_diversity_tail(steps, max_distinct=3, min_len=8):
    """Length of the maximal trailing segment made of <= max_distinct
    distinct action lists (>= min_len, else 0). Catches oscillating tails
    (click/WAIT/click cycles) that byte-identity misses. ONLY sound for
    cap-hitting trajectories: a normally-terminated episode ends with
    varied, meaningful steps and must never be gated on this."""
    seen = []
    n = 0
    for s in reversed(steps):
        key = tuple(s.actions)
        if key not in seen:
            if len(seen) == max_distinct:
                break
            seen.append(key)
        n += 1
    return n if n >= min_len else 0
