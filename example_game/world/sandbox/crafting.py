# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Generic niches and demonstration prose; games supply their own vocabulary."""

BOOK_NAME = "a sample field book"
BOOK_DESC = "A small bound notebook with a plain paper cover."
BOOK_TEXT = "Field notes: the market opens onto the common road."
CLOAK_NAME = "a sample woven cloak"
CLOAK_DESC = "A grey cloak with a simple woven border."
CLOAK_LINE = "a grey cloak with a woven border"


def catalog():
    wearable = ["weaving", "jewellery", "smithing"]
    return [
        {
            "key": key,
            "name": name,
            "description": description,
            "behaviours": ["wearable"] if key in wearable else ["readable"],
            "input_categories": ["materials", "essences"] if key in wearable else ["materials"],
            "unlock_money": 100,
            "unlock_resources": {"materials": 3},
        }
        for key, name, description in (
            ("weaving", "Weaver", "Garments, cloth and trim."),
            ("jewellery", "Jeweller", "Rings, pendants and decorative stones."),
            ("smithing", "Smith", "Cosmetic arms, armour and metalwork."),
            ("writing", "Scribe", "Books, letters and field notes."),
        )
    ]
