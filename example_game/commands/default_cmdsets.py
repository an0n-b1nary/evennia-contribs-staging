"""
Command sets

All commands in the game must be grouped in a cmdset.  A given command
can be part of any number of cmdsets and cmdsets can be added/removed
and merged onto entities at runtime.

To create new commands to populate the cmdset, see
`commands/command.py`.

This module wraps the default command sets of Evennia; overloads them
to add/remove commands from the default lineup. You can create your
own cmdsets by inheriting from them or directly from `evennia.CmdSet`.

"""

from evennia import default_cmds
from evennia_boards.commands import CmdBoard
from evennia_calendar.commands import CmdCalendar, CmdRsvp
from evennia_jobs.commands import CmdBug, CmdDiscuss, CmdIssue, CmdJobs, CmdRequest
from evennia_lore.commands import CmdForget, CmdHint, CmdInvestigate, CmdLore, CmdShare
from evennia_plots.commands import CmdArc, CmdHook, CmdPlot
from evennia_rptracker.commands import CmdActivity, CmdRPTrackerStaff
from evennia_scenes.commands import CmdLog, CmdScene
from evennia_xp.commands import CmdXp

from commands.pose_seam import CmdSandboxPose


class CharacterCmdSet(default_cmds.CharacterCmdSet):
    """
    The `CharacterCmdSet` contains general in-game commands like `look`,
    `get`, etc available on in-game Character objects. It is merged with
    the `AccountCmdSet` when an Account puppets a Character.
    """

    key = "DefaultCharacter"

    def at_cmdset_creation(self):
        """
        Populates the cmdset
        """
        super().at_cmdset_creation()

        # Replaces the stock pose/emote command — same behavior, plus the
        # rptracker/scenes seam calls. See commands/pose_seam.py.
        self.add(CmdSandboxPose)

        # RP session tracking
        self.add(CmdActivity)
        self.add(CmdRPTrackerStaff)

        # Scenes
        self.add(CmdScene)
        self.add(CmdLog)

        # Boards
        self.add(CmdBoard)

        # Calendar
        self.add(CmdCalendar)
        self.add(CmdRsvp)

        # Lore
        self.add(CmdLore)
        self.add(CmdInvestigate)
        self.add(CmdShare)
        self.add(CmdHint)
        self.add(CmdForget)

        # Plots — CmdArc/CmdHook are open at the command-lock level
        # (locks = "cmd:all()") but self-enforce PLOTS_STAFF_LOCK inside
        # func(), so they're safe to add here alongside CmdPlot.
        self.add(CmdPlot)
        self.add(CmdArc)
        self.add(CmdHook)

        # XP
        self.add(CmdXp)

        # Jobs
        self.add(CmdRequest)
        self.add(CmdBug)
        self.add(CmdIssue)
        self.add(CmdDiscuss)
        self.add(CmdJobs)


class AccountCmdSet(default_cmds.AccountCmdSet):
    """
    This is the cmdset available to the Account at all times. It is
    combined with the `CharacterCmdSet` when the Account puppets a
    Character. It holds game-account-specific commands, channel
    commands, etc.
    """

    key = "DefaultAccount"

    def at_cmdset_creation(self):
        """
        Populates the cmdset
        """
        super().at_cmdset_creation()

        # Boards support account-level (pre-puppet) reading and subscription,
        # per evennia_boards' README — expose +bb without a puppet too.
        self.add(CmdBoard)


class UnloggedinCmdSet(default_cmds.UnloggedinCmdSet):
    """
    Command set available to the Session before being logged in.  This
    holds commands like creating a new account, logging in, etc.
    """

    key = "DefaultUnloggedin"

    def at_cmdset_creation(self):
        """
        Populates the cmdset
        """
        super().at_cmdset_creation()
        #
        # any commands you add below will overload the default ones.
        #


class SessionCmdSet(default_cmds.SessionCmdSet):
    """
    This cmdset is made available on Session level once logged in. It
    is empty by default.
    """

    key = "DefaultSession"

    def at_cmdset_creation(self):
        """
        This is the only method defined in a cmdset, called during
        its creation. It should populate the set with command instances.

        As and example we just add the empty base `Command` object.
        It prints some info.
        """
        super().at_cmdset_creation()
        #
        # any commands you add below will overload the default ones.
        #
