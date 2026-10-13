"""Explicit guest command surface; newly installed commands stay unavailable."""

from django.conf import settings
from evennia import CmdSet, default_cmds
from evennia.commands.default.muxcommand import MuxCommand
from evennia.utils.utils import class_from_module


class CmdGuestChat(MuxCommand):
    """Chat with guests and welcoming players: guest <message>."""

    key = "guest"
    aliases = ["g"]  # noqa: RUF012
    locks = "cmd:all()"
    help_category = "Communication"

    def func(self):
        from evennia.comms.models import ChannelDB

        account = self.caller.account if hasattr(self.caller, "account") else self.caller
        channels = list(ChannelDB.objects.get_by_tag("chat", category="guest"))
        if len(channels) != 1:
            self.msg("The guest channel is unavailable. Please contact staff.")
            return
        channel = channels[0]
        if (
            account in channel.banlist
            or not channel.has_connection(account)
            or not channel.access(account, "send")
        ):
            self.msg("You cannot speak on the guest channel.")
            return
        if not self.args.strip():
            self.msg("Use guest <message> to chat with guests and welcoming players.")
            return
        channel.msg(self.args.strip(), senders=account)


class GuestAccountCmdSet(CmdSet):
    key = "GuestAccount"
    priority = 90
    mergetype = "Replace"
    no_channels = True
    no_objs = True

    def at_cmdset_creation(self):
        from evennia_social.commands import CmdWho

        self.add(default_cmds.CmdQuit)
        self.add(default_cmds.CmdHelp)
        self.add(CmdWho)
        self.add(CmdGuestChat)
        from django.apps import apps

        if apps.is_installed("evennia_accessibility"):
            from evennia_accessibility.commands import CmdAmbient, CmdScreenreader

            self.add(CmdScreenreader)
            self.add(CmdAmbient)


class GuestCharacterCmdSet(GuestAccountCmdSet):
    key = "GuestCharacter"
    priority = 100
    no_exits = False

    def at_cmdset_creation(self):
        super().at_cmdset_creation()
        # Select host commands, preserving aliases and vocabulary subclasses.
        allowed = {
            "look",
            "inventory",
            "say",
            "whisper",
            "pose",
            "semipose",
            "emit",
            "+pot",
            "+lastpose",
            "+poseheader",
            "+highlight",
            "+ooc",
            "+home",
            "home",
            "page",
            "+finger",
            "+where",
            "+sheet",
            "+stats",
            "+pips",
            "+edge",
            "+abilities",
            "+spend",
            "+upgrade",
            "+lock",
            "+unlock",
            "+test",
            "+request",
            "+bug",
        }
        for command in class_from_module(settings.CMDSET_CHARACTER)().commands:
            if command.key in allowed:
                self.add(command)
