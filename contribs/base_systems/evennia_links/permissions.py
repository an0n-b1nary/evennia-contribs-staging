# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Shared request-level web permission helpers.

``is_staff_user`` is the one staff predicate used by the extracted web
surfaces.  Games may provide a callable through
``EVENNIA_WEB_STAFF_PREDICATE``; otherwise the helper evaluates the
web-wide ``EVENNIA_WEB_STAFF_LOCK`` with Evennia's lock handler.
"""

import logging

from django.conf import settings

from .collect import resolve_dotted

_log = logging.getLogger("evennia")
_DEFAULT_WEB_STAFF_LOCK = "cmd:perm(Builder)"


def _setting(name, default=None):
    """Read a setting while failing closed if Django settings are unavailable."""
    try:
        return getattr(settings, name, default)
    except Exception:
        _log.exception("evennia_links: could not read setting %s", name)
        return default


def is_staff_user(request) -> bool:
    """Return whether *request* passes the game's web staff policy.

    The configured predicate is authoritative. Import failures, non-callable
    values, recursion back to this helper, and predicate exceptions all return
    ``False``. Without a predicate, Evennia evaluates the configured lock;
    Django's ``user.is_staff`` flag is intentionally never consulted.
    """
    if request is None:
        return False
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return False

    predicate_path = _setting("EVENNIA_WEB_STAFF_PREDICATE", None)
    if predicate_path:
        try:
            predicate = resolve_dotted(predicate_path)
        except Exception:
            _log.exception(
                "evennia_links: EVENNIA_WEB_STAFF_PREDICATE=%r could not be resolved",
                predicate_path,
            )
            return False
        if predicate is is_staff_user:
            _log.error(
                "evennia_links: EVENNIA_WEB_STAFF_PREDICATE=%r resolves to itself",
                predicate_path,
            )
            return False
        if not callable(predicate):
            _log.error(
                "evennia_links: EVENNIA_WEB_STAFF_PREDICATE=%r is not callable",
                predicate_path,
            )
            return False
        try:
            return bool(predicate(request))
        except Exception:
            _log.exception(
                "evennia_links: configured web staff predicate %r raised",
                predicate_path,
            )
            return False

    lockstring = _setting("EVENNIA_WEB_STAFF_LOCK", _DEFAULT_WEB_STAFF_LOCK)
    if not isinstance(lockstring, str) or not lockstring.strip():
        _log.error("evennia_links: EVENNIA_WEB_STAFF_LOCK is blank or invalid")
        return False
    try:
        return bool(user.locks.check_lockstring(user, lockstring.strip()))
    except Exception:
        _log.exception("evennia_links: web staff lock evaluation failed")
        return False
