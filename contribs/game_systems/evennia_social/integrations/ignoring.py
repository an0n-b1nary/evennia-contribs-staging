# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Links presentation provider for Social's shared ignore service."""

from evennia_links.ignoring import ignore_mode_requested
from evennia_social import ignore


def provide(sender, viewer, sender_object, kind, **kwargs):
    """Answer board and channel presentation from the same boundary service.

    ``channels`` is ordinary OOC delivery; ``ic_channels`` uses character
    post levels. Both channel kinds share the ``channels`` preference.
    """
    if kind not in ("boards", "channels", "ic_channels"):
        return None
    if not (getattr(viewer, "account", None) or hasattr(viewer, "db")):
        return None
    account = ignore.account_for(viewer)
    if not account or account.is_superuser or account.check_permstring("Builder"):
        return None
    hidden = (
        ignore.blocks_channel(viewer, sender_object)
        if kind == "channels"
        else ignore.ignore_level(viewer, sender_object) == ignore.HIDDEN
    )
    if hidden:
        preference = (
            ignore.boards_preference(account)
            if kind == "boards"
            else ignore.channels_preference(account)
        )
        if preference == ignore.HIDE:
            return "hide"
        return "placeholder"
    return None


def register():
    """Install the provider once even if app readiness is invoked repeatedly."""
    ignore_mode_requested.connect(provide, dispatch_uid="evennia_social.ignore_mode")
