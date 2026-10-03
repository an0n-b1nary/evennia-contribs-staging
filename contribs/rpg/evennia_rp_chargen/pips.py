# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Pip policy: how much edge and weakness a character may carry.

Edge is a budget (`RP_CHARGEN_PIP_BUDGET` across all stats, at most
`RP_CHARGEN_PIP_CAP` on one). Weakness is free, a roleplaying choice, capped
per stat by `RP_CHARGEN_WEAKNESS_CAP`, and refunds nothing: taking weakness
never buys more edge. Both caps default to what the stat's scale allows, and
can only lower it.

Edge and weakness may sit on the same stat (counterbalancing gear, a mixed
gift); the resolver uses the net count, and the sheet shows both.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from evennia_rp_chargen import conf
from evennia_rp_rules.ruleset import Ruleset
from evennia_rp_rules.scales import Rating, Scale


@dataclass(frozen=True)
class PipPolicy:
    """Edge budget and caps.

    Attributes:
        edge_budget: Total edge across all stats; `None` for no budget.
        edge_cap: Most edge on one stat; `None` for the scale's maximum.
        weakness_cap: Most weakness on one stat; `None` for the scale's maximum.
    """

    edge_budget: int | None = None
    edge_cap: int | None = None
    weakness_cap: int | None = None

    @classmethod
    def from_settings(cls) -> PipPolicy:
        return cls(
            edge_budget=conf.get("RP_CHARGEN_PIP_BUDGET"),
            edge_cap=conf.get("RP_CHARGEN_PIP_CAP"),
            weakness_cap=conf.get("RP_CHARGEN_WEAKNESS_CAP"),
        )

    def edge_limit(self, scale: Scale) -> int:
        return scale.max_edge if self.edge_cap is None else min(self.edge_cap, scale.max_edge)

    def weakness_limit(self, scale: Scale) -> int:
        if self.weakness_cap is None:
            return scale.max_weakness
        return min(self.weakness_cap, scale.max_weakness)

    def edge_spent(self, ratings: Mapping[str, Rating | None]) -> int:
        return sum(r.edge for r in ratings.values() if r is not None)

    def edge_left(self, ratings: Mapping[str, Rating | None]) -> int | None:
        if self.edge_budget is None:
            return None
        return self.edge_budget - self.edge_spent(ratings)

    def errors(self, ratings: Mapping[str, Rating | None], ruleset: Ruleset) -> list[str]:
        """Everything about these ratings' pips that the policy forbids."""
        edge_noun = conf.get("RP_CHARGEN_PIP_NOUN")
        weakness_noun = conf.get("RP_CHARGEN_WEAKNESS_NOUN")
        problems = []
        for key, rating in ratings.items():
            if rating is None:
                continue
            name = ruleset.stats[key].name
            limit = self.edge_limit(rating.scale)
            if rating.edge > limit:
                problems.append(f"{name} may carry at most {limit} {edge_noun}, not {rating.edge}.")
            limit = self.weakness_limit(rating.scale)
            if rating.weakness > limit:
                problems.append(
                    f"{name} may carry at most {limit} {weakness_noun}, not {rating.weakness}."
                )
        spent = self.edge_spent(ratings)
        if self.edge_budget is not None and spent > self.edge_budget:
            problems.append(f"That's {spent} {edge_noun} in all, and you have {self.edge_budget}.")
        return problems


__all__ = ["PipPolicy"]
