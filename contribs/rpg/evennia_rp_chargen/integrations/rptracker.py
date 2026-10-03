# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""evennia_rptracker integration: an RP session ending releases the build lock.

Connected by `RPChargenConfig.ready()` when the app labelled
`RP_CHARGEN_RPTRACKER_APP_LABEL` (default `evennia_rptracker`) is installed.
A game whose tracker sends a different signal calls `locks.release(character,
locks.SESSION_END)` from its own listener instead.
"""

from __future__ import annotations

from importlib import import_module

from evennia_rp_chargen import locks

DISPATCH_UID = "evennia_rp_chargen.rptracker.session_ended"


def on_session_ended(sender, session=None, **kwargs) -> None:
    character = getattr(session, "character", None)
    if character is not None:
        locks.release(character, locks.SESSION_END)


def connect(app_config) -> None:
    """Connect to `<tracker app>.signals.rp_session_ended`."""
    signals = import_module(f"{app_config.name}.signals")
    signals.rp_session_ended.connect(on_session_ended, dispatch_uid=DISPATCH_UID)
