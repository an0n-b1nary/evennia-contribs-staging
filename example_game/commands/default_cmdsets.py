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

from importlib import import_module

from django.apps import apps
from evennia import default_cmds
from evennia_boards.commands import CmdBoard
from evennia_calendar.commands import CmdCalendar, CmdRsvp
from evennia_jobs.commands import CmdBug, CmdDiscuss, CmdIssue, CmdJobs, CmdRequest
from evennia_lore.commands import CmdForget, CmdHint, CmdInvestigate, CmdLore, CmdShare
from evennia_plots.commands import CmdArc, CmdHook, CmdPlot

from commands.sandbox import CmdSandbox
from evennia_accessibility.commands import CmdScreenreader
from evennia_links.commands import CmdRuntime
from evennia_maps.commands import CmdMap
from evennia_posing.commands import (
    CmdEmit,
    CmdHighlight,
    CmdLastPose,
    CmdPose,
    CmdPoseHeader,
    CmdPot,
    CmdSemipose,
)
from evennia_regions.commands import CmdRegion
from evennia_social.commands import (
    CmdFinger,
    CmdHangouts,
    CmdHome,
    CmdIgnore,
    CmdJoin,
    CmdMood,
    CmdOoc,
    CmdOocTeleport,
    CmdPage,
    CmdRoomConfig,
    CmdRoulette,
    CmdSummon,
    CmdTel,
    CmdWhere,
)


def _optional_commands(app_label, *names):
    """A restart without an optional RP partner removes its commands too."""
    if not apps.is_installed(app_label):
        return ()
    module = import_module(f"{app_label}.commands")
    return tuple(getattr(module, name) for name in names)


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

        # Pose pipeline (evennia_posing) — CmdPose replaces Evennia's stock
        # pose/emote command, the same way the old hand-rolled stopgap did.
        self.add(CmdPose)
        self.add(CmdRuntime)
        for command in _optional_commands(
            "evennia_economy", "CmdBalance", "CmdOffer", "CmdAccept", "CmdGive", "CmdEconomy"
        ):
            self.add(command)
        for command in _optional_commands("evennia_rp_resources", "CmdGather", "CmdResources"):
            self.add(command)
        self.add(CmdEmit)
        self.add(CmdSemipose)
        self.add(CmdPot)
        self.add(CmdLastPose)
        self.add(CmdPoseHeader)
        self.add(CmdHighlight)

        # Social QoL (evennia_social) — CmdTel replaces Evennia's stock @tel.
        self.add(CmdFinger)
        self.add(CmdWhere)
        self.add(CmdHangouts)
        self.add(CmdIgnore)
        self.add(CmdPage)
        self.add(CmdSummon)
        self.add(CmdJoin)
        self.add(CmdOoc)
        self.add(CmdOocTeleport)
        self.add(CmdHome)
        self.add(CmdRoomConfig)
        self.add(CmdMood)
        self.add(CmdRoulette)
        self.add(CmdTel)

        # RP session tracking
        for command in _optional_commands(
            "evennia_rptracker", "CmdActivity", "CmdRPTrackerStaff", "CmdRPActivityReport"
        ):
            self.add(command)

        # Scenes
        for command in _optional_commands("evennia_scenes", "CmdScene", "CmdLog"):
            self.add(command)

        # RP checks and private builds need no character typeclass changes.
        for command in _optional_commands(
            "evennia_rp_chargen",
            "CmdSheet",
            "CmdStats",
            "CmdPips",
            "CmdAbilities",
            "CmdLock",
            "CmdUnlock",
            "CmdSpend",
            "CmdUpgrade",
            "CmdChargen",
        ):
            self.add(command)
        for command in _optional_commands("evennia_rp_contest", "CmdTest"):
            self.add(command)
        for command in _optional_commands(
            "evennia_rp_equipment", "CmdGear", "CmdWear", "CmdRemove", "CmdWorn"
        ):
            self.add(command)

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

        # Regions and maps. Both are open at the command-lock level
        # (locks = "cmd:all()") and self-enforce REGIONS_STAFF_LOCK /
        # MAPS_STAFF_LOCK inside the switches that write — players get the
        # read-only switches (+map, +region), builders get the rest.
        self.add(CmdRegion)
        self.add(CmdMap)

        # XP
        for command in _optional_commands("evennia_xp", "CmdXp"):
            self.add(command)

        # Jobs
        self.add(CmdRequest)
        self.add(CmdBug)
        self.add(CmdIssue)
        self.add(CmdDiscuss)
        self.add(CmdJobs)

        # Demo-only: lets a playtester promote themselves to Builder and back,
        # so one account can see both halves of every contrib's staff lock.
        # Not something to copy into a real game.
        self.add(CmdSandbox)


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

        # Accessibility (evennia_accessibility). Account-level so the toggle is
        # reachable before puppeting — a screen-reader user should not have to
        # read a character-select table to find it. The account cmdset merges
        # into the puppet's, so it works in character too.
        self.add(CmdScreenreader)
        if apps.is_installed("evennia_rptracker"):
            from evennia_rptracker.channel_commands import CmdICChannel

            self.add(CmdICChannel)


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
