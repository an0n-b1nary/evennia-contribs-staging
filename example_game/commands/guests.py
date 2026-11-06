"""Explicit guest command surface; newly installed commands stay unavailable."""

from django.conf import settings
from evennia import CmdSet, default_cmds
from evennia.commands.default.muxcommand import MuxCommand
from evennia.utils.utils import class_from_module

from evennia_links.guests import welcome_channel


class CmdWelcome(MuxCommand):
    """Chat with guests and welcoming players: welcome <message>."""

    key = "welcome"
    aliases = ["wel"]  # noqa: RUF012
    locks = "cmd:all()"
    help_category = "Communication"

    def func(self):
        account = self.caller.account if hasattr(self.caller, "account") else self.caller
        try:
            channel = welcome_channel()
        except ValueError as exc:
            self.msg(str(exc))
            return
        if (
            account in channel.banlist
            or not channel.has_connection(account)
            or not channel.access(account, "send")
        ):
            self.msg("You cannot speak on the Welcome channel.")
            return
        if not self.args.strip():
            self.msg("Use welcome <message> to chat with guests and welcoming players.")
            return
        channel.msg(self.args.strip(), senders=account, session=self.session)


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
        self.add(CmdWelcome)
        from evennia_social.commands import CmdPage

        self.add(CmdPage)
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
            "+abilities",
            "+spend",
            "+upgrade",
            "+lock",
            "+unlock",
            "+test",
            "+request",
            "+bug",
            "+apply",
        }
        for command in class_from_module(settings.CMDSET_CHARACTER)().commands:
            if command.key in allowed:
                self.add(command)
