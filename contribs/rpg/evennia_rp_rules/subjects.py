# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Subjects: whatever has stats.

The kernel never reads a character's attributes itself. Anything that can make
or oppose a check is reached through a **stat source**, an object with
`get_rating(stat_key)` and, optionally, `get_modifiers(check)`:

    class StatSource(Protocol):
        def get_rating(self, stat_key) -> Rating | None: ...
        def get_modifiers(self, check) -> Iterable[Modifier]: ...   # optional

`get_subject(obj)` finds one for any object:

1. an object that already is a stat source is used as it is;
2. otherwise `settings.RP_RULES_SUBJECT_ADAPTER`, a dotted path to a callable
   `adapter(obj) -> StatSource | None`, is asked (chargen's sheet adapter,
   or a game function that picks between sheets and NPC stat blocks);
3. a plain mapping (`{"charisma": "B++"}`) becomes a `DictStatSource`.

So characters need no typeclass changes, and an NPC can be a stat block.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from evennia_rp_rules._config import resolve_dotted, setting
from evennia_rp_rules.scales import Rating

if TYPE_CHECKING:
    from evennia_rp_rules.checks import Check
    from evennia_rp_rules.ruleset import Ruleset


@runtime_checkable
class StatSource(Protocol):
    """Anything with stats. `get_modifiers(check)` is optional.

    `get_rating()` returns a `Rating`, rating text such as `"B++"` (parsed on
    the stat's scale), or `None` when the subject lacks that stat.
    """

    def get_rating(self, stat_key: str) -> Rating | str | None: ...


class DictStatSource:
    """Stats from a plain mapping: an NPC stat block, a test dummy, a one-off.

    Args:
        ratings: `{stat_key: rating}`, each a `Rating` or text such as
            `"B++"`, parsed on that stat's scale when first asked for.
        modifiers: Modifiers offered to every check this subject is part of
            (each still decides for itself whether it applies).
        name: Shown in error messages.
        ruleset: The ruleset to parse text with; `get_ruleset()` if omitted.
    """

    def __init__(
        self,
        ratings: Mapping[str, Rating | str] | None = None,
        *,
        modifiers: Iterable = (),
        name: str = "",
        ruleset: Ruleset | None = None,
    ):
        self.ratings = dict(ratings or {})
        self.modifiers = list(modifiers)
        self.name = name
        self.ruleset = ruleset

    def __repr__(self) -> str:
        return f"<DictStatSource {self.name or '?'} {sorted(self.ratings)}>"

    def __str__(self) -> str:
        return self.name or "stat block"

    def get_rating(self, stat_key: str) -> Rating | None:
        value = self.ratings.get(stat_key)
        if value is None or isinstance(value, Rating):
            return value
        from evennia_rp_rules.ruleset import get_ruleset

        ruleset = self.ruleset or get_ruleset()
        stat = ruleset.stats.get(stat_key)
        if stat is None:
            return None
        return stat.scale.parse(value)

    def get_modifiers(self, check: Check) -> list:
        return list(self.modifiers)


def get_subject(obj) -> StatSource | None:
    """The stat source for `obj`, or `None` if it has no stats.

    Raises:
        django.core.exceptions.ImproperlyConfigured: If
            `RP_RULES_SUBJECT_ADAPTER` names something that can't be imported.
    """
    if obj is None:
        return None
    if isinstance(obj, StatSource):
        return obj
    path = setting("RP_RULES_SUBJECT_ADAPTER")
    if path:
        subject = _adapter(path)(obj)
        if subject is not None:
            return subject
    if isinstance(obj, Mapping):
        return DictStatSource(obj)
    return None


def _adapter(path: str):
    try:
        return resolve_dotted(path)
    except (ImportError, AttributeError) as exc:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(
            f"RP_RULES_SUBJECT_ADAPTER: can't import {path!r}: {exc}"
        ) from exc


def modifiers_of(subject, check: Check) -> list:
    """The subject's modifiers for `check`, or none if it offers none."""
    method = getattr(subject, "get_modifiers", None)
    return list(method(check) or ()) if callable(method) else []


__all__ = ["DictStatSource", "StatSource", "get_subject", "modifiers_of"]
