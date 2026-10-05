# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Close challenges when their setter's RP session ends."""

from importlib import import_module

from evennia_rp_contest.expiry import close_for_setter


def on_session_ended(sender, session=None, **kwargs):
    character = getattr(session, "character", None)
    if character is not None:
        close_for_setter(character)


def connect(app_config):
    signals = import_module(f"{app_config.name}.signals")
    signals.rp_session_ended.connect(on_session_ended, dispatch_uid="rp_contest.session_end")
