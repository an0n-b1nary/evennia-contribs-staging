# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Canonical direction vocabulary for the map's auto-layout.

Only exits whose key or aliases match a canonical direction participate in
layout (auto-placement, +map/reflow, derive-on-render). Free-form/flavor
exits are ignored by layout entirely — this is the minimum discipline that
makes an auto-growing tile grid possible without banning creative exits.

DIRECTION_OFFSETS is settings-overridable: a game may add or replace
entries via settings.DIRECTION_OFFSETS, merged over the module default.
"""

import contextlib

from django.conf import settings

# key: (dx, dy, d_elevation, kind)  kind in {"planar", "vertical"}
#
# Both the abbreviation and the full name are registered for every direction.
# Evennia's @tunnel makes the full name the exit key and the abbreviation an
# alias ("north" + "n"), but a plain `dig north=New Room` creates the full
# name with no alias at all — so registering abbreviations only would leave
# the single most common build path invisible to the map.
#
# in/out are deliberately absent: portals are not a direction "kind". They're
# inferred purely from geometry (destination tile lands on a non-stacked
# plane), so an in/out exit simply doesn't participate in layout.
DEFAULT_DIRECTION_OFFSETS = {
    "n": (0, 1, 0, "planar"),
    "north": (0, 1, 0, "planar"),
    "s": (0, -1, 0, "planar"),
    "south": (0, -1, 0, "planar"),
    "e": (1, 0, 0, "planar"),
    "east": (1, 0, 0, "planar"),
    "w": (-1, 0, 0, "planar"),
    "west": (-1, 0, 0, "planar"),
    "ne": (1, 1, 0, "planar"),
    "northeast": (1, 1, 0, "planar"),
    "nw": (-1, 1, 0, "planar"),
    "northwest": (-1, 1, 0, "planar"),
    "se": (1, -1, 0, "planar"),
    "southeast": (1, -1, 0, "planar"),
    "sw": (-1, -1, 0, "planar"),
    "southwest": (-1, -1, 0, "planar"),
    "u": (0, 0, 1, "vertical"),
    "up": (0, 0, 1, "vertical"),
    "d": (0, 0, -1, "vertical"),
    "down": (0, 0, -1, "vertical"),
}


def get_offsets():
    """
    Return the effective direction-offset registry.

    Merges settings.DIRECTION_OFFSETS (if any) over DEFAULT_DIRECTION_OFFSETS,
    so a game can add or override individual directions without redeclaring
    the whole table.
    """
    offsets = dict(DEFAULT_DIRECTION_OFFSETS)
    offsets.update(getattr(settings, "DIRECTION_OFFSETS", {}) or {})
    return offsets


def resolve(exit_obj):
    """
    Resolve an Evennia Exit object to a canonical direction offset.

    Matches the exit's db_key and aliases, case-insensitively, against the
    effective direction-offset registry.

    Args:
        exit_obj: An Evennia Exit (or Exit-like) object with .key and
            .aliases.all().

    Returns:
        tuple: (dx, dy, d_elevation, kind) if the exit matches a canonical
            direction, else None (free-form exits are ignored by layout).
    """
    offsets = get_offsets()

    candidates = [exit_obj.key]
    with contextlib.suppress(AttributeError):
        candidates.extend(exit_obj.aliases.all())

    for candidate in candidates:
        if not candidate:
            continue
        offset = offsets.get(candidate.strip().lower())
        if offset is not None:
            return offset
    return None
