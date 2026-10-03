# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The sheet as a stat source for evennia_rp_rules checks.

Point the kernel at it:

    RP_RULES_SUBJECT_ADAPTER = "evennia_rp_chargen.subject.subject_adapter"

or call `subject_adapter()` from a game adapter that also handles NPC stat
blocks. The adapter builds a `ChargenSubject` on demand, so characters need no
typeclass changes, and uninstalling chargen can't break `Character`.
"""

from __future__ import annotations

from evennia_rp_chargen.models import CharacterBuild
from evennia_rp_chargen.stats import StatHandler
from evennia_rp_rules.checks import CheckError
from evennia_rp_rules.scales import Rating


class ChargenSubject:
    """A character's sheet, for checks.

    Ratings come from the sheet only once it's playable (finalized, or
    approved when approval is required); a draft raises a `CheckError`
    telling the player what to do.
    """

    def __init__(self, character, build: CharacterBuild | None = None):
        self.character = character
        self._build = build

    def __repr__(self) -> str:
        return f"<ChargenSubject {self.character}>"

    def __str__(self) -> str:
        return str(self.character.key)

    @property
    def build(self) -> CharacterBuild | None:
        if self._build is None:
            self._build = CharacterBuild.objects.filter(character_id=self.character.id).first()
        return self._build

    def get_rating(self, stat_key: str) -> Rating | None:
        build = self.build
        if build is None:
            return None
        if not build.is_playable:
            if build.is_draft:
                raise CheckError(
                    f"{self.character.key}'s sheet is still a draft. Finish it with +stats/finalize."
                )
            raise CheckError(f"{self.character.key}'s sheet is awaiting staff approval.")
        return StatHandler(self.character).get(stat_key)

    def get_modifiers(self, check) -> list:
        return []


def subject_adapter(obj) -> ChargenSubject | None:
    """`RP_RULES_SUBJECT_ADAPTER` hook: a subject for anything with a sheet."""
    if getattr(obj, "id", None) is None or not hasattr(obj, "attributes"):
        return None
    build = CharacterBuild.objects.filter(character_id=obj.id).first()
    return ChargenSubject(obj, build) if build is not None else None


__all__ = ["ChargenSubject", "subject_adapter"]
