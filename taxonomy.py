"""Axis-first task taxonomy: define the axes, then enumerate their product.

v1 and v2 drew axis targets by sampling the labelled official suite. That
guarantees every brief is a task shape OSWorld really contains, but it caps the
space at what OSWorld already does -- 80 (artifact, source, operation) cells,
whose two largest stand for 48 and 40 official tasks apiece. The measured cost
was collapse: three VS Code settings tasks scoring r0.56 against each other and
three Impress restyle tasks r0.52-0.63 (see ostg.contam).

This module defines the axes up front instead, and crosses them:

    intent  x  domain  x  constraints   =   5 x 13 x 4  =  260 cells

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

# How many explicit requirements the instruction imposes. This is the
# generatable half of "difficulty": it is fixed at writing time and countable
# from the instruction text, unlike step count, which only exists after a
# rollout and belongs to the agent as much as to the task.
CONSTRAINTS = {
    1: "one requirement -- a single condition, field or transformation",
    2: "two requirements that must both hold",
    3: "three requirements, at least one of which depends on another",
    4: "four or more requirements, including an ordering or tie-breaking rule",
}

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
    """The full product, as a list. 5 x 13 x 4 = 260.

    `shard` is (index, total) and keeps only every total-th cell. Batches within
    one process are sequential because each one is told what the previous ones
    wrote; that serialisation is what makes 200 specs a ~3 hour run. Disjoint
    shards let several processes run at once without reintroducing the collision
    the avoid list exists to prevent -- two processes cannot draw the same
    (intent, domain, constraints) cell because the partition is by construction,
    not by coordination.
    """
    space = [(i, d, c) for i in INTENTS for d in DOMAINS for c in CONSTRAINTS]
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
    out = []

    while len(out) < n:
        # Cheapest correct form: scan for the first unspent cell whose intent is
        # currently least represented. The space is 260 entries, so the linear
        # scan costs nothing and avoids the bookkeeping a heap would need.
        pick = None
        for cell in sorted(space, key=lambda c: taken[c[0]]):
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

        (intent, domain, constraints), options = pick
        used.add((intent, domain, constraints))
        taken[intent] += 1

        artifact = options[rotation[intent] % len(options)]
        apps = [a for a, _ in hosts[artifact].most_common()
                if not only_apps or a in only_apps]
        primary = apps[rotation[artifact] % len(apps)]
        rotation[intent] += 1
        rotation[artifact] += 1

        out.append({
            "intent": intent,
            "domain": domain,
            "constraints": constraints,
            "artifact": artifact,
            "primary": primary,
            # v1/v2 axes the emitter still reads. `source` is not crossed: it
            # follows from the intent (transform and repair act on something
            # already present; the rest are told what to do), and crossing it
            # would produce cells like configure+second_local_artifact.
            "source": "self" if intent in ("transform", "repair")
                      else "prompt_literal",
            "operation": "",
            "app_count": 1,
            "gold_kind": "file",
            "needs_setup_shell": False,
            "blocker": "",
            "drawn_from": "taxonomy:%s/%s/%d" % (intent, domain, constraints),
        })
    return out
