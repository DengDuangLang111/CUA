"""Axis-first task taxonomy: define the axes, then enumerate their product.

v1 and v2 drew axis targets by sampling the labelled official suite. That
guarantees every brief is a task shape OSWorld really contains, but it caps the
space at what OSWorld already does -- 80 (artifact, source, operation) cells,
whose two largest stand for 48 and 40 official tasks apiece. The measured cost
was collapse: three VS Code settings tasks scoring r0.56 against each other and
three Impress restyle tasks r0.52-0.63 (see ostg.contam).

This module defines the axes up front instead, and crosses them:

    intent  x  domain  x  difficulty   =   5 x 13 x 5  =  325 cells

`domain` is the axis v2 lacked entirely. Its absence is what let the generator
produce three "change a VS Code setting" tasks in a row: nothing forced them
apart except the prompt line "make the batch diverse", which is a request, not a
constraint. Thirteen enumerated business settings make that a constraint.

None of the three carries OSWorld content -- they are generic categories, not
anything lifted from the evaluation set. The borrow-coordinates-not-content line
is in SAMPLING.md and this module stays on the safe side of it.

WHAT IS DELIBERATELY NOT CROSSED
--------------------------------
The application and the artifact. Rotating those independently produces
combinations no real task has -- `raster_image` with `libreoffice_calc`, a
`slide_deck` in GIMP -- and ostg already learned that once (see the comment in
gen.cells). They are drawn instead from pairs the official suite actually
exhibits, so every cell stays buildable while intent/domain/constraints do the
diversifying.

Two further axes from the reference taxonomy are absent on purpose:

  difficulty as step count -- removed in an earlier generation and not revived.
      Steps are a property of (task x agent), not of the task: the 208-step
      failure in the first real batch had a brief indistinguishable from its
      14-step neighbours. `constraints` is the generatable substitute -- how many
      explicit requirements the instruction imposes is decided when it is
      written, and can be counted without running anything.

  ambiguity -- excluded because it contradicts the grading model. RULE 9 requires
      one unambiguous end state, because probe_py has to decide correctness with
      no human in the loop. Varying ambiguity needs a grader that tolerates it;
      that is a different judging mechanism, not another axis.
"""
from __future__ import annotations

import collections
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABELS = HERE / "data" / "osworld361_labels.json"

# What the user is fundamentally trying to get done. Five verbs, chosen to be
# mutually exclusive at the level of the finished artifact: a task is asking for
# information, reshaping something, changing a setting, making something new, or
# fixing something broken.
INTENTS = {
    "info_seeking": "find information that already exists somewhere in the "
                    "environment and report it in the requested form",
    "transform": "convert or restructure content that already exists into a "
                 "different shape, format or ordering",
    "configure": "change a setting, preference or piece of environment state so "
                 "the machine behaves differently afterwards",
    "create": "produce an artifact that does not exist yet, from data or "
              "requirements supplied in the instruction",
    "repair": "find what is wrong in existing content and correct it",
}

# Business settings the scenario is dressed in. These do the diversifying work
# that "make the batch diverse" could only ask for: two tasks in the same cell
# of the old taxonomy but different domains cannot converge on the same
# business rule, because the rule belongs to the domain.
DOMAINS = [
    "finance", "healthcare", "education", "logistics", "human_resources",
    "legal", "marketing", "scientific_research", "retail", "real_estate",
    "travel", "manufacturing", "nonprofit",
]

# Difficulty, as (how many applications) x (how many explicit requirements).
#
# v3 used requirement count alone and it did not predict anything: across the
# first 15 rollouts the success rate was 0/1, 1/5, 0/1, 0/4 over its four levels,
# with retry loops as common at 2 requirements as at 4. Application count has
# evidence behind it -- in the official 361-task campaign multi_apps is the
# lowest-scoring domain at 31% with a median of 36 steps, against 7 steps for
# single-app chrome.
#
# The scale is ordered so every level is buildable and none is empty. An earlier
# draft put "two apps, 4+ requirements" and "two apps, 1-2 requirements" both at
# level 3, which collapses to "any two-app task" and leaves single-app 4+ with
# nowhere to go -- 46 of v3's 185 specs were exactly that. Levels 4 and 5 are
# split by app count rather than by "3 apps" versus "more than 3": the whole
# official suite contains three tasks with four applications, so a top tier
# defined as >3 would be unbuildable.
DIFFICULTY = {
    1: ("one application, one requirement -- a single condition, field or "
        "transformation", 1, 1),
    2: ("one application, two or three requirements that must all hold", 1, 2),
    3: ("one application and four or more requirements, INCLUDING an ordering "
        "or tie-breaking rule; or two applications and one to three "
        "requirements", 1, 4),
    4: ("two applications and four or more requirements including an ordering "
        "rule; or three applications and one to three requirements", 2, 4),
    5: ("three or more applications, four or more requirements, including an "
        "ordering or tie-breaking rule", 3, 4),
}

