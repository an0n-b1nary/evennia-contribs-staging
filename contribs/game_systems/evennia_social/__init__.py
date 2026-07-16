# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_social — the social quality-of-life command layer for Evennia
games: character profiles (+finger), player/venue discovery (+where,
+hangouts), private messaging (page), ignore/mute, consensual teleportation
(+summon/+join), OOC room chat and navigation shortcuts (+ooc, +home), and
an enhanced @tel.

No Django models — all state lives on Character/Room AttributeProperty
fields, so there is nothing to migrate.

Hard-depends on `evennia_posing` (pyproject.toml `dependencies`): reuses
`format_pose_time`, reads posing's `last_pose_time`/`pose_status` for
`+where`, and layers ignore-filtering onto posing's header/highlight
`msg()` via cooperative mixin inheritance. See README "Integration recipe".

Public API:

    SocialCharacterMixin, SocialRoomMixin  — mix into your typeclasses
    HANGOUT_TYPES                          — valid +hangouts categories
    find_room(caller, query), find_room_for_player(caller, query, character)
    is_staff(character), get_connected_characters(), find_character(name)

Commands (import explicitly when needed):

    from evennia_social.commands import (
        CmdFinger, CmdWhere, CmdHangouts, CmdIgnore, CmdPage,
        CmdSummon, CmdJoin, CmdOoc, CmdOocTeleport, CmdHome,
        CmdRoomConfig, CmdRoulette, CmdTel,
    )

Screen-reader support (requires the [accessibility] extra):

    +where and +hangouts render a plain linear list instead of a
    fixed-width table when evennia_accessibility is installed and the
    caller has screenreader_mode enabled. No wiring needed beyond
    installing the extra.

See README.md for the full integration recipe, including the account
options this contrib expects the game to register in
OPTIONS_ACCOUNT_DEFAULT and the OOC_ROOM_DBREF / TELEPORT_MODE settings.

Every export below is loaded lazily (PEP 562): unlike evennia_posing's
highlighting.py, none of this contrib's modules are free of Evennia ORM
touches — search.py and social.py both import evennia.objects.models /
evennia.objects.objects at module level for their isinstance()-based
matching (see MIGRATION_NOTES.md), which raises AppRegistryNotReady if
imported eagerly during Django's app-loading phase (this package's own
apps.py is discovered during that phase, since evennia_social is itself
listed in INSTALLED_APPS).
"""

__version__ = "0.1.0"

_LAZY = {
    "SocialCharacterMixin": "typeclasses",
    "SocialRoomMixin": "typeclasses",
    "HANGOUT_TYPES": "typeclasses",
    "find_room": "search",
    "find_room_for_player": "search",
    "find_character": "social",
    "is_staff": "social",
    "get_connected_characters": "social",
}

__all__ = [
    "HANGOUT_TYPES",
    "SocialCharacterMixin",
    "SocialRoomMixin",
    "find_character",
    "find_room",
    "find_room_for_player",
    "get_connected_characters",
    "is_staff",
]


def __getattr__(name):
    submodule = _LAZY.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(f".{submodule}", __name__), name)


def __dir__():
    return sorted([*globals(), *_LAZY])
