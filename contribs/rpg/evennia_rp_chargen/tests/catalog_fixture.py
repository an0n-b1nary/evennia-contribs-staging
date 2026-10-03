# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""A small ability catalog and a fake XP ledger for the ability suites.

TEST_RULESET's tags are Climbing and Riddles (domains) and Fire (an element).

    Domain Expertise    template per domain, 3 XP, levels 1-3, 10 loadout,
                        +2 on own tagged checks, +1 per level
    Domain Ineptitude   free flaw per domain, -2 on own tagged checks
    Domain Vulnerability free flaw per domain, -2 when an opposing check is tagged
    Lucky               staff-only, 5 loadout, +1 on everything
    Cursed              staff-only flaw, -1 on everything
"""

from __future__ import annotations

from decimal import Decimal

from evennia_rp_chargen.ledger import InsufficientXP

CATALOG = [
    {
        "key": "domain-expertise",
        "name": "Domain Expertise",
        "category": "domain",
        "tag_kind": "domain",
        "acquisition": "xp",
        "xp_cost": 3,
        "max_level": 3,
        "budget_cost": 10,
        "effects": [{"kind": "tag_bonus", "tags": ["@tag"], "score": 2, "per_level": 1}],
    },
    {
        "key": "domain-ineptitude",
        "name": "Domain Ineptitude",
        "category": "domain",
        "tag_kind": "domain",
        "is_flaw": True,
        "acquisition": "free",
        "effects": [{"kind": "tag_bonus", "tags": ["@tag"], "score": -2}],
    },
    {
        "key": "domain-vulnerability",
        "name": "Domain Vulnerability",
        "category": "domain",
        "tag_kind": "domain",
        "is_flaw": True,
        "acquisition": "free",
        "effects": [{"kind": "tag_bonus", "tags": ["@tag"], "score": -2, "match": "opposing"}],
    },
    {
        "key": "lucky",
        "name": "Lucky",
        "acquisition": "staff",
        "budget_cost": 5,
        "effects": [{"kind": "score_bonus", "score": 1}],
    },
    {
        "key": "cursed",
        "name": "Cursed",
        "is_flaw": True,
        "acquisition": "staff",
        "effects": [{"kind": "score_bonus", "score": -1}],
    },
]

CATALOG_SETTINGS = {
    "RP_CHARGEN_CATALOG_SEED": f"{__name__}.CATALOG",
    "RP_CHARGEN_LOADOUT_BUDGET": 20,
    "RP_CHARGEN_STARTING_ALLOWANCE": 5,
    "RP_CHARGEN_UPGRADE_COST": {"base": 2, "factor": 2},
}


class FakeLedger:
    """XP balances in memory, keyed by character id. Spends are idempotent on ref."""

    balances: dict[int, Decimal] = {}  # noqa: RUF012
    spends: dict[str, tuple[int, Decimal]] = {}  # noqa: RUF012

    @classmethod
    def reset(cls, **balances):
        cls.balances = {int(k): Decimal(v) for k, v in balances.items()}
        cls.spends = {}

    def balance(self, character):
        return self.balances.get(character.id, Decimal(0))

    def spend(self, character, amount, *, ref_key, reason=""):
        if ref_key in self.spends:
            return
        if self.balance(character) < amount:
            raise InsufficientXP(f"{character} has {self.balance(character)}, needs {amount}")
        self.balances[character.id] = self.balance(character) - amount
        self.spends[ref_key] = (character.id, Decimal(amount))

    def refund(self, character, *, ref_key):
        entry = self.spends.pop(ref_key, None)
        if entry is None:
            return Decimal(0)
        self.balances[character.id] = self.balance(character) + entry[1]
        return entry[1]
