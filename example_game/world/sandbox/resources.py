# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Generic resource catalogue: terrain variety, common pool and rare stock."""


def catalog():
    return [
        {
            "key": "timber",
            "name": "Timber",
            "category": "materials",
            "terrains": ["forest"],
            "weight": 2,
        },
        {
            "key": "stone",
            "name": "Stone",
            "category": "materials",
            "terrains": ["hills"],
            "weight": 2,
        },
        {"key": "scrap", "name": "Scrap", "category": "materials", "terrains": ["urban"]},
        {"key": "grain", "name": "Grain", "category": "provisions", "terrains": []},
        {"key": "fish", "name": "Fish", "category": "provisions", "terrains": ["water"]},
        {"key": "ember", "name": "Ember essence", "category": "essences", "terrains": ["hills"]},
        {"key": "tide", "name": "Tide essence", "category": "essences", "terrains": ["water"]},
        {
            "key": "rare-crystal",
            "name": "Rare crystal",
            "category": "essences",
            "terrains": [],
            "in_trickle": False,
        },
    ]
