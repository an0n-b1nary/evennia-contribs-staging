# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Stat allocation: how a draft sheet's rungs may be chosen.

`settings.RP_CHARGEN_ALLOCATION` picks one:

    {"path": "evennia_rp_chargen.allocation.PointBuyAllocation",
     "params": {"costs": {"d": 0, "c": 1, "b": 2, "a": 4, "s": 7}, "budget": 14}}

    {"path": "evennia_rp_chargen.allocation.ArrayAllocation",
     "params": {"array": ["a", "b", "b", "c", "c", "d", "d"]}}

    {"path": "evennia_rp_chargen.allocation.FreeAllocation"}   # the default

An allocation reports two kinds of problem. **Errors** make a change
impossible (overspending, using a rung more often than the array allows), so
the change is refused. **To-dos** only stop finalising (stats still unset,
array slots still unused). Allocation looks only at rungs; edge and weakness
are the pip policy's business (`pips`).

Allocation points exist only while a sheet is a draft; they aren't XP, and
the sheet stops showing them once it's finalized.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from evennia_rp_chargen import conf
from evennia_rp_rules.ruleset import Ruleset
from evennia_rp_rules.scales import Rating


@dataclass
class AllocationReport:
    """What an allocation thinks of a set of ratings.

    Attributes:
        errors: Problems that make these ratings impossible.
        todo: What's left before the sheet can be finalized.
        spent, budget: Points, for allocations that count them.
        summary: One line for the sheet ("11 of 14 build points spent").
    """

    errors: list[str] = field(default_factory=list)
    todo: list[str] = field(default_factory=list)
    spent: int | None = None
    budget: int | None = None
    summary: str = ""

    @property
    def can_finalize(self) -> bool:
        return not self.errors and not self.todo


@runtime_checkable
class Allocation(Protocol):
    def check(self, ratings: Mapping[str, Rating | None], ruleset: Ruleset) -> AllocationReport:
        """Judge `{stat_key: rating or None}` for every ruleset stat."""
        ...

    def config_problems(self, ruleset: Ruleset) -> list[str]:
        """Ways this allocation doesn't fit `ruleset` (shown by the system check)."""
        ...


def _unset_todo(ratings, ruleset: Ruleset) -> list[str]:
    unset = [ruleset.stats[key].name for key, rating in ratings.items() if rating is None]
    return [f"Set {', '.join(unset)}."] if unset else []


class FreeAllocation:
    """Any rungs at all; only requires every stat to be set before finalising."""

    def __init__(self, **params):
        if params:
            raise TypeError(f"FreeAllocation takes no parameters, got {sorted(params)}")

    def check(self, ratings, ruleset) -> AllocationReport:
        return AllocationReport(todo=_unset_todo(ratings, ruleset))

    def config_problems(self, ruleset) -> list[str]:
        return []


class PointBuyAllocation:
    """Each rung costs points; the total may not exceed the budget.

    Args:
        costs: `{rung_key: points}` for every rung of every scale a stat uses.
        budget: Points available.
        require_full: Refuse to finalize with points left over (default: a
            cheaper build is just a weaker one).
    """

    def __init__(self, costs: Mapping[str, int], budget: int, require_full: bool = False):
        self.costs = dict(costs)
        self.budget = budget
        self.require_full = require_full

    def config_problems(self, ruleset) -> list[str]:
        problems = []
        for value in [*self.costs.values(), self.budget]:
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                problems.append(
                    f"costs and budget must be whole numbers of at least 0, got {value!r}"
                )
        rungs = {rung.key for stat in ruleset.stats.values() for rung in stat.scale.rungs}
        missing = sorted(rungs - set(self.costs))
        if missing:
            problems.append(f"no cost for rung(s) {', '.join(missing)}")
        return problems

    def cost(self, ratings) -> int:
        return sum(self.costs.get(r.rung.key, 0) for r in ratings.values() if r is not None)

    def check(self, ratings, ruleset) -> AllocationReport:
        noun = conf.get("RP_CHARGEN_ALLOCATION_NOUN")
        spent = self.cost(ratings)
        report = AllocationReport(
            spent=spent,
            budget=self.budget,
            todo=_unset_todo(ratings, ruleset),
            summary=f"{spent} of {self.budget} {noun} spent",
        )
        if spent > self.budget:
            report.errors.append(f"That costs {spent} {noun}, and you have {self.budget}.")
        elif self.require_full and spent < self.budget:
            report.todo.append(f"Spend your remaining {self.budget - spent} {noun}.")
        return report


class ArrayAllocation:
    """Stats take the rungs in a fixed list, one each, in any order.

    Args:
        array: Rung keys, one per stat (`["a", "b", "b", "c", "c", "d", "d"]`).
    """

    def __init__(self, array):
        self.array = [str(key) for key in array]

    def config_problems(self, ruleset) -> list[str]:
        problems = []
        if len(self.array) != len(ruleset.stats):
            problems.append(
                f"the array has {len(self.array)} entries for {len(ruleset.stats)} stats"
            )
        rungs = {rung.key for stat in ruleset.stats.values() for rung in stat.scale.rungs}
        unknown = sorted(set(self.array) - rungs)
        if unknown:
            problems.append(f"unknown rung(s) in the array: {', '.join(unknown)}")
        return problems

    def check(self, ratings, ruleset) -> AllocationReport:
        available = Counter(self.array)
        used = Counter(r.rung.key for r in ratings.values() if r is not None)
        labels = {
            rung.key: rung.label for stat in ruleset.stats.values() for rung in stat.scale.rungs
        }
        report = AllocationReport(todo=_unset_todo(ratings, ruleset))
        for key, count in sorted(used.items()):
            if count > available[key]:
                report.errors.append(
                    f"Only {available[key]} stat(s) may be {labels.get(key, key)}, not {count}."
                )
        left = available - used
        unassigned = []
        for key in self.array:  # array order, each leftover slot once
            if left[key] > 0:
                unassigned.append(labels.get(key, key))
                left[key] -= 1
        report.summary = f"Unassigned: {' '.join(unassigned) or 'none'}"
        return report


def get_allocation() -> Allocation:
    """The allocation named by `settings.RP_CHARGEN_ALLOCATION`.

    Raises:
        django.core.exceptions.ImproperlyConfigured: If it can't be built.
    """
    from django.core.exceptions import ImproperlyConfigured

    from evennia_links import resolve_dotted

    config = conf.get("RP_CHARGEN_ALLOCATION") or {}
    if not isinstance(config, Mapping):
        raise ImproperlyConfigured("RP_CHARGEN_ALLOCATION must be a dict with 'path' and 'params'")
    path = config.get("path", conf.DEFAULTS["RP_CHARGEN_ALLOCATION"]["path"])
    try:
        cls = resolve_dotted(path)
        return cls(**dict(config.get("params") or {}))
    except (ImportError, AttributeError, TypeError) as exc:
        raise ImproperlyConfigured(f"RP_CHARGEN_ALLOCATION: can't build {path!r}: {exc}") from exc


__all__ = [
    "Allocation",
    "AllocationReport",
    "ArrayAllocation",
    "FreeAllocation",
    "PointBuyAllocation",
    "get_allocation",
]
