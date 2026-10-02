# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Ruleset validation issues.

Validation is Django-free so the odds tool and plain unit tests can run it;
the app's system check (which needs Django) only translates these into
`django.core.checks` messages.

Issue ids:

    E001  malformed spec (missing/ill-typed fields, duplicates, bad keys)
    E002  inconsistent spec (unknown references, bad resolver parameters)
    E003  pips can cross a rung (edge reaches the next rung up, or weakness
          reaches the next rung down)
    W001  a pip changes no odds (the noise can't resolve its value)
"""

from __future__ import annotations

from dataclasses import dataclass

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    """One validation finding.

    Attributes:
        id: Short id such as `"E003"`; the system check prefixes the app label.
        message: What's wrong, naming the offending part of the spec.
        hint: How to fix it, when there's something useful to say.
        level: `ERROR` or `WARNING`.
    """

    id: str
    message: str
    hint: str | None = None
    level: str = ERROR

    def __str__(self) -> str:
        text = f"{self.id}: {self.message}"
        return f"{text} (hint: {self.hint})" if self.hint else text


class RulesetError(ValueError):
    """A ruleset spec failed validation.

    Attributes:
        issues: Every error-level `Issue` found (validation doesn't stop at the
            first one, so a ruleset author sees the whole list at once).
    """

    def __init__(self, issues: list[Issue]):
        self.issues = list(issues)
        summary = "; ".join(str(issue) for issue in self.issues) or "invalid ruleset"
        super().__init__(summary)
