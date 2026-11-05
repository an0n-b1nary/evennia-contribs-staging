# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Evennia 6 channel command with heterogeneous typeclass discovery."""

from django.apps import apps
from evennia.accounts.models import AccountDB
from evennia.commands.default.comms import CmdChannel
from evennia.comms.models import ChannelDB
from evennia.utils import logger
from evennia.utils.utils import strip_unsafe_input

from evennia_links.command_syntax import StrictSwitchMixin
from evennia_links.identity import comms_identity, is_visitor, sending_character


class CmdICChannel(StrictSwitchMixin, CmdChannel):
    """Keep normal channel syntax while including opt-in channel typeclasses."""

    def search_channel(self, channelname, exact=False, handle_errors=True):
        channelname = self.caller.nicks.get(key=channelname, category="channel") or channelname
        channels = ChannelDB.objects.channel_search(channelname, exact=True)
        if not channels and not exact:
            channels = ChannelDB.objects.channel_search(channelname, exact=False)
        channels = [
            channel
            for channel in channels
            if channel.access(self.caller, "listen") or channel.access(self.caller, "control")
        ]
        if not handle_errors:
            return channels
        if len(channels) == 1:
            return channels[0]
        if not channels:
            self.msg(
                f"No channel found matching '{channelname}' (could also be due to missing access)."
            )
        else:
            self.msg(
                f"Multiple possible channel matches/alias for '{channelname}':\n"
                + ", ".join(channel.key for channel in channels)
            )
        return None

    def list_channels(self, channelcls=ChannelDB):
        return super().list_channels(channelcls=channelcls)

    def msg_channel(self, channel, message, **kwargs):
        if not channel.access(self.caller, "send", session=self.session):
            self.msg(f"You are not allowed to send messages to channel {channel}")
            return
        message = strip_unsafe_input(message, self.session)
        return channel.msg(message, senders=self.caller, session=self.session, **kwargs)

    def channel_list_who(self, channel):
        if comms_identity() == "account":
            return super().channel_list_who(channel)

        characters = {}
        newcomers = 0
        muted = set(channel.mutelist)
        for subscriber in channel.subscriptions.online():
            if isinstance(subscriber, AccountDB):
                for session in subscriber.sessions.all():
                    character = subscriber.get_puppet(session)
                    if character is not None:
                        characters[character.pk] = (character, subscriber in muted)
                    elif is_visitor(subscriber, session):
                        newcomers += 1
            else:
                characters[subscriber.pk] = (subscriber, subscriber in muted)

        # Social is optional; its provider owns all presence policy when present.
        is_listed = None
        if apps.is_installed("evennia_social"):
            from evennia_social.presence import is_listed

        names = [
            character.get_display_name(self.caller) + (" (muting)" if muting else "")
            for character, muting in characters.values()
            if is_listed is None or is_listed(character, self.caller)
        ]
        names.sort(key=str.casefold)
        if newcomers:
            names.append(f"and {newcomers} newcomer{'s' if newcomers != 1 else ''}")
        return names

    def boot_user(self, channel, target, quiet=False, reason=""):
        if comms_identity() == "account":
            return super().boot_user(channel, target, quiet=quiet, reason=reason)
        target_name = (sending_character(target) or target).get_display_name(None)
        caller_name = (
            sending_character(self.caller, self.session) or self.caller
        ).get_display_name(None)
        if not channel.subscriptions.has(target):
            return False, f"{target_name} is not connected to channel {channel.key}."
        # DefaultChannel.post_leave_channel removes channel nicks and aliases.
        if not channel.disconnect(target):
            return False, f"Could not disconnect {target_name} from channel {channel.key}."
        reason_text = f" Reason: {reason}" if reason else ""
        target.msg(f"You were booted from channel {channel.key} by {caller_name}.{reason_text}")
        if not quiet:
            channel.msg(f"{target_name} was booted from channel by {caller_name}.{reason_text}")
        logger.log_sec(
            f"Channel Boot: {target} (Channel: {channel}, Reason: {reason}, Caller: {self.caller}"
        )
        return True, ""
