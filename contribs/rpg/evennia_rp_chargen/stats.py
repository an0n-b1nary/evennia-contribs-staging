# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Stat storage: a character's ratings, in one Attribute.

The Attribute `rp_stats` (category `rp_chargen`) holds rung *keys* and pip
counts, never scores:

    {"_v": 1, "charisma": {"rung": "b", "edge": 3, "weak": 1}, ...}

so retuning the ruleset's numbers never touches a sheet. `StatHandler` turns
that into `Rating`s on the current ruleset. It enforces only what the scale
itself requires (a known rung, pip counts within the curves); allocation, pip
budgets and locks are policies, applied by `services`.
"""

from __future__ import annotations

import logging

from evennia_rp_rules.ruleset import Ruleset, StatDef, get_ruleset
from evennia_rp_rules.scales import Rating

ATTR_KEY = "rp_stats"
ATTR_CATEGORY = "rp_chargen"
FORMAT_VERSION = 1

logger = logging.getLogger("evennia")


class StatHandler:
    """Read and write one character's ratings.

    Args:
        obj: The character.
        ruleset: Defaults to `get_ruleset()`.
    """

    def __init__(self, obj, ruleset: Ruleset | None = None):
        self.obj = obj
        self._ruleset = ruleset

    @property
    def ruleset(self) -> Ruleset:
        return self._ruleset or get_ruleset()

    # -- storage ------------------------------------------------------------

    def _load(self) -> dict:
        raw = self.obj.attributes.get(ATTR_KEY, category=ATTR_CATEGORY, default=None) or {}
        return {
            key: dict(value)
            for key, value in dict(raw).items()
            if key != "_v" and hasattr(value, "items")
        }

    def _save(self, data: dict) -> None:
        self.obj.attributes.add(ATTR_KEY, {"_v": FORMAT_VERSION, **data}, category=ATTR_CATEGORY)

    def raw(self) -> dict:
        """The stored entries, as plain dicts, keyed by stat."""
        return self._load()

    # -- reading ------------------------------------------------------------

    def _stat(self, stat: StatDef | str) -> StatDef:
        if isinstance(stat, StatDef):
            return stat
        found = self.ruleset.stats.get(stat)
        if found is None:
            raise KeyError(f"unknown stat {stat!r}")
        return found

    def get(self, stat: StatDef | str) -> Rating | None:
        """The rating for `stat`, or `None` if unset or no longer valid.

        An entry goes invalid when the ruleset changes under it (a rung
        removed, a pip curve shortened); `problems()` lists those for staff.
        """
        stat = self._stat(stat)
        entry = self._load().get(stat.key)
        if entry is None:
            return None
        try:
            return _rating(stat, entry)
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning(
                "rp_chargen: %s's %s entry %r is invalid: %s", self.obj, stat.key, entry, exc
            )
            return None

    def ratings(self) -> dict[str, Rating | None]:
        """Every ruleset stat, in ruleset order, to its rating or `None`."""
        return {key: self.get(stat) for key, stat in self.ruleset.stats.items()}

    def unset(self) -> list[StatDef]:
        """Ruleset stats without a (valid) rating."""
        return [stat for key, stat in self.ruleset.stats.items() if self.get(stat) is None]

    def problems(self) -> list[str]:
        """Stored entries that no longer fit the ruleset."""
        found = []
        for key, entry in self._load().items():
            stat = self.ruleset.stats.get(key)
            if stat is None:
                found.append(f"'{key}' is not a stat in the current ruleset")
                continue
            try:
                _rating(stat, entry)
            except (KeyError, ValueError, TypeError) as exc:
                found.append(f"{stat.name}: {exc}")
        return found

    def edge_total(self) -> int:
        return sum(r.edge for r in self.ratings().values() if r is not None)

    # -- writing ------------------------------------------------------------

    def set(self, stat: StatDef | str, rating: Rating) -> Rating:
        """Store `rating` for `stat`, rung and pips both.

        Raises:
            ValueError: If `rating` isn't on the stat's scale.
        """
        stat = self._stat(stat)
        if rating.scale.key != stat.scale.key:
            raise ValueError(f"{stat.name} is rated on {stat.scale.name}, not {rating.scale.name}")
        rating = stat.scale.rating(rating.rung.key, rating.edge, rating.weakness)
        data = self._load()
        data[stat.key] = {"rung": rating.rung.key, "edge": rating.edge, "weak": rating.weakness}
        self._save(data)
        return rating

    def set_rung(self, stat: StatDef | str, rung: str) -> Rating:
        """Set the rung (a key, label or alias), keeping any pips.

        Raises:
            ValueError: Unknown rung (the message lists the valid ones).
        """
        stat = self._stat(stat)
        try:
            new_rung = stat.scale.rung(rung)
        except KeyError as exc:
            raise ValueError(exc.args[0]) from None
        current = self.get(stat)
        edge, weakness = (current.edge, current.weakness) if current else (0, 0)
        return self.set(stat, stat.scale.rating(new_rung, edge, weakness))

    def set_pips(
        self, stat: StatDef | str, *, edge: int | None = None, weakness: int | None = None
    ) -> Rating:
        """Change pip counts on a rated stat.

        Raises:
            LookupError: If the stat has no rung yet.
            ValueError: If a count is negative or beyond the scale's curve.
        """
        stat = self._stat(stat)
        current = self.get(stat)
        if current is None:
            raise LookupError(f"{stat.name} has no rating yet")
        return self.set(stat, current.with_pips(edge=edge, weakness=weakness))

    def clear(self, stat: StatDef | str) -> None:
        stat = self._stat(stat)
        data = self._load()
        if data.pop(stat.key, None) is not None:
            self._save(data)

    def wipe(self) -> None:
        """Remove every rating."""
        self.obj.attributes.remove(ATTR_KEY, category=ATTR_CATEGORY)


def _rating(stat: StatDef, entry: dict) -> Rating:
    return stat.scale.rating(
        str(entry["rung"]), int(entry.get("edge", 0)), int(entry.get("weak", 0))
    )


__all__ = ["ATTR_CATEGORY", "ATTR_KEY", "StatHandler"]
