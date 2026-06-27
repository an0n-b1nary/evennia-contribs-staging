# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Permission helpers for evennia_plots — in-game commands, models, and web views.

Uses Evennia's lock system (``PLOTS_STAFF_LOCK`` setting) rather than Django's
``is_staff`` flag, which is unrelated to in-game permission levels.

In-game usage (commands and models)::

    from evennia_plots.permissions import is_plot_staff, can_manage_arc

    if not is_plot_staff(caller):
        caller.msg("Permission denied.")
        return

Web view usage::

    from evennia_plots.permissions import is_staff_user, get_character_id

    if not is_staff_user(request):
        raise PermissionDenied
"""

from django.conf import settings
from django.core.exceptions import PermissionDenied

# ---------------------------------------------------------------------------
# In-game (character-level) helpers — used by models and commands
# ---------------------------------------------------------------------------


def is_plot_staff(character) -> bool:
    """Return True if *character* passes the PLOTS_STAFF_LOCK lock expression.

    Reads ``PLOTS_STAFF_LOCK`` (default ``"cmd:perm(Builder)"``), strips the
    ``cmd:`` prefix, and evaluates it against the character's lock handler.
    Returns False on any exception (unauthenticated, anonymous, test stubs).

    Args:
        character: Evennia ObjectDB typeclass instance, or None.
    """
    if character is None:
        return False
    lock_expr = getattr(settings, "PLOTS_STAFF_LOCK", "cmd:perm(Builder)")
    expr = lock_expr[4:] if lock_expr.startswith("cmd:") else lock_expr
    try:
        return bool(character.locks.check_lockstring(character, expr))
    except Exception:
        return False


def can_manage_arc(character, arc=None) -> bool:
    """Return True if *character* may create or mutate PlotArcs.

    Today this delegates entirely to ``is_plot_staff``. The *arc* parameter
    is a seam for a future per-arc designated-manager whitelist; callers that
    have the arc in scope should pass it so they are already correct when that
    policy lands.

    Args:
        character: Evennia ObjectDB typeclass instance.
        arc: PlotArc instance or None.
    """
    return is_plot_staff(character)


# ---------------------------------------------------------------------------
# Web (request-level) helpers — used by views and API
# ---------------------------------------------------------------------------


def _staff_lock_expr() -> str:
    """Return the bare lock expression (without ``cmd:`` prefix) for staff checks."""
    lock = getattr(settings, "PLOTS_STAFF_LOCK", "cmd:perm(Builder)")
    return lock[4:] if lock.startswith("cmd:") else lock


def is_staff_user(request) -> bool:
    """Return True if the request's account has plot staff permissions.

    Uses Evennia's lock system (configured via ``PLOTS_STAFF_LOCK``, default
    ``perm(Builder)``) rather than Django's ``is_staff`` flag. Falls back to
    ``is_superuser`` if the lock check raises (e.g. in tests).
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
