# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Named checks: what a page's ``requires`` names, typically a reveal switch.

A check is global, not per reader: a reveal switch is on or off for everyone.
It's read on every request, so a page appears as soon as its switch is on.
A name resolves, first match wins, to:

1. the host's ``GUIDES_CHECKS[name]``: a bool, a callable, or a dotted path to one;
2. a check registered with ``register_check(name, func)``, typically by a
   contrib in its ``AppConfig.ready()``;
3. an ``evennia_links`` runtime setting of that name, when links is installed
   (so ``RP_ECONOMY_REVEALED`` follows a staff toggle without a restart);
4. a Django setting of that name.

An unknown name, or a check that raises, fails closed: the page stays hidden
from players. ``evennia guides_check`` reports unknown names before they reach
a live site.
"""

import logging

from django.utils.module_loading import import_string

from evennia_guides import conf

logger = logging.getLogger("evennia")

_registry = {}
_warned = set()


def register_check(name, func):
    """Register ``func() -> bool`` as the check ``name``. Re-registering replaces it."""
    if not callable(func):
        raise TypeError(f"check {name!r} must be callable")
    _registry[name] = func


def registered():
    return dict(_registry)


def _runtime_setting(name):
    """(found, value) for an evennia_links runtime setting."""
    try:
        from evennia_links import runtime
    except ImportError:
        return False, None
    if name not in runtime.registered():
        return False, None
    return True, runtime.get(name)


def _resolve(name):
    """(found, callable-or-value) for a check name."""
    overrides = conf.get("GUIDES_CHECKS")
    if name in overrides:
        value = overrides[name]
        return True, import_string(value) if isinstance(value, str) else value
    if name in _registry:
        return True, _registry[name]
    found, value = _runtime_setting(name)
    if found:
        return True, value
    from django.conf import settings

    if name.isupper() and hasattr(settings, name):
        return True, getattr(settings, name)
    return False, None


def is_known(name):
    """Whether a check name resolves to anything (for validation)."""
    try:
        return _resolve(name)[0]
    except Exception:
        return False


def check(name):
    """Whether the named check passes now. Unknown or failing checks are False."""
    try:
        found, value = _resolve(name)
        if not found:
            if name not in _warned:
                _warned.add(name)
                logger.warning("evennia_guides: unknown check %r; treating it as off", name)
            return False
        return bool(value() if callable(value) else value)
    except Exception:
        logger.exception("evennia_guides: check %r failed; treating it as off", name)
        return False


def page_visible(page):
    """Whether players may see a player page: every check it requires passes."""
    return page.audience == "player" and all(check(name) for name in page.requires)


def can_view(page, *, staff):
    """Whether a reader may open a page: staff always, players when it's visible."""
    return staff or page_visible(page)


def is_staff(viewer):
    """
    Whether a viewer is guide staff (``GUIDES_STAFF_LOCK``).

    The viewer is a request's user: an Account, an anonymous user, or None.
    """
    if viewer is None or not getattr(viewer, "is_authenticated", True):
        return False
    locks = getattr(viewer, "locks", None)
    if locks is None:
        return False
    return locks.check_lockstring(viewer, conf.get("GUIDES_STAFF_LOCK"))
