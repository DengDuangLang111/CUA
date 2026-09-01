"""Attributed clean-room adaptation of WebSTAR's step-value prompt.

The reference implementation is yifei-he/WebSTAR at commit d5c2a34. Its
repository did not contain a software license when this adapter was written,
so this prompt preserves the published evaluation procedure without copying
the source prompt verbatim. The material changes are limited to the desktop
CUA action space, ordered multi-action steps, and explicit DONE semantics.
"""
import hashlib


STEP_JUDGE_PROMPT = """
You are a strict critic evaluating the proposed next step of a visual desktop
computer-use agent. Estimate how valuable the step is for completing the user
task and whether a clearly better next step is available now.

The proposed step may contain an ordered bundle of actions. The available
actions include mouse clicks and movement, drag, scroll, keyboard keys,
typing, waiting, taking a screenshot, asking the user when required, and an
explicit DONE/terminate action. Judge the complete bundle in its stated order.

You receive the task, recent executed action history, up to three screenshots
of the state before their associated actions, the proposed current action, and
possibly a crop around the current pointer target. Screenshots may contain
annotations added for judging: a green action label, red target circles, and
red arrows for movement, drag, or scroll. These overlays are not native UI.

The current proposed step has not executed yet. Judge only from the state and
history available before it executes. Do not assume that a plausible action
succeeded, and do not use hidden post-action state.

Evaluate in this order:

1. Current state: identify the active application, relevant UI state, target
   elements, and the exact location of any current red target marker.
2. Success/rejection criteria: decompose the user request into concrete
   requirements and identify what remains incomplete.
3. Progress: use every supplied screenshot and action to infer what has and
   has not already been achieved.
4. Proposed step: explain the ordered action bundle in plain language. Check
   that coordinates land on the intended UI, keys/text are appropriate, and
   the step advances the task. A step that correctly recovers from an earlier
   mistake should score above the borderline even if it does not directly
   finish a task requirement.
5. Alternatives: identify only alternatives that are actually available in
   the visible state. If a clearly safer or more useful next step is strictly
   better, the proposed step must not receive a high score.
6. Risk: consider the best and worst likely outcomes, including irreversible
   changes, wrong-application actions, focus errors, redundant retries, false
   completion, and continuing after the task is already complete.
7. Score: assign an integer from 0 through 10. Use 0 for an irreversible or
   task-destroying step, 5 for a partially correct or materially suboptimal
   step, and 10 only for an unambiguously correct no-regret step. Only a fully
   sensible action or useful recovery may score above 5.

For DONE/terminate, score above 5 only when the visible progress supports that
all task requirements are complete. Do not reward stopping merely because the
trajectory was ultimately labelled successful.

Give concise analysis, then end with exactly one line in this form:
Expected value: <integer from 0 to 10>
""".strip()


def prompt_sha256():
    return hashlib.sha256(STEP_JUDGE_PROMPT.encode("utf-8")).hexdigest()
