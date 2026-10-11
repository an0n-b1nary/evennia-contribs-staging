# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Social -> Maps tile overlay: who is in each room right now.

evennia_maps asks its installed partners once per map render, via the
``collect_tile_overlays`` collector signal, and this module answers for
presence. Install both contribs and the live map shows who's here; uninstall
either and the map renders without it.

A web map is a remote presence surface, so it follows ``+where``: a character
appears only if they are findable (``evennia_social.presence``). The map has
no in-game viewer standing in a room, so for players the rule is
``is_publicly_findable``, and unfindable or dark characters are left out of
both the names and the count. Staff renders list everyone, with the same
" (unfindable)" / " (dark)" marker ``+where`` shows staff.

Overlay key
-----------
``present``
    ``{room_id: ["Name", ...]}``: connected characters in the room, sorted by
    name. Rooms with nobody to show are absent.

Connected from EvenniaSocialConfig.ready(), gated on evennia_maps being
installed.
"""


def provide(sender, room_ids, staff, **kwargs):
    """
    ``collect_tile_overlays`` receiver: see the module docstring for the key.

    One pass over the live sessions for the whole grid, with no database
    query per tile; the cost grows with the number of players online, not
    the size of the map. Each character's presence Attribute is read from
    Evennia's attribute cache, which costs one query the first time a
    character is seen after a restart.
    """
    wanted = set(room_ids or ())
    if not wanted:
        return {}
    # Imported here, not at module level: ready() imports this module, and
    # evennia_social.social binds Evennia's SESSION_HANDLER on import, which
    # is still None until Evennia finishes starting. Importing it that early
    # would leave +where with no session handler too.
    from evennia_social import presence
    from evennia_social.social import get_connected_characters

    present = {}
    seen = set()
    for character in get_connected_characters():
        # A character puppeted from several sessions appears once.
        if character.pk in seen:
            continue
        seen.add(character.pk)
        location = character.location
        if location is None or location.pk not in wanted:
            continue
        if staff:
            name = character.key + presence.staff_marker(character)
        elif presence.is_publicly_findable(character):
            name = character.key
        else:
            continue
        present.setdefault(location.pk, []).append(name)
    if not present:
        return {}
    return {"present": {room_id: sorted(names) for room_id, names in present.items()}}
