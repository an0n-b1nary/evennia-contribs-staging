# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_lore — wiki-like lore compendium for Evennia games.

Public API (model classes loaded lazily to avoid AppRegistryNotReady):

    LoreTag             — tag applied to lore entries
    LoreEntry           — the main wiki-like article model
    LoreVersion         — edit-history snapshot for LoreEntry.body
    LoreAcquisition     — per-character compendium ownership row
    PlotLoreLink        — bridge: LoreEntry ↔ PlotThread (integer soft-ref)
    LoreSceneLink       — bridge: LoreEntry ↔ Scene (integer soft-ref)
    LoreRegionLink      — bridge: LoreEntry ↔ Region (integer soft-ref)

Signals (eagerly exported — plain Signal() objects, safe at app-load time):

    lore_entry_created, lore_entry_published, lore_entry_edited, lore_acquired

Commands (import explicitly):

    from evennia_lore.commands import CmdLore, CmdInvestigate, CmdShare, CmdHint, CmdForget

Web/API surface (requires [web] extra):

    from evennia_lore.views import LoreListView, LoreDetailView, ...
    from evennia_lore.api.views import LoreEntryViewSet, LoreTagViewSet
"""

__version__ = "0.1.0"

from evennia_lore.signals import (
    lore_acquired,
    lore_entry_created,
    lore_entry_edited,
    lore_entry_published,
)

_LAZY = {
    "LoreTag": "models",
    "LoreEntry": "models",
    "LoreVersion": "models",
    "LoreAcquisition": "models",
    "PlotLoreLink": "models",
    "LoreSceneLink": "models",
    "LoreRegionLink": "models",
}

__all__ = [
    "LoreAcquisition",
    "LoreEntry",
    "LoreRegionLink",
    "LoreSceneLink",
    "LoreTag",
    "LoreVersion",
    "PlotLoreLink",
    "lore_acquired",
    "lore_entry_created",
    "lore_entry_edited",
    "lore_entry_published",
]


def __getattr__(name):
    submodule = _LAZY.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(f".{submodule}", __name__), name)


def __dir__():
    return sorted([*globals(), *_LAZY])
