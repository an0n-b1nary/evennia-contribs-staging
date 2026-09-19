# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Permission helpers for evennia_xp web views and API.

HTTP staff checks use the shared ``evennia_links.is_staff_user`` policy;
``XP_STAFF_LOCK`` remains the in-game and authoring lock where configured.
"""

from django.core.exceptions import PermissionDenied

from evennia_links import is_staff_user as is_staff_user


def get_character_id(user) -> int | None:
    """Return the read-only XP identity from the account's playable roster.

    A live puppet is a preference only when several roster characters exist;
    roster order is the deterministic fallback. Live puppets not present in
    the roster are ignored.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    account = getattr(user, "account", None) or user
    try:
        roster = list(account.characters.all())
    except Exception:
        return None
    roster = [character for character in roster if character and getattr(character, "pk", None)]
    if not roster:
        return None
    if len(roster) == 1:
        return roster[0].pk
    try:
        live = account.get_all_puppets()
    except Exception:
        live = []
    live_ids = {
        getattr(character, "pk", None)
        for character in live or []
        if character and getattr(character, "pk", None)
    }
    for character in roster:
        if character.pk in live_ids:
            return character.pk
    return roster[0].pk


def require_character(request) -> int:
    """Return the character's ObjectDB pk or raise PermissionDenied."""
    character_id = get_character_id(request.user)
    if character_id is None:
        raise PermissionDenied("A puppeted character is required for this action.")
    return character_id
