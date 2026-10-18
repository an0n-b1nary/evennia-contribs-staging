# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Settings-safe Pattern proposal form for JOBS_REQUEST_FORMS; no model or registry imports."""

FORM_KEY = "pattern"
FORM = {
    "label": "Propose a Pattern",
    "description": (
        "Propose crafter knowledge, such as a recipe, schematic or method. If staff "
        "approve, the Pattern starts Spreading and you know it."
    ),
    "questions": [
        {"key": "name", "label": "Pattern name", "type": "text", "max_length": 80},
        {
            "key": "description",
            "label": "Description",
            "help_text": "Shown to players in +pattern/info.",
            "max_length": 2000,
        },
        {"key": "origin", "label": "Where does it come from in the setting?"},
        {
            "key": "niches",
            "label": "Which niches can use it?",
            "type": "text",
            "help_text": "Niche names or keys, separated by commas.",
            "max_length": 500,
        },
        {
            "key": "recognisable",
            "label": "What makes work in it recognisable?",
            "help_text": "Items worked in it carry a system hallmark naming the Pattern.",
        },
        {
            "key": "combination",
            "label": "Requested combination",
            "required": False,
            "help_text": (
                "Optional: a lifecycle and verbs it should unlock, such as wearable + readable. "
                "Staff only open combinations the game has tested."
            ),
        },
        {
            "key": "reuse",
            "label": (
                "I acknowledge that content I contribute to this Pattern may be reused in a "
                "later game or storyline. Reuse is not guaranteed."
            ),
            "type": "boolean",
        },
    ],
}
