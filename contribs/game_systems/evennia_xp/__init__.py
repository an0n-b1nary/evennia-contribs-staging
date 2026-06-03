# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_xp — registry-driven weekly XP batch engine for Evennia games.

Public API (model classes loaded lazily to avoid AppRegistryNotReady):

    XPLog           — immutable per-award ledger row
    CharacterXP     — aggregate balance totals per character

Signals (eagerly exported — plain Signal() objects, safe at app-load time):

    xp_awarded, xp_batch_completed

Batch engine (import explicitly):

    from evennia_xp.batch import run_weekly_batch, Award, BatchSummary

Commands (import explicitly):

    from evennia_xp.commands import CmdXp

Web/API surface (requires [web] extra):

    from evennia_xp.views import XPSummaryView
    from evennia_xp.api.views import XPLogViewSet
"""

__version__ = "0.1.0"

from evennia_xp.signals import xp_awarded, xp_batch_completed

_LAZY = {
    "XPLog": "models",
    "CharacterXP": "models",
}

__all__ = [
    "CharacterXP",
    "XPLog",
    "xp_awarded",
    "xp_batch_completed",
]


def __getattr__(name):
    submodule = _LAZY.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(f".{submodule}", __name__), name)


def __dir__():
    return sorted([*globals(), *_LAZY])
