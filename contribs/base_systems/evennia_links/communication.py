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


class CharacterCommsChannelMixin:
    """Character-mode ordinary channels, before CommunicationChannelMixin.

    Compose with DefaultChannel. IC channels already resolve their speakers
    and enforce their own eligibility policy. Subscriptions remain per account.
    """

    comms_identity = "character"

    def msg(self, message, senders=None, bypass_mute=False, **kwargs):
        from evennia.utils.utils import make_iter

        from .guests import welcome_channel
        from .identity import is_visitor, sending_character

        senders = list(make_iter(senders)) if senders else []
        if not isinstance(message, str) or not message.strip():
            return
        if not senders:
            return super().msg(message, bypass_mute=bypass_mute, **kwargs)
        if kwargs.get("emit") or kwargs.get("external"):
            if all(self.access(sender, "control") for sender in senders):
                return super().msg(message, senders=senders, bypass_mute=bypass_mute, **kwargs)
            return

        session = kwargs.get("session")
        if len(senders) == 1:
            sender = senders[0]
            if is_visitor(sender, session):
                try:
                    welcome = welcome_channel()
                except ValueError as exc:
                    sender.msg(str(exc))
                    return
                if self != welcome:
                    sender.msg("Visitors may speak on the welcome channel only.")
                    return
                # A guest with a puppet uses its generated character name.
                speaker = sending_character(sender, session) or sender
            else:
                speaker = sending_character(sender, session)
            if speaker is not None:
                return super().msg(message, senders=[speaker], bypass_mute=bypass_mute, **kwargs)

        for sender in senders:
            sender.msg("Speak on this channel as one puppeted character.")

    def at_post_msg(self, message, **kwargs):
        """Store public display names in the log shared by history and the web."""
        from evennia.utils import logger

        if log_file := self.get_log_filename():
            names = ",".join(sender.get_display_name(None) for sender in kwargs.get("senders", []))
            logger.log_file(f"{names}: {message}" if names else message, log_file)
