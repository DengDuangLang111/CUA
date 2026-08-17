"""Loop-filter behaviour, pinned. Run it after touching traj.py.

    PYTHONPATH=<ostg repo> python -m ostg.sft.test_filters

Each case is a string of letters; one letter is one step's action list. The
output marks a dropped training target with '.'.

Only the SHIPPED filters are covered. A 2026-08-14 attempt to add a
count-based oscillation filter and to lower min_run to 7 was reverted: see
TRAINING.md, "repeat count is not evidence of pathology".
"""
import sys

from ostg.sft.traj import identical_runs, low_diversity_tail


class _Step:
    def __init__(self, a):
        self.actions = [a]


def _steps(s):
    return [_Step(c) for c in s]


def _show(s, fn, **kw):
    dropped = fn(_steps(s), **kw)
    return "".join("." if i in dropped else c for i, c in enumerate(s))


def main():
    ok = True

    def t(name, got, want):
        nonlocal ok
        good = got == want
        ok &= good
        print("  %s  %s" % ("PASS" if good else "FAIL", name))
        if not good:
            print("        got  %r\n        want %r" % (got, want))

    print("identical_runs  ('.' = dropped as a training target)")
    t("run of 8 is caught at the shipped default",
      _show("abhhhhhhhhcd", identical_runs), "abh.......cd")
    t("run of 7 is NOT caught -- deliberately. libreoffice_calc/768f4c21 "
      "scrolls 7x and the screen changes every time, so it is real work",
      _show("abhhhhhhhcd", identical_runs), "abhhhhhhhcd")
    t("run of 6 is the calibrated legitimate maximum",
      _show("abhhhhhhcd", identical_runs), "abhhhhhhcd")
    t("keeps the first step of a caught run",
      _show("aaaaaaaaaa", identical_runs), "a.........")
    t("an ordinary varied trajectory is untouched",
      _show("abcdefghijklmnop", identical_runs), "abcdefghijklmnop")
    t("empty", _show("", identical_runs), "")

    print("\nlow_diversity_tail  (returns a LENGTH to trim, not an index set)")
    # 9, not 8: max_distinct=3 lets the neighbouring "f" join the window as a
    # third distinct action. This widening is pre-existing shipped behaviour,
    # not a defect -- worth pinning so it is not rediscovered as a surprise.
    t("oscillating tail; a neighbour joins as the 3rd distinct action",
      low_diversity_tail(_steps("abcdefxyxyxyxy")), 9)
    t("a varied tail is not trimmed",
      low_diversity_tail(_steps("xyxyxyxyabcdef")), 0)
    t("tail shorter than min_len is not trimmed",
      low_diversity_tail(_steps("abcdefghxyxyxy")), 0)
    t("empty", low_diversity_tail(_steps("")), 0)

    print("\nALL PASS" if ok else "\nSOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())


def test_whole_traj_reject():
    from ostg.sft.traj import whole_traj_reject, Step
    def mk(n, done=True, bad_at=None):
        steps = []
        for i in range(1, n + 1):
            r = "<tool_call><parameter=action>\nleft_click\n</parameter></tool_call>"
            h = False
            if bad_at == i:
                r = "<tool_call><parameter=action>\nctrl_scroll\n</parameter></tool_call>"
                h = True
            steps.append(Step(num=i, response=r, actions=["pyautogui.click(1,1)"], hallucinated=h))
        if done:
            steps[-1].actions = ["DONE"]
        return steps
    assert whole_traj_reject(mk(10)) is None
    assert whole_traj_reject(mk(50)) == "cap-hit"
    assert whole_traj_reject(mk(10, done=False)) == "no-done"
    assert whole_traj_reject(mk(10, bad_at=3)) == "illegal:ctrl_scroll"


def test_think_est_tokens():
    from ostg.sft import traj
    assert traj.think_est_tokens("<think>" + "a" * 350 + "</think>x") == 100
    assert traj.think_est_tokens("no think here") == 0
    assert traj.think_est_tokens("") == 0
