# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Room search utilities for fuzzy and partial name matching.

Provides find_room() and find_room_for_player(), which combine Evennia's
built-in object search with difflib fuzzy matching for typo tolerance. Used
by CmdTel (@tel) and CmdSummon/CmdJoin's target resolution.

Room/Character matching is done by isinstance() against Evennia's
DefaultRoom/DefaultCharacter rather than a typeclass dotted-path string, so
this works against whatever Room/Character subclass the consuming game
defines (isinstance() covers the whole subclass tree; a dotted-path filter
would only match one exact class).
"""

import difflib

from django.conf import settings
from evennia.objects.objects import DefaultRoom


def _get_all_rooms():
    """Return all Room objects (any subclass of DefaultRoom).

    ``all_family()`` resolves DefaultRoom's whole subclass tree to typeclass
    paths and filters on them in SQL, so this stays a single indexed query
    rather than pulling every object in the database into Python to
    isinstance-check it (which would also force a typeclass resolution per
    row). Only the fuzzy-match fallback path calls this.
    """
    return DefaultRoom.objects.all_family()


def find_room(caller, query, exclude_secret=False):
    """Find a room by partial or fuzzy name match.

    Uses Evennia's built-in search first (substring match), then falls
    back to difflib fuzzy matching for typo tolerance.

    Args:
        caller: The object performing the search.
        query (str): Room name to search for.
        exclude_secret (bool): If True, filter out rooms with
            allow_teleport == "secret" from results and suggestions.

    Returns:
        tuple: (room_or_none, list_of_suggestions)
            - (room, []) if exactly one match
            - (None, [room, ...]) if multiple matches
            - (None, []) if no matches at all
    """
    # Global substring search, then narrow to rooms by isinstance (not a
    # typeclass path — see module docstring). Deduplicate by primary key:
    # Evennia's unfiltered candidate search can return separate object
    # wrappers for the same underlying row (e.g. matched via both key and
    # alias), which would otherwise masquerade as an ambiguous multi-match.
    candidates = caller.search(query, global_search=True, quiet=True)
    seen_pks = set()
    results = []
    for obj in candidates:
        if isinstance(obj, DefaultRoom) and obj.pk not in seen_pks:
            seen_pks.add(obj.pk)
            results.append(obj)

    if exclude_secret:
        results = [r for r in results if getattr(r, "allow_teleport", "public") != "secret"]

    if len(results) == 1:
        return (results[0], [])
    if len(results) > 1:
        return (None, results)

    # No results from Evennia search — try fuzzy matching.
    all_rooms = _get_all_rooms()
    if exclude_secret:
        room_map = {}
        for room in all_rooms:
            if getattr(room, "allow_teleport", "public") != "secret":
                room_map[room.db_key] = room
    else:
        room_map = {room.db_key: room for room in all_rooms}

    close = difflib.get_close_matches(query, room_map.keys(), n=5, cutoff=0.6)
    if close:
        suggestions = [room_map[name] for name in close]
        return (None, suggestions)

    return (None, [])


def find_room_for_player(caller, query, character):
    """Find a room respecting player teleport restrictions.

    Applies two layers of filtering:
    1. TELEPORT_MODE setting: "visited" restricts to rooms the character
       has visited or controls; "open" allows any room.
    2. Per-room allow_teleport: "private" and "secret" rooms are blocked
       unless the character controls the room.

    Staff (Builder+) should use find_room() directly instead.

    Args:
        caller: The object performing the search.
        query (str): Room name to search for.
        character: The character whose visited_rooms and access are checked.

    Returns:
        tuple: (room_or_none, list_of_suggestions) — same format as find_room().
    """
    room, suggestions = find_room(caller, query, exclude_secret=True)
    candidates = [room] if room else suggestions

    teleport_mode = getattr(settings, "TELEPORT_MODE", "visited")
    visited = character.visited_rooms or set()

    filtered = []
    for r in candidates:
        access_level = getattr(r, "allow_teleport", "public")
        controls = r.access(character, "control")

        # Private/secret rooms: owner only (among players)
        if access_level in ("private", "secret") and not controls:
            continue

        # Visited mode: must have visited or control the room
        if teleport_mode == "visited" and r.dbref not in visited and not controls:
            continue

        filtered.append(r)

    if len(filtered) == 1:
        return (filtered[0], [])
    if len(filtered) > 1:
        return (None, filtered)
    return (None, [])
