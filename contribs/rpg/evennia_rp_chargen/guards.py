# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Change guards: other apps may refuse a build change before it's written.

Every service that changes a sheet (ratings and pips, the loadout, flaws, and
staff grants, revokes and rating edits) describes the change as a
`BuildChange` and sends `build_change_requested`. It does so after its own
rules pass and before anything is written. A partner app connects a receiver
in its `ready()`; chargen never imports the partner.

    # A partner app, in its AppConfig.ready():
    from evennia_rp_chargen.guards import UNEQUIP, build_change_requested

    def keep_gear_attuned(sender, change, **kwargs):
        if change.kind == UNEQUIP and gear_needs(change.character, change.ability):
            return "Your Cursed Axe needs Rage equipped. Remove the axe first."
        return None

    build_change_requested.connect(keep_gear_attuned, dispatch_uid="mygear.guard")

Contract for receivers:

- Return None (or "") to allow the change, or a message fit to show the player
  to refuse it. A list of messages also refuses. Every refusal is shown.
- Staff changes are asked too, and there is no override. A guard keeps
  something true about the build; staff settle a conflict the way a player
  would, by first undoing whatever depends on the build.
- A receiver that raises, or returns anything else, refuses the change and is
  logged. A broken guard must not wave changes through.
- Don't write anything. A guard is asked, and the change can still fail after
  it answers (an XP payment, a concurrent edit).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.dispatch import Signal

if TYPE_CHECKING:
    from evennia_rp_chargen.models import AbilityDefinition, CharacterAbility, TagDefinition
    from evennia_rp_rules.ruleset import StatDef
    from evennia_rp_rules.scales import Rating

logger = logging.getLogger("evennia")

build_change_requested = Signal()  # kwargs: change (a BuildChange)

# What a change does. RATING covers rungs and pips; the rest are ability changes.
RATING = "rating"
EQUIP = "equip"
UNEQUIP = "unequip"
ACQUIRE = "acquire"
UPGRADE = "upgrade"
TAKE_FLAW = "take_flaw"
REMOVE_FLAW = "remove_flaw"
GRANT = "grant"
REVOKE = "revoke"

GUARD_FAILED = (
    "That change couldn't be checked just now, so nothing changed. "
    "Tell staff if it keeps happening."
)


@dataclass(frozen=True)
class BuildChange:
    """One proposed change to a character's build.

    Attributes:
        character: Whose build changes.
        kind: One of the kinds above.
        stat, before, after: For RATING, the stat and its rating before and
            after the change (None: unset).
        ability, tag: For the ability kinds, the definition and, for a
            template, the tag.
        copy: The `CharacterAbility` the change touches; None when the change
            creates it.
        level: The copy's level after the change; 0 when the change removes it.
        by: Who made the change, when the service was told. Staff tools always
            pass it.
    """

    character: Any
    kind: str
    stat: StatDef | None = None
    before: Rating | None = None
    after: Rating | None = None
    ability: AbilityDefinition | None = None
    tag: TagDefinition | None = None
    copy: CharacterAbility | None = None
    level: int | None = None
    by: Any = None


def refusals(change: BuildChange) -> list[str]:
    """Every guard's objection to `change`, without repeats. Empty: allowed."""
    messages = []
    for receiver, response in build_change_requested.send_robust(sender=BuildChange, change=change):
        if isinstance(response, Exception):
            logger.error(
                "rp_chargen guard %r raised; refusing the change", receiver, exc_info=response
            )
            messages.append(GUARD_FAILED)
        elif not response:
            continue
        elif isinstance(response, str):
            messages.append(response)
        elif isinstance(response, (list, tuple)) and all(isinstance(m, str) for m in response):
            messages.extend(m for m in response if m)
        else:
            logger.error(
                "rp_chargen guard %r returned %s, expected a message; refusing the change",
                receiver,
                type(response).__name__,
            )
            messages.append(GUARD_FAILED)
    return list(dict.fromkeys(messages))


def check(change: BuildChange) -> None:
    """Raise `ChargenError` with every refusal if any guard objects to `change`."""
    messages = refusals(change)
    if messages:
        from evennia_rp_chargen.services import ChargenError

        raise ChargenError(" ".join(messages))


__all__ = [
    "ACQUIRE",
    "EQUIP",
    "GRANT",
    "RATING",
    "REMOVE_FLAW",
    "REVOKE",
    "TAKE_FLAW",
    "UNEQUIP",
    "UPGRADE",
    "BuildChange",
    "build_change_requested",
    "check",
    "refusals",
]
