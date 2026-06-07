# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Permission helpers for evennia_boards web views and API.

Uses Evennia's lock system (BOARDS_STAFF_LOCK setting) rather than Django's
is_staff flag, which is unrelated to in-game permission levels.

Usage::

    from evennia_boards.permissions import is_staff_user, get_character_id, require_character

    if not is_staff_user(request):
        raise PermissionDenied

    character_id = require_character(request)  # raises PermissionDenied if no puppet
"""

from django.conf import settings
from django.core.exceptions import PermissionDenied


def _staff_lock_expr():
    """Return the bare lock expression (without ``cmd:`` prefix) for staff checks."""
    lock = getattr(settings, "BOARDS_STAFF_LOCK", "cmd:perm(Builder)")
    return lock[4:] if lock.startswith("cmd:") else lock


def is_staff_user(request) -> bool:
    """Return True if the request's account has boards staff permissions.

    Uses Evennia's lock system (configured via BOARDS_STAFF_LOCK, default
    ``perm(Builder)``) rather than Django's ``is_staff`` flag. Falls back
    to ``is_superuser`` if the lock check raises (e.g. in tests).
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
