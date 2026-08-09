"""The task space: intent x domain x difficulty, enumerated and drawn from.

Glosses are part of the prompt (gen.user_prompt quotes them verbatim); change
them only when changing the prompt is the intent.
"""
from __future__ import annotations

import collections
import random

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

DOMAINS = [
    "finance", "healthcare", "education", "logistics", "human_resources",
    "legal", "marketing", "scientific_research", "retail", "real_estate",
    "travel", "manufacturing", "nonprofit",
]

# (gloss, apps, min requirements). Levels 4-5 exist mostly to measure where the
# model breaks; DIFFICULTY_MIX keeps them a minority of a run.
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

DIFFICULTY_MIX = {1: 0.15, 2: 0.25, 3: 0.25, 4: 0.20, 5: 0.15}

# The slide's fourth axis, not yet crossed in: the probe decides alone, so
# today every instruction must name one unambiguous end state. Crossing this in
# means changing the prompt and the grader together.
AMBIGUITY = (1, 2, 3, 4)

# Which artifacts each intent can plausibly end in. browser_tab is graded by
# OSWorld's own url matcher (grade=browser), not by a probe.
INTENT_ARTIFACTS = {
    "info_seeking": {"spreadsheet", "text_document", "terminal_output",
                     "filesystem", "browser_tab"},
    "transform": {"spreadsheet", "text_document", "slide_deck", "pdf_or_archive",
                  "raster_image", "source_code"},
    "configure": {"preference_store", "app_data_store", "desktop_session"},
    "create": {"spreadsheet", "text_document", "slide_deck", "pdf_or_archive",
               "source_code", "filesystem"},
    "repair": {"spreadsheet", "text_document", "source_code", "filesystem",
               "preference_store"},
}

# artifact -> apps that carry it in the official suite, most common first.
# Derived once from osworld361_labels.json (v6 read it at runtime).
ARTIFACT_HOSTS = {
    "app_data_store": ["chrome", "vscode", "thunderbird"],
    "browser_tab": ["chrome"],
    "desktop_session": ["vlc", "thunderbird", "vscode", "libreoffice_impress",
                        "gimp", "files"],
    "filesystem": ["files", "vscode", "chrome", "thunderbird"],
    "pdf_or_archive": ["libreoffice_calc", "chrome", "libreoffice_writer"],
    "preference_store": ["vscode", "chrome", "files", "vlc", "thunderbird",
                         "gimp", "libreoffice_impress", "libreoffice_writer"],
    "raster_image": ["gimp", "libreoffice_impress", "vlc"],
    "slide_deck": ["libreoffice_impress"],
    "source_code": ["vscode"],
    "spreadsheet": ["libreoffice_calc"],
    "terminal_output": ["files"],
    "text_document": ["libreoffice_writer", "files", "vscode"],
}


def cells(n, seed, only_apps=None, used=None, shard=None):
    """Draw n briefs. `used` is the (intent, domain, difficulty) triples earlier
    batches spent, so a run walks the product instead of re-drawing corners.

    `shard` is (index, total): keep only every total-th cell of the product, so
    N processes generate at once over disjoint coordinates. Permute before
    striding -- a raw stride aligns with the innermost axis and hands each
    shard a single difficulty level. The permutation seed is a CONSTANT, not
    `seed`: every process must derive the same partition or the shards stop
    being disjoint."""
    prior_intent = collections.Counter(c[0] for c in (used or ()))
    spent_diff = collections.Counter(c[2] for c in (used or ()))
    rng = random.Random(seed)
    space = [(i, d, c) for i in INTENTS for d in DOMAINS for c in DIFFICULTY]
    if shard:
        idx, total = shard
        random.Random(20260808).shuffle(space)
        space = space[idx::total]
    rng.shuffle(space)
    used = set(used or ())
    rotation = collections.Counter()
    taken = collections.Counter()
    taken_diff = collections.Counter()
    out = []

    while len(out) < n:
        # Least-used intent first (a hard guarantee), then difficulty-quota
        # debt (a target). Linear scan over 325 entries costs nothing.
        drawn = sum(spent_diff.values()) + len(out)

        def diff_debt(level):
            want = DIFFICULTY_MIX.get(level, 0) * max(drawn + 1, 1)
            return (spent_diff[level] + taken_diff[level]) - want

        pick = None
        for cell in sorted(space, key=lambda c: (taken[c[0]], diff_debt(c[2]))):
            if cell in used:
                continue
            intent = cell[0]
            options = sorted(INTENT_ARTIFACTS[intent] & set(ARTIFACT_HOSTS))
            if only_apps:
                options = [a for a in options
                           if any(app in only_apps for app in ARTIFACT_HOSTS[a])]
            if options:
                pick = (cell, options)
                break
            used.add(cell)
        if pick is None:
            break

        (intent, domain, difficulty), options = pick
        used.add((intent, domain, difficulty))
        taken[intent] += 1
        taken_diff[difficulty] += 1
        _gloss, n_apps, n_reqs = DIFFICULTY[difficulty]

        turn = prior_intent[intent] + rotation[intent]
        artifact = options[turn % len(options)]
        apps = [a for a in ARTIFACT_HOSTS[artifact]
                if not only_apps or a in only_apps]
        primary = apps[(turn // len(options)) % len(apps)]
        rotation[intent] += 1

        out.append({
            "intent": intent,
            "domain": domain,
            "difficulty": difficulty,
            "constraints": n_reqs,
            "artifact": artifact,
            "primary": primary,
            "source": ("live_web" if artifact == "browser_tab"
                       else ("self" if intent in ("transform", "repair")
                             else ("second_local_artifact" if turn % 2 else
                                   "prompt_literal"))),
            "app_count": n_apps,
            # How the task is judged; the cell dictates it and the model
            # cannot downgrade it (the v6 lesson).
            "grade": ("browser" if artifact == "browser_tab"
                      else "table" if artifact == "spreadsheet" else "probe"),
            "drawn_from": "taxonomy:%s/%s/d%d" % (intent, domain, difficulty),
        })
    return out
