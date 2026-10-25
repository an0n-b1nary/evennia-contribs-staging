# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Presence commands: +unfindable, and a ``who`` that honours it.

The rules live in ``evennia_social.presence``; these only set and show them.
"""

import time

import evennia
from evennia.commands.default.account import CmdWho as DefaultCmdWho
from evennia.commands.default.muxcommand import MuxCommand
from evennia.utils import utils

from evennia_social import presence
from evennia_social.identity import staff_run_marker
from evennia_social.social import is_staff

_EXPLAIN = {
    presence.FINDABLE: "You are |wfindable|n: you show up in +where and on the map.",
    presence.UNFINDABLE: (
        "You are |wunfindable|n: left out of who, +where, venue counts and the map. "
        "Anyone in the same room still sees you, and staff see you marked (unfindable)."
    ),
    presence.DARK: (
        "You are |wdark|n: left out of who, +where, venue counts and the map. "
        "Anyone in the same room still sees you, and other staff see you marked (dark)."
    ),
}


class CmdUnfindable(MuxCommand):
    """
    Choose whether others can find your character from afar.

    Usage:
        +unfindable          - Show your current setting
        +unfindable on       - Leave your character out of who, +where and the map
        +unfindable off      - Be listed again
        +unfindable dark     - (staff) The same, marked (dark) for other staff

    Unfindable means unlisted: you don't appear in who, +where, venue counts
    or the map. Anyone in the same room sees you as usual, and staff still see
    you. The setting is per character.
    """

    key = "+unfindable"
    aliases = []  # noqa: RUF012
    help_category = "Social"
    locks = "cmd:all()"

    def func(self):
        caller = self.caller
        arg = self.args.strip().lower()
        if not arg:
            caller.msg(_EXPLAIN[presence.visibility(caller)])
            return
        choice = {"on": presence.UNFINDABLE, "off": presence.FINDABLE, "dark": presence.DARK}.get(
            arg
        )
        if choice is None:
            caller.msg("Usage: +unfindable [on|off|dark]")
            return
        if choice == presence.DARK and not is_staff(caller):
            caller.msg("Only staff can go dark. |w+unfindable on|n hides where you are.")
            return
        presence.set_visibility(caller, choice)
        caller.msg(_EXPLAIN[choice])


class CmdWho(DefaultCmdWho):
    """
    list who is currently online

    Usage:
      who
      doing

    Shows who is currently online. Unfindable characters are left out for
    everyone but staff and anyone in the same room.
    """

    def func(self):
        account = self.account
        privileged = self.cmdstring != "doing" and (
            account.check_permstring("Developer") or account.check_permstring("Admins")
        )
        if privileged:
            # Evennia's privileged table already shows every session.
            super().func()
            return
        # who is an account command: the caller is the account, and the
        # character (if any) is this session's puppet.
        viewer = self.session.get_puppet() if self.session else None
        viewer_is_staff = account.check_permstring("Builder") or (
            viewer is not None and is_staff(viewer)
        )
        sessions = []
        for session in evennia.SESSION_HANDLER.get_sessions():
            if not session.logged_in:
                continue
            puppet = session.get_puppet()
            if (
                puppet is not None
                and not viewer_is_staff
                and not presence.is_listed(puppet, viewer)
            ):
                continue
            sessions.append(session)
        sessions.sort(key=lambda s: s.account.key)
        table = self.styled_table("|wAccount name", "|wOn for", "|wIdle")
        for session in sessions:
            table.add_row(
                utils.crop(session.get_account().get_display_name(account), width=25)
                + staff_run_marker(session.get_account()),
                utils.time_format(time.time() - session.conn_time, 0),
                utils.time_format(time.time() - session.cmd_last_visible, 1),
            )
        naccounts = len({session.account.pk for session in sessions})
        is_one = naccounts == 1
        self.msg(
            f"|wAccounts:|n\n{table}\n{'One' if is_one else naccounts} "
            f"unique account{'' if is_one else 's'} logged in."
        )
