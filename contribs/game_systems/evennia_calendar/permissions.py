# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Permission helpers for evennia_calendar web views and API.

HTTP staff checks use the shared ``evennia_links.is_staff_user`` policy rather
than Django's ``is_staff`` flag. ``CALENDAR_STAFF_LOCK`` remains the lock for
in-game calendar actions and authoring policy.

Usage::

    from evennia_calendar.permissions import is_staff_user, get_character_id, require_character

    if not is_staff_user(request):
        raise PermissionDenied

    character_id = require_character(request)  # raises PermissionDenied if no puppet
"""

from django.core.exceptions import PermissionDenied

from evennia_links import is_staff_user as is_staff_user


def get_character_id(user) -> int | None:
    """Return the ObjectDB pk for the first puppeted character of *user*.

    Returns None if the user is unauthenticated or has no active puppet.
    """
    if not user.is_authenticated:
        return None
    account = getattr(user, "account", None) or user
    puppets = account.get_all_puppets() if hasattr(account, "get_all_puppets") else []
    return puppets[0].pk if puppets else None


def require_character(request) -> int:
    """Return the ObjectDB pk for the puppeted character, or raise PermissionDenied.

    Use for write actions (form submits, POSTs) that require a character identity.

    Raises:
        PermissionDenied: if unauthenticated, or logged in but no puppet.
    """
    character_id = get_character_id(request.user)
    if character_id is None:
        raise PermissionDenied("A puppeted character is required for this action.")
    return character_id
