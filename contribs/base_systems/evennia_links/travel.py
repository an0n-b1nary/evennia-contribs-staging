"""Optional authoritative room travel/visibility policy, independent of ownership.

None means unmanaged: the caller retains its established policy. Configured
providers must return True, False or None; errors deny. No partner imports.
"""

import logging

from django.conf import settings

from .collect import resolve_dotted

logger = logging.getLogger("evennia")


def _answer(setting, actor, room):
    path = getattr(settings, setting, None)
    if not path:
        return None
    try:
        provider = resolve_dotted(path)
        result = (
            provider(room, actor) if setting == "LINKS_ROOM_VISIBILITY" else provider(actor, room)
        )
        if result is not None and type(result) is not bool:
            raise ValueError("Room policy must return True, False or None")
        return result
    except Exception:
        logger.exception("%s failed; denying room access", setting)
        return False


def travel_permission(actor, room):
    return _answer("LINKS_ROOM_TRAVEL", actor, room)


def room_visibility(room, viewer=None):
    return _answer("LINKS_ROOM_VISIBILITY", viewer, room)
