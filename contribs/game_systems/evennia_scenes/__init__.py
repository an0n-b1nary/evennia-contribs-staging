# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_scenes — scene logging and event log browser for Evennia games.

Public API (model classes are loaded lazily to avoid AppRegistryNotReady
when this package is imported during Django's app-loading phase):

    Scene             — RP session in a room (open → active → closed lifecycle)
    SceneParticipant  — per-character participation tracking
    LogEntry          — captured pose/say/emit/ooc/dice/combat/system entry
    LogEntryVersion   — append-only edit history for LogEntry
    Status            — Scene.Status enum (OPEN / ACTIVE / CLOSED)
    Privacy           — Scene.Privacy enum (PUBLIC / POSE_PRIVATE / VIEW_PRIVATE)
    Role              — SceneParticipant.Role enum (PARTICIPANT / OBSERVER)
    LogType           — LogEntry.LogType enum (POSE / EMIT / SAY / OOC / …)

Signals (eagerly exported — plain Signal() objects, safe at app-load time):

    scene_opened, scene_started, scene_closed, log_entry_created

Capture hooks (import explicitly when needed):

    from evennia_scenes.capture import capture_to_scene, register_room_entry

Commands (import explicitly when needed):

    from evennia_scenes.commands import CmdScene, CmdLog

Web/API surface (requires [web] extra):

    from evennia_scenes.views import SceneListView, SceneDetailView
    # wire URLs with: include(("evennia_scenes.urls", "evennia_scenes"))
    # API: include("evennia_scenes.api.urls") at /api/v1/ or similar
"""

__version__ = "0.1.0"

from evennia_scenes.signals import (
    log_entry_created,
    scene_closed,
    scene_opened,
    scene_started,
)

_LAZY = {
    "Scene": "models",
    "SceneParticipant": "models",
    "LogEntry": "models",
    "LogEntryVersion": "models",
    # Enums are inner classes — resolved via their parent model.
    "Status": "models",
    "Privacy": "models",
    "Role": "models",
    "LogType": "models",
}

__all__ = [
    "LogEntry",
    "LogEntryVersion",
    "LogType",
    "Privacy",
    "Role",
    "Scene",
    "SceneParticipant",
    "Status",
    "log_entry_created",
    "scene_closed",
    "scene_opened",
    "scene_started",
]


def __getattr__(name):
    submodule = _LAZY.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    mod = import_module(f".{submodule}", __name__)
    # Resolve inner-class enums via their parent model.
    if name == "Status":
        return mod.Scene.Status
    if name == "Privacy":
        return mod.Scene.Privacy
    if name == "Role":
        return mod.SceneParticipant.Role
    if name == "LogType":
        return mod.LogEntry.LogType
    return getattr(mod, name)


def __dir__():
    return sorted([*globals(), *_LAZY])