# How much of a run each level should be. Deliberately not uniform: level 5 is
# harder than the hardest thing the official suite contains (3+ apps AND an
# ordering rule, where official's 3-app tasks already score 31%), so most of
# those rollouts will fail and produce no SFT sample. 15% buys a measurement of
# where the model breaks without spending a third of the VM budget on it.
DIFFICULTY_MIX = {1: 0.15, 2: 0.25, 3: 0.25, 4: 0.20, 5: 0.15}

# Which artifacts each intent can plausibly end in. Without this the product
# yields cells like configure+slide_deck, which is not a task anyone writes.
# Intersected at draw time with the artifacts the official suite actually
# carries, so the result is both coherent and buildable.
INTENT_ARTIFACTS = {
    "info_seeking": {"spreadsheet", "text_document", "browser_tab",
                     "terminal_output", "filesystem"},
    "transform": {"spreadsheet", "text_document", "slide_deck", "pdf_or_archive",
                  "raster_image", "source_code"},
    "configure": {"preference_store", "app_data_store", "desktop_session"},
    "create": {"spreadsheet", "text_document", "slide_deck", "pdf_or_archive",
               "source_code", "filesystem"},
    "repair": {"spreadsheet", "text_document", "source_code", "filesystem",
               "preference_store"},
}


def observed_pairs(domain_app):
    """(artifact -> [app, ...]) as the official suite actually pairs them.

    The counter is kept, not flattened to a set: an artifact carried by calc in
    40 tasks and by writer in 2 should not present those as equally typical.
    """
    tasks = json.loads(LABELS.read_text(encoding="utf-8"))["tasks"]
    hosts = collections.defaultdict(collections.Counter)
    for t in tasks:
        app = domain_app.get(t["domain"])
        if app:
            hosts[t["artifact"]][app] += 1
    return hosts


def enumerate_space(shard=None):
    """The full product, as a list. 5 x 13 x 5 = 325.

    `shard` is (index, total) and keeps only every total-th cell. Batches within
    one process are sequential because each one is told what the previous ones
    wrote; that serialisation is what makes 200 specs a ~3 hour run. Disjoint
    shards let several processes run at once without reintroducing the collision
    the avoid list exists to prevent -- two processes cannot draw the same
    (intent, domain, constraints) cell because the partition is by construction,
    not by coordination.
    """
    space = [(i, d, c) for i in INTENTS for d in DOMAINS for c in DIFFICULTY]
    if shard:
        idx, total = shard
        # Permute before striding. A raw stride inherits the product's own
        # periodicity: the comprehension varies `constraints` fastest over its 4
        # values, so `space[i::4]` handed every shard exactly ONE constraint level
        # -- shard 0 got 65 cells all at c=1, shard 3 all at c=4. Blocking instead
        # would have done the same thing to `intent`, the outermost axis. Any
        # arithmetic partition of a product aligns with some axis of it; a
        # permutation aligns with none.
        #
        # The seed is a constant, not `seed`: every process must derive the SAME
        # permutation or the shards stop being disjoint, which is the one property
        # that lets them run without coordinating.
        random.Random(20260808).shuffle(space)
        space = space[idx::total]
    return space


