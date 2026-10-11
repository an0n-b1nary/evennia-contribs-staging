# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Room rights without a dependency on an ownership package.

LINKS_ROOM_PERMISSION is a dotted callable(actor, room, action) -> bool.
LINKS_ROOM_OWNER is a dotted callable(room) -> character or None. Providers
are authoritative; missing/broken configured providers fail closed. With no
provider, permissions use Evennia control access and ownership is unknown.
Staff overrides belong to the caller's existing policy, not this helper.
"""

import logging

from django.conf import settings

from .collect import resolve_dotted

_log = logging.getLogger("evennia")
ACTIONS = frozenset({"describe", "configure", "lock", "admit", "install", "transfer"})


def can(actor, room, action):
    """Whether an actor has one of ACTIONS here. Unknown actions deny."""
    if actor is None or room is None or not isinstance(action, str) or action not in ACTIONS:
        return False
    try:
        path = getattr(settings, "LINKS_ROOM_PERMISSION", None)
        if not path:
            return bool(room.access(actor, "control"))
        provider = resolve_dotted(path)
        if not callable(provider) or provider is can:
            raise ValueError("Invalid room permission provider")
        return bool(provider(actor, room, action))
    except Exception:
        _log.exception("evennia_links: room permission lookup failed; denying %s", action)
        return False


def owner_of(room):
    """The owning character, or None. Control access does not imply ownership."""
    if room is None:
        return None
    try:
        path = getattr(settings, "LINKS_ROOM_OWNER", None)
        if not path:
            return None
        provider = resolve_dotted(path)
        if not callable(provider) or provider is owner_of:
            raise ValueError("Invalid room owner provider")
        owner = provider(room)
        if owner is not None:
            from evennia.objects.models import ObjectDB

            if not isinstance(owner, ObjectDB) or not owner.pk:
                raise ValueError("Room owner must be a saved ObjectDB or None")
        return owner
    except Exception:
        _log.exception("evennia_links: room owner lookup failed; returning no owner")
        return None
