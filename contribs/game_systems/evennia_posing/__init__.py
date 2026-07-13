# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_posing — the pose pipeline for Evennia games: pose/emit/say/semipose
capture, the pose order tracker, pose headers, and name highlighting.

No Django models — all state lives on Character/Room AttributeProperty
fields, so there is nothing to migrate.

Public API:

    PosingCharacterMixin, PosingRoomMixin  — mix into your typeclasses
    highlight_names(text, looker, characters)
    format_pose_time(timestamp)
    pose_recorded  — Signal fired by PosingCharacterMixin.record_pose()

Commands (import explicitly when needed):

    from evennia_posing.commands import (
        CmdPose, CmdEmit, CmdSemipose, CmdPot, CmdLastPose,
        CmdPoseHeader, CmdHighlight,
    )

Screen-reader support (requires the [accessibility] extra):

    +pot renders a plain linear list instead of a fixed-width table when
    evennia_accessibility is installed and the caller has screenreader_mode
    enabled. No wiring needed beyond installing the extra.

See README.md for the full integration recipe, including the
``pose_recorded`` signal and the account options this contrib expects the
game to register in OPTIONS_ACCOUNT_DEFAULT.

PosingCharacterMixin/PosingRoomMixin are loaded lazily (PEP 562): they pull
in ``evennia.typeclasses.attributes.AttributeProperty``, which touches
Django's ContentType machinery and raises AppRegistryNotReady if imported
eagerly during Django's app-loading phase (this package's own ``apps.py``
is discovered during that phase). ``highlight_names``/``format_pose_time``/
``pose_recorded`` have no such dependency and are safe to export eagerly.
"""

from evennia_posing.highlighting import format_pose_time, highlight_names
from evennia_posing.signals import pose_recorded

__version__ = "0.1.0"

_LAZY = {
    "PosingCharacterMixin": "typeclasses",
    "PosingRoomMixin": "typeclasses",
}

__all__ = [
    "PosingCharacterMixin",
    "PosingRoomMixin",
    "format_pose_time",
    "highlight_names",
    "pose_recorded",
]


def __getattr__(name):
    submodule = _LAZY.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(f".{submodule}", __name__), name)


def __dir__():
    return sorted([*globals(), *_LAZY])