def cells(n, seed, domain_app, only_apps=None, used=None, shard=None):
    """Draw n briefs from the enumerated space.

    `used` is the set of (intent, domain, constraints) triples already spent by
    earlier batches of this run; passing it makes successive batches walk the
    260-cell product instead of re-drawing its most probable corners. Once every
    cell is spent the draw simply returns fewer than n -- the caller sees a short
    batch rather than silent repeats.
    """
    # How many times each intent and each artifact were already drawn by EARLIER
    # batches, read off the spent-cell set rather than kept in a variable.
    #
    # The rotation counter below used to start at zero on every call, and since a
    # batch draws each intent exactly once it never advanced past zero -- every
    # batch took options[0], the alphabetically first buildable artifact for that
    # intent. Over a 200-spec run that produced FOUR distinct artifacts:
    # info_seeking was browser_tab 40 times out of 40, transform was
    # pdf_or_archive, create and repair were both filesystem, configure was
    # app_data_store. spreadsheet, text_document, slide_deck, source_code and
    # raster_image could not occur at all. The artifact axis was not narrow, it
    # was constant.
    #
    # `used` is the only cross-batch state cells() receives, so the offset is
    # derived from it. Snapshotted here because the loop adds to `used` as it goes.
    prior_intent = collections.Counter(c[0] for c in (used or ()))
    # Difficulty is quota-driven, not uniform over the product. Levels are equal
    # thirds of the cartesian space but must not be equal shares of a run: see
    # DIFFICULTY_MIX. `spent_diff` is how many of each level earlier batches
    # already took, so the quota is a run-level property, not a per-batch one.
    spent_diff = collections.Counter(c[2] for c in (used or ()))
    rng = random.Random(seed)
    space = enumerate_space(shard)
    rng.shuffle(space)
    used = set(used or ())
    hosts = observed_pairs(domain_app)
    rotation = collections.Counter()

    # Balance intent within the batch. A plain shuffle is uniform in expectation
    # but not in any single draw -- the first seed tried here put 4 of 6 cells on
    # `transform`, and a batch weighted that way reproduces exactly the
    # clustering the domain axis exists to prevent. Taking the least-used intent
    # each time spreads the batch across all five without changing which cells
    # are reachable.
    taken = collections.Counter()
    taken_diff = collections.Counter()
    out = []

    while len(out) < n:
        # Cheapest correct form: scan for the first unspent cell whose intent is
        # currently least represented. The space is 260 entries, so the linear
        # scan costs nothing and avoids the bookkeeping a heap would need.
        # Sort by (how far this intent is ahead, how far this difficulty is
        # ahead of its quota). Difficulty is second because intent balance is a
        # hard guarantee and the mix is a target: a run that ends one level-4
        # short is fine, a run that writes 40 `transform` and 8 `repair` is the
        # collapse the whole taxonomy exists to prevent.
        drawn = sum(spent_diff.values()) + len(out)
        def diff_debt(level):
            want = DIFFICULTY_MIX.get(level, 0) * max(drawn + 1, 1)
            return (spent_diff[level] + taken_diff[level]) - want
        pick = None
        for cell in sorted(space, key=lambda c: (taken[c[0]], diff_debt(c[2]))):
            if cell in used:
                continue
            intent, _, _ = cell
            options = sorted(INTENT_ARTIFACTS[intent] & set(hosts))
            if only_apps:
                options = [a for a in options
                           if any(app in only_apps for app in hosts[a])]
            if options:
                pick = (cell, options)
                break
            # No buildable artifact for this intent under --apps: spend the cell
            # so the scan cannot see it again and spin forever.
            used.add(cell)
        if pick is None:
            break  # space exhausted, or --apps excludes everything left

        (intent, domain, difficulty), options = pick
        used.add((intent, domain, difficulty))
        taken[intent] += 1
        taken_diff[difficulty] += 1
        _gloss, n_apps, n_reqs = DIFFICULTY[difficulty]

        # prior_intent carries the offset across batches; rotation carries it
        # within one, for the case where n exceeds the number of intents.
        turn = prior_intent[intent] + rotation[intent]
        artifact = options[turn % len(options)]
        apps = [a for a, _ in hosts[artifact].most_common()
                if not only_apps or a in only_apps]
        # Divided, not counted separately: the app should advance only once the
        # artifact rotation has come all the way round, so an artifact carried by
        # two apps alternates between them across full cycles instead of tracking
        # the intent counter and re-aliasing with it.
        primary = apps[(turn // len(options)) % len(apps)]
        rotation[intent] += 1

        out.append({
            "intent": intent,
            "domain": domain,
            "difficulty": difficulty,
            # Kept because emit, report and task_index.csv all read it, and
            # because "how many requirements" is still the countable half of
            # what difficulty means. It is now derived, not an axis.
            "constraints": n_reqs,
            "artifact": artifact,
            "primary": primary,
            # v1/v2 axes the emitter still reads. `source` is not crossed: it
            # follows from the intent (transform and repair act on something
            # already present; the rest are told what to do), and crossing it
            # would produce cells like configure+second_local_artifact.
            #
            # browser_tab is the exception on both fields. A task whose answer is
            # WHICH PAGE CHROME ENDED ON leaves no file, so it is graded by
            # OSWorld's own url matcher and its probe_py is empty BY DESIGN. Left
            # at "file" the cell overwrote the model's correct `browser_state`
            # (gen.py stamps gold_kind from the cell, deliberately, so a blocked
            # cell cannot be downgraded) and emit would then wire an empty probe
            # into a file-reading evaluator: every such task scores 0 forever,
            # and the build-time controls report n/a rather than failing, so it
            # ships silently. Measured on the killed run: 5 of the first 21.
            # `second_local_artifact` says the data lives in a SECOND FILE the
            # agent must open, not in the instruction. v3 never produced one --
            # source was a hardcoded three-way choice -- and the cost was
            # measurable: 56% of its specs were prompt_literal, and the ones that
            # inlined a table (up to 36 numbers in a single instruction) are where
            # the agent's retry loops started. Dozens of keystrokes is dozens of
            # chances to see a screen that does not match.
            #
            # It replaces prompt_literal on alternate draws rather than always:
            # "the values are stated in the instruction" is a real task shape too,
            # and reading a number out of a sentence is not the failure -- typing
            # sixty of them is.
            "source": "live_web" if artifact == "browser_tab"
                      else ("self" if intent in ("transform", "repair")
                            else ("second_local_artifact" if turn % 2 else
                                  "prompt_literal")),
            "operation": "",
            # 1 for most, 2 or 3 for one draw in four. v3 emitted app_count=1 for
            # 184 of 185 specs because this was hardcoded, so the multi-app shape
            # -- which the official suite carries as its own domain -- never
            # occurred. Kept a minority: every extra application multiplies the
            # ways a rollout can wander off, and the loop rate is already 75%.
            # From the difficulty level, not a rotation. This is the axis now.
            "app_count": n_apps,
            "gold_kind": "browser_state" if artifact == "browser_tab" else "file",
            "needs_setup_shell": False,
            "blocker": "",
            "drawn_from": "taxonomy:%s/%s/d%d" % (intent, domain, difficulty),
        })
    return out
