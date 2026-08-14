"""Loop-filter behaviour, pinned. Run it after touching traj.py.

    PYTHONPATH=<ostg repo> python -m ostg.sft.test_filters

Each case is a string of letters; one letter is one step's action list. The
output marks a dropped training target with '.'. Written 2026-08-14, when an
audit found three trajectories whose loops reached the training targets.
"""
import sys

from ostg.sft.traj import identical_runs, low_diversity_runs


class _Step:
    def __init__(self, a):
        self.actions = [a]


def _show(s, fn, **kw):
    dropped = fn([_Step(c) for c in s], **kw)
    return "".join("." if i in dropped else c for i, c in enumerate(s))


CASES = [
    # low_diversity_runs -- mid-episode oscillation, the shape identical_runs
    # cannot see because the repeats are not consecutive
    ("gimp/e16448e3: typewrite/press cycled 4x mid-trajectory",
     "abcdefggghijklmnopqrstuavvwxyxyxyxyza",
     "abcdefggghijklmnopqrstuavvwxy......za", low_diversity_runs, {}),

    # Documented, not accidental: max_distinct=3 lets a neighbouring action
    # join the window and push it to min_len. Nothing unique is lost -- the
    # first occurrence of every distinct action always survives.
    ("a neighbour can extend the window; it still survives",
     "abcdxyxyxyxefg", "abcdxy.....efg", low_diversity_runs, {}),

    ("window of 6 is below min_len, untouched",
     "abcxyxyxdefg", "abcxyxyxdefg", low_diversity_runs, {}),
    ("4 distinct actions is not low diversity",
     "abcdwxyzwxyzwxyzabcd", "abcdwxyzwxyzwxyzabcd", low_diversity_runs, {}),
    ("first occurrence of every distinct action is kept",
     "aaaaaaaabbbb", "a.......b...", low_diversity_runs, {}),
    ("an ordinary varied trajectory is untouched",
     "abcdefghijklmnop", "abcdefghijklmnop", low_diversity_runs, {}),
    ("empty", "", "", low_diversity_runs, {}),

    # identical_runs -- min_run lowered 8 -> 7 on 2026-08-14. The calibration
    # note in traj.py puts the longest LEGITIMATE identical run at 6, so 7 is
    # the tight value: it catches libreoffice_calc/768f4c21 and nothing else.
    ("run of 7 is caught at the new default",
     "abhhhhhhhcd", "abh......cd", identical_runs, {}),
    ("run of 6 is calibrated-legitimate, untouched",
     "abhhhhhhcd", "abhhhhhhcd", identical_runs, {}),
    ("the old threshold is still reachable via --min-run",
     "abhhhhhhhcd", "abhhhhhhhcd", identical_runs, {"min_run": 8}),
]


def main():
    ok = True
    for name, src, want, fn, kw in CASES:
        got = _show(src, fn, **kw)
        good = got == want
        ok &= good
        print("  %s  %s" % ("PASS" if good else "FAIL", name))
        if not good:
            print("        got  %s\n        want %s" % (got, want))

    # The two filters must not disagree: every index identical_runs drops sits
    # inside a low-diversity window too, so enabling both can only ever drop
    # the union and never produce a contradictory kept/dropped pair.
    s = "abcaaaaaaaaaaaadef"
    steps = [_Step(c) for c in s]
    good = identical_runs(steps) <= low_diversity_runs(steps)
    ok &= good
    print("  %s  identical_runs drops are a subset of low_diversity_runs drops"
          % ("PASS" if good else "FAIL"))

    print("\nALL PASS" if ok else "\nSOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
