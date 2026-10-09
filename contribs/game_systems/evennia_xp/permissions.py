# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Permission helpers for evennia_xp web views and API.

HTTP staff checks use the shared ``evennia_links.is_staff_user`` policy;
``XP_STAFF_LOCK`` remains the in-game and authoring lock where configured.
"""

from django.core.exceptions import PermissionDenied

from evennia_links import is_staff_user as is_staff_user
from evennia_links.characters import web_character


def get_character_id(user) -> int | None:
    """Return the read-only XP identity from the account's playable roster.

    Resolved by ``evennia_links.characters.web_character`` with
    ``roster_only``: a live puppet on the roster is preferred, then the last
    puppet, then roster order. Live puppets not present in the roster are
    ignored.
    """
    character = web_character(user, roster_only=True)
    return character.pk if character else None


def require_character(request) -> int:
    """Return the character's ObjectDB pk or raise PermissionDenied."""
    character_id = get_character_id(request.user)
    if character_id is None:
        raise PermissionDenied("A character is required for this action.")
    return character_id
