# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Reference-game composition for private map previews, before projects exist."""

from evennia_building.visibility import room_visibility

from evennia_maps.permissions import room_attr_values


def room_visible(room, viewer=None):
    managed = room_visibility(room, viewer)
    if managed is not None:
        return managed
    room_types = room_attr_values(room, "room_type")
    teleport_rules = room_attr_values(room, "allow_teleport")
    if "staff" in room_types:
        return False
    if "secret" in teleport_rules and "ooc" in room_types:
        return bool(viewer and room.access(viewer, "control"))
    return "secret" not in teleport_rules


def last_played(character):
    """Existing host puppet/unpuppet timestamp; another alt's login is irrelevant."""
    return character.attributes.get("sandbox_last_seen") if character else None
