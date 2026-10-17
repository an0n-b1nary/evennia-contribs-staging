# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Generic niches and demonstration prose; games supply their own vocabulary."""

BOOK_NAME = "a sample field book"
BOOK_DESC = "A small bound notebook with a plain paper cover."
BOOK_TEXT = "Field notes: the market opens onto the common road."
BOOK_DETAILS = {"cover": "A tiny stitched map marks the cloth cover."}
BOOK_SENSES = {"smell": "Dry paper and cedar.", "touch": "Soft cloth over stiff boards."}
PAGED_BOOK_NAME = "a sample travel book"
JOURNAL_NAME = "a sample field journal"
EDITION_NAME = "a sample journal edition"
LETTER_NAME = "a sample sealed letter"
SIGNET_NAME = "a sample rose signet"
SEAL_DESIGN = "The Courier's Rose"
LETTER_TEXT = "Meet by the well when the market closes."
LORE_BOOK_NAME = "a sample annotated guide"
TOME_NAME = "an old market chronicle"
BOOK_PAGES = [
    {"title": "Market Row", "text": "Stalls line the road beside the well."},
    {"title": "The Common Road", "text": "The road bends towards a stand of trees."},
]
CLOAK_NAME = "a sample woven cloak"
CLOAK_DESC = "A grey cloak with a simple woven border."
CLOAK_LINE = "a grey cloak with a woven border"
CLOAK_STATES = {
    "default": "hood down",
    "variants": {
        "hood down": {"worn_line": CLOAK_LINE},
        "hood up": {
            "worn_line": "a grey cloak with its hood raised",
            "description": "A grey cloak with a raised hood and a simple woven border.",
        },
    },
}
LUTE_NAME = "a sample carved lute"
LUTE_DESC = "A small lute carved from pale wood."
LUTE_MODE = "A bright melody rings from the little lute."
LUTE_SENSES = {"sound": "The loose strings hum faintly.", "touch": "Smooth, polished wood."}
FIXTURE_NAME = "a sample brass lantern"
FIXTURE_DESC = "A brass lantern with a beeswax candle."
FIXTURE_LINE = "Warm lamplight falls across the market stalls."
FIXTURE_SMELL = "A faint scent of beeswax."
FIXTURE_SOUND = "The soft hiss of a candlewick."
COMPANION_NAME = "a sample clockwork bird"
COMPANION_DESC = "A little brass bird with decorative clockwork feathers."
COMPANION_TRICK = "The little brass bird bows and spreads its wings."


def catalog():
    wearable = ["weaving", "jewellery", "smithing"]
    return (
        [
            {
                "key": key,
                "name": name,
                "description": description,
                "behaviours": (
                    ["wearable"]
                    + (
                        ["modifier_dye"]
                        if key == "weaving"
                        else ["modifier_engrave"]
                        if key == "smithing"
                        else []
                    )
                )
                if key in wearable
                else ["readable"],
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
        + [
            {
                "key": key,
                "name": name,
                "description": description,
                "behaviours": [behaviour],
                "input_categories": [category, "essences"]
                if key in ("music", "decoration")
                else [category],
                "unlock_money": 100,
                "unlock_resources": {category: 3},
            }
            for key, name, description, behaviour, category in (
                (
                    "music",
                    "Artisan",
                    "Instruments, games and flavour readings.",
                    "activatable",
                    "materials",
                ),
                (
                    "decoration",
                    "Decorator",
                    "Fixtures and sensory room layers.",
                    "installable",
                    "materials",
                ),
                (
                    "cooking",
                    "Cook",
                    "Food, drinks and cosmetic tonics.",
                    "consumable",
                    "provisions",
                ),
                (
                    "illusions",
                    "Illusionist",
                    "Fireworks and short-lived illusions.",
                    "broadcast",
                    "essences",
                ),
            )
        ]
        + [
            {
                "key": "enchanting",
                "name": "Enchanter",
                "description": "Cosmetic auras, marks and selected-layer undoing.",
                "behaviours": ["modifier_aura", "modifier_mark", "modifier_undo"],
                "input_categories": ["essences"],
                "unlock_money": 100,
                "unlock_resources": {"essences": 3},
            },
            {
                "key": "companions",
                "name": "Companion Maker",
                "description": "Cosmetic pets, familiars and animated objects.",
                "behaviours": ["companion"],
                "input_categories": ["materials", "essences"],
                "unlock_money": 100,
                "unlock_resources": {"materials": 3},
            },
        ]
    )
