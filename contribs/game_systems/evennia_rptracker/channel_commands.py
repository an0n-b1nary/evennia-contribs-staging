# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Evennia 6 channel command with heterogeneous typeclass discovery."""

from evennia.commands.default.comms import CmdChannel
from evennia.comms.models import ChannelDB
from evennia.utils.utils import strip_unsafe_input


class CmdICChannel(CmdChannel):
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
