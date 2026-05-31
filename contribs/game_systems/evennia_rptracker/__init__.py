# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_rptracker — passive RP session detection and tracking for Evennia games.

Public API (functions and signals — safe to import eagerly):

    record_rp_activity(character, room)  — call from your pose hook
    end_session(character_id, manual)    — call from your disconnect hook
    get_active_session_id(character_id)  — current session pk or None
    get_session_state(character_id)      — in-memory state dict or None
    flush_all_sessions()                 — call from at_server_stop()
    recover_orphaned_sessions()          — call from at_server_start()
    ensure_idle_check_running()          — call from at_server_start()
    sweep_rp_sessions(window_end)        — call before XP collectors
    signals.rp_session_started
    signals.rp_session_ended
    signals.rp_activity_recorded

Model classes are loaded lazily (PEP 562) to avoid AppRegistryNotReady
when the package is imported during Django's app-loading phase.
"""

from evennia_rptracker import signals
from evennia_rptracker.antigaming import sweep_rp_sessions
from evennia_rptracker.tracker import (
    end_session,
    ensure_idle_check_running,
    flush_all_sessions,
    get_active_session_id,
    get_session_state,
    record_rp_activity,
    recover_orphaned_sessions,
)

__version__ = "0.1.0"

_LAZY = {
    "RPSession": "models",
    "RPSessionPartner": "models",
    "RPSessionSceneLink": "models",
}

__all__ = [
    "RPSession",
    "RPSessionPartner",
    "RPSessionSceneLink",
    "end_session",
    "ensure_idle_check_running",
    "flush_all_sessions",
    "get_active_session_id",
    "get_session_state",
    "record_rp_activity",
    "recover_orphaned_sessions",
    "signals",
    "sweep_rp_sessions",
]


def __getattr__(name):
    submodule = _LAZY.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(f".{submodule}", __name__), name)


def __dir__():
    return sorted([*globals(), *_LAZY])
