# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Small helpers shared by the spec validators.

Each validator appends `Issue`s to a list it was handed rather than raising on
the first problem, so `Ruleset.from_spec` can report everything at once.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from fractions import Fraction

from evennia_rp_rules._numbers import to_fraction
from evennia_rp_rules.issues import Issue

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
KEY_HINT = "keys are lowercase slugs: letters, digits, '_' and '-'"


def malformed(issues: list[Issue], where: str, message: str, hint: str | None = None) -> None:
    issues.append(Issue("E001", f"{where}: {message}", hint))


def inconsistent(issues: list[Issue], where: str, message: str, hint: str | None = None) -> None:
    issues.append(Issue("E002", f"{where}: {message}", hint))


def require_mapping(value, issues: list[Issue], where: str) -> Mapping | None:
    if not isinstance(value, Mapping):
        malformed(issues, where, f"expected a mapping, got {type(value).__name__}")
        return None
    return value


def require_list(
    value, issues: list[Issue], where: str, *, allow_empty: bool = False
) -> list | None:
    if not isinstance(value, list | tuple):
        malformed(issues, where, f"expected a list, got {type(value).__name__}")
        return None
    if not value and not allow_empty:
        malformed(issues, where, "must not be empty")
        return None
    return list(value)


def require_key(value, issues: list[Issue], where: str) -> str | None:
    if not isinstance(value, str) or not KEY_RE.match(value):
        malformed(issues, where, f"invalid key {value!r}", KEY_HINT)
        return None
    return value


def require_text(value, issues: list[Issue], where: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        malformed(issues, where, f"expected non-empty text, got {value!r}")
        return None
    return value.strip()


def require_number(
    value, issues: list[Issue], where: str, *, minimum=None, strict=False
) -> Fraction | None:
    """Parse a number, optionally bounded below (`strict` makes the bound exclusive)."""
    try:
        number = to_fraction(value)
    except (TypeError, ValueError, ZeroDivisionError):
        malformed(issues, where, f"expected a number, got {value!r}")
        return None
    if minimum is not None:
        bound = to_fraction(minimum)
        if number < bound or (strict and number == bound):
            comparison = ">" if strict else ">="
            malformed(issues, where, f"must be {comparison} {minimum}, got {value!r}")
            return None
    return number


def text_aliases(value, issues: list[Issue], where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    items = require_list(value, issues, where, allow_empty=True)
    if items is None:
        return ()
    aliases = []
    for index, alias in enumerate(items):
        text = require_text(alias, issues, f"{where}[{index}]")
        if text is not None:
            aliases.append(text)
    return tuple(aliases)
