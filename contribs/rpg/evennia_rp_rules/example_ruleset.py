# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""A small, neutral default ruleset.

Used when `RP_RULES_RULESET` isn't set, and as a worked example of the spec.
Copy it into your game (say `world/ruleset.py`), rename things, and tune the
numbers with the odds tool:

    python -m evennia_rp_rules.odds --ruleset world.ruleset --scores
    python -m evennia_rp_rules.odds --ruleset world.ruleset --matrix success --pips -2,0,3,5

How the numbers fit together:

- Rungs sit 20 points apart. Edge is worth at most 15 and weakness at most 17
  (before rung factors), so neither can carry a rating across a rung; the
  ruleset fails validation (E003) if you change that by accident.
- Edge pips depreciate (5, 4, 3, 2, 1) and are worth less on the upper rungs
  (factors 1 down to 0.7). Weakness pips bite progressively harder (2 to 5).
- Noise is `3d20-3d20`, a bell from -57 to +57 centred on 0. An even match
  succeeds (Partial Success or better) about half the time (51.4%); one rung
  down, under one time in ten (8.6%).
- Whole-point dice only "see" whole points, so every pip stays worth at least a
  point after rung factors; otherwise it would do nothing (warning W001).
"""

RULESET = {
    "version": "example-1",
    "scales": {
        "rank": {
            "name": "Rank",
            "rungs": [
                {"key": "novice", "label": "Novice", "score": 0},
                {"key": "adept", "label": "Adept", "score": 20},
                {"key": "expert", "label": "Expert", "score": 40, "edge_factor": 0.9},
                {"key": "master", "label": "Master", "score": 60, "edge_factor": 0.8},
                {"key": "legend", "label": "Legend", "score": 80, "edge_factor": 0.7},
            ],
            "edge": [5, 4, 3, 2, 1],
            "weakness": [2, 3, 3, 4, 5],
        },
    },
    "stats": [
        {"key": "might", "name": "Might", "description": "Strength and stamina."},
        {"key": "finesse", "name": "Finesse", "description": "Agility and precision."},
        {"key": "wits", "name": "Wits", "description": "Learning, perception, quick thinking."},
        {
            "key": "presence",
            "name": "Presence",
            "description": "Charm, nerve, force of personality.",
        },
    ],
    "tags": [
        {"key": "athletics", "name": "Athletics"},
        {"key": "lore", "name": "Lore"},
        {"key": "persuasion", "name": "Persuasion"},
        {"key": "stealth", "name": "Stealth"},
    ],
    "outcomes": [
        {"key": "critical_failure", "label": "Critical Failure", "degree": -2, "success": False},
        {"key": "failure", "label": "Failure", "degree": -1, "success": False},
        {"key": "partial_success", "label": "Partial Success", "degree": 0, "success": True},
        {"key": "success", "label": "Success", "degree": 1, "success": True},
        {"key": "critical_success", "label": "Critical Success", "degree": 2, "success": True},
    ],
    "resolver": {
        "path": "evennia_rp_rules.resolvers.GradedResolver",
        "params": {
            "noise": "3d20-3d20",
            "bands": [
                {"outcome": "critical_success", "min": 25},
                {"outcome": "success", "min": 8},
                {"outcome": "partial_success", "min": 0},
                {"outcome": "failure", "min": -20},
                {"outcome": "critical_failure"},
            ],
        },
    },
}
