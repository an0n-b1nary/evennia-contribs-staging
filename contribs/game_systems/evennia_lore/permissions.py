# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Permission helpers for evennia_lore web views and API.

HTTP staff checks use the shared ``evennia_links.is_staff_user`` policy;
``LORE_STAFF_LOCK`` remains the in-game and authoring lock.
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
    """Return the character's ObjectDB pk or raise PermissionDenied."""
    character_id = get_character_id(request.user)
    if character_id is None:
        raise PermissionDenied("A character is required for this action.")
    return character_id
