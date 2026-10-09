# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Permission helpers for evennia_jobs web views and API.

HTTP staff checks use the shared ``evennia_links.is_staff_user`` policy rather
than Django's ``is_staff`` flag. The jobs command lock remains the policy for
in-game and authoring actions.

Usage::

    from evennia_jobs.permissions import is_staff_user, get_character_id, require_character

    # In a view:
    if not is_staff_user(request):
        raise PermissionDenied

    # For authoring actions that require a character:
    character_id = require_character(request)   # raises PermissionDenied if no character
"""

from django.core.exceptions import PermissionDenied

from evennia_links import is_staff_user as is_staff_user
from evennia_links.characters import web_character


def get_character_id(user) -> int | None:
    """Return the ObjectDB pk of the character *user* acts as on the web.

    Resolved by ``evennia_links.characters.web_character``: a live puppet is
    preferred but not required, so a visitor who is not connected in-game
    still acts as a character from their account. Returns None if the user is
    unauthenticated or has no character.
    """
    character = web_character(user)
    return character.pk if character else None


def require_character(request) -> int:
    """Return the ObjectDB pk of the acting character, or raise PermissionDenied.

    Use for write actions (form submits, POSTs) that require an active character.

    Raises:
        PermissionDenied: if unauthenticated, or logged in but has no character.
    """
    character_id = get_character_id(request.user)
    if character_id is None:
        raise PermissionDenied("A character is required for this action.")
    return character_id
