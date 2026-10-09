# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Opt-in IC channels; import typeclasses only after Evennia initializes."""

import logging

from evennia.accounts.models import AccountDB
from evennia.comms.comms import DefaultChannel
from evennia.utils.utils import make_iter

from evennia_rptracker.channel_tracker import eligible, end_subscriber_sessions

logger = logging.getLogger("evennia")


def sending_character(sender, session=None):
    """Resolve a single active character; never pick arbitrarily among puppets."""
    if isinstance(sender, AccountDB):
        if session is not None:
            character = sender.get_puppet(session)
            if character is not None and getattr(character, "account", None) == sender:
                return character
            return None
        puppets = {obj.pk: obj for obj in sender.get_all_puppets()}
        return next(iter(puppets.values())) if len(puppets) == 1 else None
    return sender if getattr(sender, "account", None) else None


class ICChannel(DefaultChannel):
    """Character-attributed channel with passive session collection and normal history.

    Configure RPTRACKER_CHANNEL_ELIGIBLE(character) for host policy. Unattributed
    system messages and staff emits are logged but never count as RP.
    """

    def msg(self, message, senders=None, bypass_mute=False, **kwargs):
        senders = list(make_iter(senders)) if senders else []
        if not isinstance(message, str) or not message.strip():
            return
        if not senders:
            return self._deliver(message, [], bypass_mute, kwargs)
        if kwargs.get("emit") or kwargs.get("external"):
            if all(self.access(sender, "control") for sender in senders):
                return self._deliver(message, senders, bypass_mute, kwargs)
            return
        character = (
            sending_character(senders[0], kwargs.get("session")) if len(senders) == 1 else None
        )
        if (
            character is None
            or not eligible(character)
            or not self.access(senders[0], "send", session=kwargs.get("session"))
        ):
            for sender in senders:
                sender.msg("Speak on this IC channel as one eligible puppeted character.")
            return
        return self._deliver(
            message, [character], bypass_mute, {**kwargs, "_ic_character": character}
        )

    def _deliver(self, message, senders, bypass_mute, kwargs):
        """Use Evennia's receive hooks, rechecking listen access for subscribers.

        A character can cease qualifying after joining. A muted or ineligible
        recipient must not abort delivery to the other subscribers.
        """
        kwargs = {**kwargs, "senders": senders, "bypass_mute": bypass_mute}
        message = self.at_pre_msg(message, **kwargs)
        if message in (None, False):
            return
        receivers = (
            self.subscriptions.online() if self.send_to_online_only else self.subscriptions.all()
        )
        for receiver in receivers:
            if (not bypass_mute and receiver in self.mutelist) or not self.access(
                receiver, "listen"
            ):
                continue
            try:
                rendered = receiver.at_pre_channel_msg(message, self, **kwargs)
                if rendered in (None, False):
                    continue
                receiver.channel_msg(rendered, self, **kwargs)
                receiver.at_post_channel_msg(rendered, self, **kwargs)
            except Exception:
                logger.exception("RPTracker: channel delivery failed for receiver #%s", receiver.pk)
        self.at_post_msg(message, **kwargs)

    def at_post_msg(self, message, **kwargs):
        super().at_post_msg(message, **kwargs)
        character = kwargs.get("_ic_character")
        if character is not None:
            try:
                from evennia_rptracker import record_rp_channel_activity

                record_rp_channel_activity(character, self)
            except Exception:
                logger.exception("RPTracker: channel collection failed on channel #%s", self.pk)

    def post_leave_channel(self, leaver, **kwargs):
        super().post_leave_channel(leaver, **kwargs)
        end_subscriber_sessions(leaver, self.pk)

    def delete(self):
        from evennia_rptracker.channel_tracker import _active_channel_sessions, end_channel_session

        for key in list(_active_channel_sessions):
            if key[1] == self.pk:
                end_channel_session(*key)
        return super().delete()
