# SPDX-License-Identifier: BSD-3-Clause
"""Optional communication restrictions, shared by commands and write services.

Receivers return a denial message or None. Restrictions compose: any denial
wins. Receiver errors fail closed rather than silently allowing a message.
"""

import logging

from django.core.exceptions import PermissionDenied
from django.dispatch import Signal

communication_requested = Signal()  # actor, kind, target
logger = logging.getLogger("evennia")


def denial(actor, kind, target=None):
    for _, result in communication_requested.send_robust(
        sender=denial, actor=actor, kind=kind, target=target
    ):
        if isinstance(result, Exception):
            logger.error("Communication restriction failed", exc_info=result)
            return "Communication is temporarily unavailable. Please contact staff."
        if result:
            return str(result)
    return None


def require_communication(actor, kind, target=None):
    message = denial(actor, kind, target)
    if message:
        raise PermissionDenied(message)


class CommunicationCharacterMixin:
    """Put before DefaultCharacter; covers stock say/whisper and direct at_say."""

    def at_pre_say(self, message, **kwargs):
        blocked = denial(self, "room")
        if blocked:
            self.msg(blocked)
            return None
        return super().at_pre_say(message, **kwargs)

    def at_say(self, message, *args, **kwargs):
        if message is None:
            return None
        blocked = denial(self, "room")
        if blocked:
            self.msg(blocked)
            return None
        if message is not None:
            return super().at_say(message, *args, **kwargs)


class CommunicationChannelMixin:
    """Put before DefaultChannel or an IC channel typeclass; system emits pass."""

    def at_pre_msg(self, message, **kwargs):
        from evennia.utils.utils import make_iter

        for actor in make_iter(kwargs.get("senders") or []):
            blocked = denial(actor, "channel", self)
            if blocked:
                actor.msg(blocked)
                return None
        return super().at_pre_msg(message, **kwargs)
