# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Explicit request/session scope; never borrow another puppet's access."""

from evennia_links.characters import web_roster
from evennia_links.notices import NoticeContext, authorize_context, session_context


def from_web(request):
    """Resolve only the website's explicit, currently owned puppet choice."""
    try:
        selected = int(request.session.get("puppet"))
    except (TypeError, ValueError):
        selected = None
    character = next((c for c in web_roster(request.user) if c.pk == selected), None)
    return NoticeContext(request.user, character)


def from_command(caller, session=None):
    """Use the originating session account and exact command character."""
    from evennia.accounts.models import AccountDB

    if session is not None:
        if isinstance(caller, AccountDB):
            if caller != session.get_account():
                raise ValueError("The command must use its own account session")
        elif caller != session.get_puppet():
            raise ValueError("The command must use its controlled session character")
        context = session_context(session)
    else:
        account = caller if isinstance(caller, AccountDB) else getattr(caller, "account", None)
        character = None if isinstance(caller, AccountDB) else caller
        context = NoticeContext(account, character)
    if not authorize_context(context):
        raise ValueError("An authenticated account and controlled playable character are required")
    return context


def ownerships(context):
    """Return exactly the account and explicitly selected playable character."""
    if not authorize_context(context):
        raise ValueError("Invalid notice context")
    result = [("account", context.account.pk)]
    if context.character is not None:
        result.append(("character", context.character.pk))
    return result
