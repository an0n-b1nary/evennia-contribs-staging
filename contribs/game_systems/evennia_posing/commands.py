# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Pose pipeline commands.

Overrides Evennia's default pose command and adds emit/semipose, the pose
order tracker (+pot), last-pose recall (+lastpose), and player-configurable
pose headers (+poseheader) and name highlighting (+highlight).

Requires the caller's Character typeclass to mix in
``evennia_posing.PosingCharacterMixin`` (for ``record_pose()``,
``last_pose_time``, ``last_pose_text``, ``pose_status``) and, for +pot/
+lastpose, the caller's Room typeclass to mix in
``evennia_posing.PosingRoomMixin`` (for ``get_characters_by_pose_time()``).

Add to your CharacterCmdSet::

    from evennia_posing.commands import (
        CmdPose, CmdEmit, CmdSemipose, CmdPot, CmdLastPose,
        CmdPoseHeader, CmdHighlight,
    )
    self.add(CmdPose)       # replaces Evennia's stock CmdPose
    self.add(CmdEmit)
    self.add(CmdSemipose)
    self.add(CmdPot)
    self.add(CmdLastPose)
    self.add(CmdPoseHeader)
    self.add(CmdHighlight)
"""

from evennia.commands.default.general import CmdPose as DefaultCmdPose
from evennia.commands.default.muxcommand import MuxCommand

from evennia_posing.highlighting import format_pose_time

# Screenreader support is optional; falls back to always-False when
# evennia-accessibility is not installed. Mirrors the pattern used by
# evennia_boards and other contribs in this repo.
try:
    from evennia_accessibility import uses_screenreader
except ImportError:

    def uses_screenreader(_caller):
        return False


# =====================================================================
# Pose/Emit/Semipose overrides
# =====================================================================


class CmdPose(DefaultCmdPose):
    """
    Strike a pose.

    Usage:
        pose <pose text>
        :<pose text>

    Example:
        pose leans against the wall.
        :nods slowly.

    Describe an action or state. Your character name is automatically
    prepended. Use a leading apostrophe for possessives: :'s eyes narrow.
    """

    # Inherit key, aliases, locks from DefaultCmdPose.
    help_category = "Roleplaying"

    def func(self):
        """Execute the pose and record it for +pot tracking."""
        # Note: DefaultCmdPose.parse() overrides MuxCommand.parse() with
        # custom emote-space handling and never sets self.rhs, so only
        # self.args is meaningful here.
        if not self.args:
            self.caller.msg("What do you want to pose?")
            return
        # Build the pose text the same way Evennia does (name + args).
        pose_text = f"{self.caller.name}{self.args}"
        # Let Evennia handle formatting and delivery.
        super().func()
        # Record for pose tracking (+pot, +lastpose, and pose_recorded
        # signal listeners).
        self.caller.record_pose(pose_text, pose_type="pose")


class CmdEmit(MuxCommand):
    """
    Emit freeform text to the room.

    Usage:
        emit <text>
        \\\\<text>

    Send a freeform message to the room without your character name
    prepended. Useful for environmental descriptions, narration, or
    action text where you want full control over the format.
    """

    key = "emit"
    aliases = ["\\\\"]  # noqa: RUF012
    help_category = "Roleplaying"
    locks = "cmd:all()"

    def func(self):
        """Execute the emit."""
        if not self.args:
            self.caller.msg("What do you want to emit?")
            return
        text = self.args.strip()
        if not self.caller.location:
            self.caller.msg("You have no location to emit to.")
            return
        # Send to the room (including the caller).
        self.caller.location.msg_contents(text=(text, {"type": "pose"}), from_obj=self.caller)
        # Record for pose tracking.
        self.caller.record_pose(text, pose_type="emit")


class CmdSemipose(MuxCommand):
    """
    Pose with your name directly joined (no space).

    Usage:
        semipose <text>
        ;<text>

    Example:
        ;'s eyes narrow.     -> Korben's eyes narrow.
        ;-shaped shadow       -> Korben-shaped shadow

    Like pose, but your character name is prepended without a trailing
    space. Primarily used for possessives and hyphenated constructions.
    """

    key = "semipose"
    aliases = [";"]  # noqa: RUF012
    help_category = "Roleplaying"
    locks = "cmd:all()"

    def func(self):
        """Execute the semipose."""
        if not self.args:
            self.caller.msg("What do you want to pose?")
            return
        if not self.caller.location:
            self.caller.msg("You have no location to pose in.")
            return
        # No space between name and args — that's the whole point.
        pose_text = f"{self.caller.name}{self.args}"
        self.caller.location.msg_contents(text=(pose_text, {"type": "pose"}), from_obj=self.caller)
        # pose_type="pose" (not "semipose") — downstream consumers like
        # evennia_scenes' LogType have no dedicated "semipose" value, and a
        # semipose is functionally a pose with no space before the text.
        self.caller.record_pose(pose_text, pose_type="pose")


# =====================================================================
# Pose Order Tracker
# =====================================================================


class CmdPot(MuxCommand):
    """
    View the pose order tracker.

    Usage:
        +pot              - Display the pose order for this room
        +pot/obs          - Toggle your status to Observing
        +pot/afk          - Toggle your status to AFK
        +pot/ic           - Set your status back to IC

    Displays a sorted list of characters in the room, ordered by time
    since last pose (longest wait first = whose turn it is). Posing
    resets your timer automatically.
    """

    key = "+pot"
    aliases = []  # noqa: RUF012
    help_category = "Roleplaying"
    locks = "cmd:all()"

    def func(self):
        """Execute command."""
        caller = self.caller

        # Handle status switches.
        if self.switches:
            switch = self.switches[0].lower()
            if switch == "obs":
                if caller.pose_status == "observing":
                    caller.pose_status = "ic"
                    caller.msg("You are no longer observing.")
                else:
                    caller.pose_status = "observing"
                    caller.msg("You are now observing.")
                return
            elif switch == "afk":
                if caller.pose_status == "afk":
                    caller.pose_status = "ic"
                    caller.msg("You are no longer AFK.")
                else:
                    caller.pose_status = "afk"
                    caller.msg("You are now AFK.")
                return
            elif switch == "ic":
                caller.pose_status = "ic"
                caller.msg("Your status is now IC.")
                return
            else:
                caller.msg(f"|wUnknown switch:|n /{switch}. See |whelp +pot|n.")
                return

        # Display pose order.
        if not caller.location:
            caller.msg("You have no location.")
            return

        characters = caller.location.get_characters_by_pose_time()
        if not characters:
            caller.msg("No characters here.")
            return

        # Screen-reader mode: plain list instead of fixed-width table.
        if uses_screenreader(caller):
            count = len(characters)
            lines = [f"Pose Order: {count} character{'s' if count != 1 else ''} present"]
            for char in characters:
                name = char.get_display_name(caller)
                status = getattr(char, "pose_status", "ic").upper()
                if status == "AFK" or char.last_pose_time is None:
                    time_str = "--"
                else:
                    time_str = format_pose_time(char.last_pose_time)
                lines.append(f"  {name} — {time_str} ({status})")
            caller.msg("\n".join(lines))
            return

        # Build the table.
        header = "|w+========================== Pose Order " "===========================+|n"
        col_header = f" |w{'Name':<30} {'Time':<12} {'Status':<6}|n"
        separator = "|x" + "-" * 57 + "|n"

        rows = []
        for char in characters:
            name = char.get_display_name(caller)
            # Truncate long names to fit the column.
            if len(name) > 29:
                name = name[:26] + "..."

            status = getattr(char, "pose_status", "ic").upper()

            # AFK characters show -- for time (their wait is irrelevant).
            if status == "AFK" or char.last_pose_time is None:
                time_str = "--"
            else:
                time_str = format_pose_time(char.last_pose_time)

            rows.append(f" {name:<30} {time_str:<12} {status:<6}")

        footer_count = f" {len(characters)} character{'s' if len(characters) != 1 else ''} present"
        footer_line = "|w+=======================================================" "=+|n"

        output = "\n".join(
            [header, col_header, separator, *rows, separator, footer_count, footer_line]
        )
        caller.msg(output)


# =====================================================================
# Last Pose Recall
# =====================================================================


class CmdLastPose(MuxCommand):
    """
    View recent poses in the room.

    Usage:
        +lastpose              - Show the last pose from each character
        +lastpose <character>  - Show a specific character's last pose

    Aliases: +lp

    Displays the most recent pose from characters in the current room.
    Without arguments, shows a summary of everyone's last pose (truncated).
    With a character name, shows their full last pose.
    """

    key = "+lastpose"
    aliases = ["+lp"]  # noqa: RUF012
    help_category = "Roleplaying"
    locks = "cmd:all()"

    def func(self):
        """Execute command."""
        caller = self.caller

        if not caller.location:
            caller.msg("You have no location.")
            return

        if self.args:
            # Show a specific character's full last pose.
            target = caller.search(self.args.strip())
            if not target:
                return  # caller.search() already sends error message
            pose = getattr(target, "last_pose_text", "")
            if not pose:
                caller.msg(f"{target.get_display_name(caller)} has no recent pose.")
                return
            caller.msg(f"|w--- {target.get_display_name(caller)} ---|n\n{pose}")
            return

        # Show summary of all characters' last poses.
        characters = caller.location.get_characters_by_pose_time()
        # Reverse: most recent first for readability.
        characters = list(reversed(characters))

        if not characters:
            caller.msg("No characters here.")
            return

        lines = ["|w--- Last Poses ---|n"]
        found_any = False
        for char in characters:
            pose = getattr(char, "last_pose_text", "")
            if not pose:
                continue
            found_any = True
            name = char.get_display_name(caller)
            # Truncate long poses for the summary view.
            if len(pose) > 200:
                pose = pose[:200] + "..."
            lines.append(f"|w{name}:|n {pose}")

        if not found_any:
            caller.msg("No recent poses in this room.")
            return

        caller.msg("\n".join(lines))


# =====================================================================
# Pose Header Configuration
# =====================================================================


class CmdPoseHeader(MuxCommand):
    """
    Configure pose header display.

    Usage:
        +poseheader                    - Show current settings
        +poseheader/on                 - Enable pose headers
        +poseheader/off                - Disable pose headers
        +poseheader/format <string>    - Set header format ({name} required)
        +poseheader/separator <string> - Set separator between poses
        +poseheader/separator          - Clear separator

    Toggle and configure the optional header displayed above each pose.
    The header shows the posing character's name. Use {name} as the
    placeholder in format strings.

    Examples:
        +poseheader/format --- {name} ---
        +poseheader/format |w[{name}]|n
        +poseheader/separator |x--- --- ---|n
    """

    key = "+poseheader"
    aliases = ["+ph"]  # noqa: RUF012
    help_category = "Roleplaying"
    locks = "cmd:all()"

    def func(self):
        """Execute command."""
        caller = self.caller
        account = caller.account
        if not account:
            caller.msg("You must be logged in to configure pose headers.")
            return

        if not self.switches:
            # Display current settings.
            enabled = account.options.get("show_pose_headers", True)
            fmt = account.options.get("pose_header_format", "--- {name} ---")
            separator = account.options.get("pose_separator", "")

            status = "|gON|n" if enabled else "|rOFF|n"
            sep_display = f'"|w{separator}|n"' if separator else "(none)"

            # Show a preview using the caller's own name.
            preview = fmt.format(name=caller.get_display_name(caller))

            caller.msg(
                f"|w+== Pose Header Settings ==+|n\n"
                f" Status:    {status}\n"
                f" Format:    |w{fmt}|n\n"
                f" Separator: {sep_display}\n"
                f" Preview:   {preview}"
            )
            return

        switch = self.switches[0].lower()

        if switch == "on":
            account.options.set("show_pose_headers", "True")
            caller.msg("Pose headers |genabled|n.")

        elif switch == "off":
            account.options.set("show_pose_headers", "False")
            caller.msg("Pose headers |rdisabled|n.")

        elif switch == "format":
            if not self.args:
                caller.msg("Usage: |w+poseheader/format <format string>|n")
                return
            fmt = self.args.strip()
            if "{name}" not in fmt:
                caller.msg(
                    "Format string must contain |w{name}|n as a placeholder.\n"
                    "Example: |w+poseheader/format --- {name} ---|n"
                )
                return
            account.options.set("pose_header_format", fmt)
            preview = fmt.format(name=caller.get_display_name(caller))
            caller.msg(f"Pose header format set. Preview: {preview}")

        elif switch == "separator":
            separator = self.args.strip() if self.args else ""
            account.options.set("pose_separator", separator)
            if separator:
                caller.msg(f'Pose separator set to: "{separator}"')
            else:
                caller.msg("Pose separator cleared.")

        else:
            caller.msg(f"|wUnknown switch:|n /{switch}. " "See |whelp +poseheader|n.")


# =====================================================================
# Name Highlight Configuration
# =====================================================================


class CmdHighlight(MuxCommand):
    """
    Configure name highlighting in poses.

    Usage:
        +highlight                 - Show current settings
        +highlight/on              - Enable name highlighting
        +highlight/off             - Disable name highlighting
        +highlight/self <color>    - Set your name's highlight color
        +highlight/others <color>  - Set other characters' highlight color

    Automatically color-highlights character names within poses.
    Your own name is highlighted in one color, other characters in another.

    Color codes: |rr|n=red, |gg|n=green, |yy|n=yellow, |bb|n=blue,
    |mm|n=magenta, |cc|n=cyan, |ww|n=white, |xx|n=dark grey.
    Uppercase for bright: |RR|n, |GG|n, |YY|n, etc.

    Examples:
        +highlight/self y          - Highlight your name in yellow
        +highlight/others g        - Highlight others in green
    """

    key = "+highlight"
    aliases = ["+hl"]  # noqa: RUF012
    help_category = "Roleplaying"
    locks = "cmd:all()"

    VALID_COLORS = set("rgybmcwxRGYBMCWX")  # noqa: RUF012

    def func(self):
        """Execute command."""
        caller = self.caller
        account = caller.account
        if not account:
            caller.msg("You must be logged in to configure highlighting.")
            return

        if not self.switches:
            # Display current settings with preview.
            enabled = account.options.get("highlight_enabled", True)
            self_color = account.options.get("highlight_self_color", "w")
            others_color = account.options.get("highlight_others_color", "c")

            status = "|gON|n" if enabled else "|rOFF|n"
            self_preview = f"|{self_color}{caller.key}|n"
            others_preview = f"|{others_color}OtherCharacter|n"

            caller.msg(
                f"|w+== Name Highlighting ==+|n\n"
                f" Status:       {status}\n"
                f" Self color:   |{self_color}{self_color}|n"
                f" (preview: {self_preview})\n"
                f" Others color: |{others_color}{others_color}|n"
                f" (preview: {others_preview})"
            )
            return

        switch = self.switches[0].lower()

        if switch == "on":
            account.options.set("highlight_enabled", "True")
            caller.msg("Name highlighting |genabled|n.")

        elif switch == "off":
            account.options.set("highlight_enabled", "False")
            caller.msg("Name highlighting |rdisabled|n.")

        elif switch in ("self", "others"):
            color = self.args.strip() if self.args else ""
            if not color or color not in self.VALID_COLORS:
                caller.msg(
                    f"Usage: |w+highlight/{switch} <color>|n\n"
                    f"Valid colors: r, g, y, b, m, c, w, x "
                    f"(uppercase for bright)."
                )
                return
            option_key = "highlight_self_color" if switch == "self" else "highlight_others_color"
            account.options.set(option_key, color)
            preview = f"|{color}{caller.key}|n"
            label = "Self" if switch == "self" else "Others"
            caller.msg(f"{label} highlight color set to: {preview}")

        else:
            caller.msg(f"|wUnknown switch:|n /{switch}. " "See |whelp +highlight|n.")
