# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Permission helpers for evennia_lore web views and API.

HTTP staff checks use the shared ``evennia_links.is_staff_user`` policy;
``LORE_STAFF_LOCK`` remains the in-game and authoring lock.
"""

from django.core.exceptions import PermissionDenied

from evennia_links import is_staff_user as is_staff_user


def get_character_id(user) -> int | None:
    """Return the ObjectDB pk for the first puppeted character of *user*."""
    if not user.is_authenticated:
        return None
    account = getattr(user, "account", None) or user
    puppets = account.get_all_puppets() if hasattr(account, "get_all_puppets") else []
    return puppets[0].pk if puppets else None


def require_character(request) -> int:
    """Return the character's ObjectDB pk or raise PermissionDenied."""
    character_id = get_character_id(request.user)
    if character_id is None:
        raise PermissionDenied("A puppeted character is required for this action.")
    return character_id
