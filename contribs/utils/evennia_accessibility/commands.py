# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Accessibility preferences — the +screenreader command.

A shortcut for toggling the ``screenreader_mode`` account option without
going through the generic ``@option`` command. Bare invocation reports the
current state; /on and /off set it.

Add it to your CharacterCmdSet (and AccountCmdSet, if players should reach
it out of character)::

    from evennia_accessibility.commands import CmdScreenreader

    self.add(CmdScreenreader)

The option itself must be registered in ``OPTIONS_ACCOUNT_DEFAULT`` (see
README). Without that registration Evennia's OptionHandler refuses to store
the value; the command reports that plainly instead of raising.
"""

from evennia.commands.default.muxcommand import MuxCommand
from evennia.utils import logger

OPTION_KEY = "screenreader_mode"


class CmdScreenreader(MuxCommand):
    """
    Toggle screen-reader-friendly output mode.

    Usage:
        +screenreader          - Show current setting
        +screenreader/on       - Enable screen-reader output
        +screenreader/off      - Disable screen-reader output

    When enabled, ASCII tables and colour-only indicators in commands that
    support it are replaced with plain text lists that work well with NVDA,
    JAWS, VoiceOver, and similar tools.

    This option is stored on your account and persists across sessions.
    """

    key = "+screenreader"
    aliases = ["+sr"]  # noqa: RUF012
    help_category = "General"
    locks = "cmd:all()"

    def func(self):
        caller = self.caller
        account = getattr(caller, "account", None) or caller

        if not account:
            caller.msg("You must be logged in to use this command.")
            return

        if "on" in self.switches:
            if self._store(account, "True"):
                caller.msg(
                    "|gScreen-reader mode enabled.|n "
                    "Tables and colour indicators will be replaced with plain text."
                )
        elif "off" in self.switches:
            if self._store(account, "False"):
                caller.msg("|gScreen-reader mode disabled.|n Output will use standard formatting.")
        elif self.switches:
            caller.msg(
                f"Unknown switch '/{self.switches[0]}'. "
                "Use |w+screenreader/on|n or |w+screenreader/off|n."
            )
        else:
            enabled = account.options.get(OPTION_KEY, False)
            state = "|gEnabled|n" if enabled else "|xDisabled|n"
            caller.msg(
                f"Screen-reader mode: {state}\n"
                "Use |w+screenreader/on|n or |w+screenreader/off|n to change."
            )

    def _store(self, account, value):
        """Write the option, reporting an unregistered option instead of raising.

        ``OptionHandler.set`` raises ``ValueError("Option not found!")`` when
        the game never added ``screenreader_mode`` to ``OPTIONS_ACCOUNT_DEFAULT``.
        That is a game configuration fault, so the player gets a plain answer
        and the server log gets the fix.
        """
        try:
            account.options.set(OPTION_KEY, value)
        except ValueError:
            logger.log_warn(
                f"+screenreader: '{OPTION_KEY}' is not registered in "
                "OPTIONS_ACCOUNT_DEFAULT; see the evennia_accessibility README."
            )
            self.caller.msg(
                "Screen-reader mode isn't available on this game yet. Please let the staff know."
            )
            return False
        return True


class CmdAmbient(MuxCommand):
    """Mute effects arriving from other rooms or through ambient channels.

    Usage: +ambient, +ambient/mute, +ambient/unmute

    Stored per account, across characters and logins. Effects used in your
    current room remain visible as scene content.
    """

    key = "+ambient"
    help_category = "General"
    locks = "cmd:all()"

    def func(self):
        from .accessibility import mutes_ambient

        account = getattr(self.caller, "account", self.caller)
        if account is None or not hasattr(account, "options"):
            self.msg("You must be logged in to use this command.")
            return
        if not self.switches:
            self.msg(f"Ambient effects: {'muted' if mutes_ambient(account) else 'enabled'}.")
            return
        if len(self.switches) != 1 or self.switches[0] not in ("mute", "unmute"):
            self.msg("Use +ambient, +ambient/mute or +ambient/unmute.")
            return
        try:
            account.options.set("mute_ambient_effects", str(self.switches[0] == "mute"))
        except ValueError:
            self.msg("Ambient preferences aren't available on this game yet. Please tell staff.")
            return
        self.msg(f"Ambient effects: {'muted' if mutes_ambient(account) else 'enabled'}.")
