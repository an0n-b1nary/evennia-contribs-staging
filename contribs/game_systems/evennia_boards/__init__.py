# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_boards — bulletin board system for Evennia games.

Public API (model classes are loaded lazily to avoid AppRegistryNotReady
when this package is imported during Django's app-loading phase):

    Board           — named bulletin board (OOC or IC type)
    Post            — per-board auto-numbered post with threading + soft-archive
    PostVersion     — append-only edit history
    Subscription    — account-level board subscription
    PostCalendarLink — optional bridge to a calendar event (soft-ref)
    BoardType       — enum: OOC / IC

Signals (eagerly exported — plain Signal() objects, safe at app-load time):

    post_created, board_unread_notified

Commands (import explicitly when needed):

    from evennia_boards.commands import CmdBoard

Web/API surface (requires [web] extra):

    from evennia_boards.views import BoardListView, BoardDetailView
    from evennia_boards.api.views import BoardViewSet, PostViewSet
    # wire URLs with: include("evennia_boards.urls") / include("evennia_boards.api.urls")

XP integration (requires [xp] extra — register in your settings):

    XP_COLLECTORS      += [("cutscene", "evennia_boards.integrations.xp.collect_cutscene_posts")]
    XP_ANTIGAMING_SWEEPS += ["evennia_boards.integrations.xp.sweep_cutscene_spam"]
"""

__version__ = "0.1.0"

from evennia_boards.signals import board_unread_notified, post_created

_LAZY = {
    "Board": "models",
    "Post": "models",
    "PostVersion": "models",
    "Subscription": "models",
    "PostCalendarLink": "models",
    "BoardType": "models",
}

__all__ = [
    "Board",
    "BoardType",
    "Post",
    "PostCalendarLink",
    "PostVersion",
    "Subscription",
    "board_unread_notified",
    "post_created",
]


def __getattr__(name):
    submodule = _LAZY.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    mod = import_module(f".{submodule}", __name__)
    if name == "BoardType":
        return mod.Board.BoardType
    return getattr(mod, name)


def __dir__():
    return sorted([*globals(), *_LAZY])
