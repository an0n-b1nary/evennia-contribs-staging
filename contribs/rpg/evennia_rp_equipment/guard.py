# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Refuse build changes that would break worn gear (evennia_rp_chargen's change guard).

Connected to `evennia_rp_chargen.guards.build_change_requested` in `ready()`.
A change is refused when it would take a requirement that worn gear meets
right now and leave it unmet: moving pips off a stat, unequipping or losing a
required ability, or shedding a required flaw. Staff changes are refused the
same way; the gear has to come off first.

Gaining things never breaks gear, so acquiring, equipping, upgrading, taking a
flaw and staff grants are never refused here.
"""

from __future__ import annotations

from evennia_rp_equipment.display import worn_items
from evennia_rp_equipment.requirements import MET, describe, rating_meets, status

DISPATCH_UID = "evennia_rp_equipment.guard"


def _breaks(change, req) -> bool:
    from evennia_rp_chargen import guards

    if change.kind == guards.RATING:
        return (
            req.on_stat
            and change.stat is not None
            and req.stat == change.stat.key
            and rating_meets(req, change.before)
            and not rating_meets(req, change.after)
        )
    if change.kind in (guards.UNEQUIP, guards.REVOKE, guards.REMOVE_FLAW):
        if change.ability is None:
            return False
        tag_key = change.tag.key if change.tag is not None else None
        return (
            req.matches_ability(change.ability.key, tag_key)
            and status(change.character, req) == MET
        )
    return False


def on_build_change(sender, change, **kwargs):
    """`build_change_requested` receiver: a message per worn item the change would break."""
    character = change.character
    items = worn_items(character)
    if not items:
        return None
    own = change.by is None or change.by == character
    refusals = []
    for item in items:
        for req in item.get_requirements():
            if _breaks(change, req):
                name = item.get_display_name(change.by or character)
                whose = f"your {name}" if own else f"{character.key}'s {name}"
                # "Proficiency: Blades is held by...", not "...Blades equipped is held by".
                held = describe(req).removesuffix(" equipped")
                refusals.append(f"{held} is held by {whose}. Take that off first.")
    return refusals or None


__all__ = ["DISPATCH_UID", "on_build_change"]
