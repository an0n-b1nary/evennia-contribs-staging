# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Reference-game composition for private map previews, before projects exist."""

from evennia_maps.permissions import room_attr_values


def room_visible(room, viewer=None):
    room_types = room_attr_values(room, "room_type")
    teleport_rules = room_attr_values(room, "allow_teleport")
    if "staff" in room_types:
        return False
    if "secret" in teleport_rules and "ooc" in room_types:
        return bool(viewer and room.access(viewer, "control"))
    return "secret" not in teleport_rules
