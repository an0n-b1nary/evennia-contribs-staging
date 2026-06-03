# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Permission helpers for evennia_xp web views and API (XP_STAFF_LOCK)."""

from django.conf import settings
from django.core.exceptions import PermissionDenied


def _staff_lock_expr():
    lock = getattr(settings, "XP_STAFF_LOCK", "cmd:perm(Builder)")
    return lock[4:] if lock.startswith("cmd:") else lock


def is_staff_user(request) -> bool:
    """Return True if the request's account has XP staff permission.

    Uses Evennia's lock system (XP_STAFF_LOCK, default ``perm(Builder)``) rather
    than Django's ``is_staff`` flag. Falls back to ``is_superuser`` if the lock
    check raises (e.g. in tests without locks infrastructure).
    """
    if not request.user.is_authenticated:
        return False
    account = request.user
    try:
        return bool(account.locks.check_lockstring(account, _staff_lock_expr()))
    except Exception:
        return bool(getattr(account, "is_superuser", False))


def get_character_id(user) -> int | None:
    """Return the ObjectDB pk for the first puppeted character of *user*.

    Returns ``None`` if the user is unauthenticated or has no puppets.
    """
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
