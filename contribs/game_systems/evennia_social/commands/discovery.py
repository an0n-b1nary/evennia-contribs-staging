# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Player discovery commands — +where and +hangouts.

Provides location-based player discovery: who's where, which hangout
venues are active, and room population counts.

Requires the caller's Room typeclass to mix in
``evennia_social.SocialRoomMixin`` (for ``hangout_type``) and
``evennia_posing.PosingCharacterMixin`` on Character (for
``last_pose_time``/``pose_status``, read via ``format_pose_time``).
"""

from collections import defaultdict

from evennia.commands.default.muxcommand import MuxCommand
from evennia.objects.models import ObjectDB

from evennia_posing.highlighting import format_pose_time
from evennia_social.social import get_connected_characters, is_staff
from evennia_social.typeclasses import HANGOUT_TYPES

# Screenreader support is optional; falls back to always-False when
# evennia-accessibility is not installed. Mirrors the pattern used by
# evennia_posing and evennia_boards.
try:
    from evennia_accessibility import uses_screenreader
except ImportError:

    def uses_screenreader(_caller):
        return False


class CmdWhere(MuxCommand):
    """
    List connected characters and their locations.

    Usage:
        +where              - Show all connected characters by room
        +where/ic           - Show only characters in IC rooms
        +where/ooc          - Show only characters in OOC rooms
        +where/count        - Show room population counts only

    Respects IC/OOC visibility rules. Staff rooms are only visible
    to staff members.
    """

    key = "+where"
    aliases = []  # noqa: RUF012
    help_category = "Social"
    locks = "cmd:all()"

    def func(self):
        caller = self.caller

        if not self.switches:
            caller.msg(self._format(caller))
            return

        switch = self.switches[0].lower()

        if switch == "ic":
            caller.msg(self._format(caller, filter_type="ic"))
        elif switch == "ooc":
            caller.msg(self._format(caller, filter_type="ooc"))
        elif switch == "count":
            caller.msg(self._format_count(caller))
        else:
            caller.msg(f"|rUnknown switch:|n /{switch}. See |whelp +where|n for usage.")

    @staticmethod
    def _format(viewer, filter_type=None):
        """Build the +where display string.

        Args:
            viewer: The character viewing +where.
            filter_type: None (all), "ic", or "ooc".
        """
        width = 68
        is_viewer_staff = is_staff(viewer)
        characters = get_connected_characters()

        # Group characters by room, applying visibility rules.
        rooms = defaultdict(list)
        for char in characters:
            if not char.location:
                continue
            room = char.location
            # room_type is a shared, contrib-agnostic Room attribute: owned
            # by no contrib, defaulted defensively. See README.
            room_type = getattr(room, "room_type", "ic") or "ic"

            # Staff rooms hidden from non-staff.
            if room_type == "staff" and not is_viewer_staff:
                continue

            # Apply filter if requested.
            if filter_type and room_type != filter_type:
                continue

            rooms[room].append(char)

        # Sort rooms by population descending, then name ascending.
        sorted_rooms = sorted(rooms.items(), key=lambda r: (-len(r[1]), r[0].key))

        # Screen-reader mode: plain list instead of bordered table.
        if uses_screenreader(viewer):
            total = sum(len(c) for _, c in sorted_rooms)
            lines = [f"Who's Where: {total} character{'s' if total != 1 else ''} online"]
            for room, chars in sorted_rooms:
                room_type = getattr(room, "room_type", "ic") or "ic"
                char_descs = []
                for char in sorted(chars, key=lambda c: c.last_pose_time or 0):
                    name = char.get_display_name(looker=viewer)
                    idle = format_pose_time(char.last_pose_time)
                    if char.pose_status == "afk":
                        idle = "--"
                    status = char.pose_status.upper() if char.pose_status else "IC"
                    char_descs.append(f"{name} (idle {idle}, {status})")
                lines.append(
                    f"  {room.key} ({room_type.upper()}): "
                    + (", ".join(char_descs) if char_descs else "empty")
                )
            return "\n".join(lines)

        lines = []
        header = " Who's Where "
        lines.append(f"|w+{'=' * (width - 2)}+|n")
        pad = width - 2 - len(header)
        left = pad // 2
        right = pad - left
        lines.append(f"|w+{'=' * left}{header}{'=' * right}+|n")

        if not sorted_rooms:
            lines.append(" No characters found.")
        else:
            total = 0
            for room, chars in sorted_rooms:
                room_type = getattr(room, "room_type", "ic") or "ic"
                type_label = room_type.upper()
                count = len(chars)
                total += count
                plural = "character" if count == 1 else "characters"
                lines.append(f" |w{room.key}|n ({type_label}) — {count} {plural}")

                # Sort by pose time ascending (longest wait first).
                chars.sort(key=lambda c: c.last_pose_time or 0)
                for char in chars:
                    name = char.get_display_name(looker=viewer)
                    if len(name) > 34:
                        name = name[:31] + "..."
                    idle = format_pose_time(char.last_pose_time)
                    if char.pose_status == "afk":
                        idle = "--"
                    status = char.pose_status.upper() if char.pose_status else "IC"
                    lines.append(f"   {name:<34} {idle:<9}{status}")

                lines.append("")  # blank line between rooms

            # Remove trailing blank line.
            if lines and lines[-1] == "":
                lines.pop()

            lines.append(f"|w{'-' * width}|n")
            lines.append(f" {total} character{'s' if total != 1 else ''} online")

        lines.append(f"|w+{'=' * (width - 2)}+|n")
        return "\n".join(lines)

    @staticmethod
    def _format_count(viewer):
        """Build the +where/count compact display."""
        width = 68
        is_viewer_staff = is_staff(viewer)
        characters = get_connected_characters()

        rooms = defaultdict(int)
        total = 0
        for char in characters:
            if not char.location:
                continue
            room = char.location
            room_type = getattr(room, "room_type", "ic") or "ic"
            if room_type == "staff" and not is_viewer_staff:
                continue
            rooms[room] += 1
            total += 1

        sorted_rooms = sorted(rooms.items(), key=lambda r: (-r[1], r[0].key))

        # Screen-reader mode: plain list instead of bordered table.
        if uses_screenreader(viewer):
            room_count = len(sorted_rooms)
            lines = [
                f"Room Population: {total} character{'s' if total != 1 else ''} online"
                f" in {room_count} room{'s' if room_count != 1 else ''}"
            ]
            for room, count in sorted_rooms:
                lines.append(f"  {room.key}: {count}")
            return "\n".join(lines)

        lines = []
        header = " Room Population "
        lines.append(f"|w+{'=' * (width - 2)}+|n")
        pad = width - 2 - len(header)
        left = pad // 2
        right = pad - left
        lines.append(f"|w+{'=' * left}{header}{'=' * right}+|n")

        if not sorted_rooms:
            lines.append(" No characters online.")
        else:
            for room, count in sorted_rooms:
                lines.append(f" {room.key:<40} {count}")
            room_count = len(sorted_rooms)
            lines.append(f"|w{'-' * width}|n")
            lines.append(
                f" {total} character{'s' if total != 1 else ''} online "
                f"in {room_count} room{'s' if room_count != 1 else ''}"
            )

        lines.append(f"|w+{'=' * (width - 2)}+|n")
        return "\n".join(lines)


class CmdHangouts(MuxCommand):
    """
    Browse the hangout directory.

    Usage:
        +hangouts               - Show populated hangout rooms
        +hangouts/all           - Show all hangouts, including empty ones
        +hangouts/<type>        - Filter by hangout type (e.g. /bar, /arena)
        +hangouts/types         - List valid hangout types

    Shows designated hangout rooms ranked by population, with activity
    freshness and room mood. Use a room-config command (see README) to
    designate a room as a hangout. For individual character listings,
    see |w+where|n.
    """

    key = "+hangouts"
    aliases = []  # noqa: RUF012
    help_category = "Social"
    locks = "cmd:all()"

    def func(self):
        caller = self.caller

        if not self.switches:
            caller.msg(self._format(caller))
            return

        switch = self.switches[0].lower()

        if switch == "all":
            caller.msg(self._format(caller, include_empty=True))
        elif switch == "types":
            valid = ", ".join(HANGOUT_TYPES)
            caller.msg(f"|wValid hangout types:|n {valid}")
        elif switch in HANGOUT_TYPES:
            caller.msg(self._format(caller, filter_type=switch))
        else:
            valid = ", ".join(HANGOUT_TYPES)
            caller.msg(
                f"|rUnknown switch:|n /{switch}. "
                f"Valid filters: {valid}, all, types. "
                "See |whelp +hangouts|n for usage."
            )

    @staticmethod
    def _format(viewer, filter_type=None, include_empty=False):
        """Build the +hangouts display string.

        Args:
            viewer: The character viewing +hangouts.
            filter_type: None (all hangout types) or a specific HANGOUT_TYPES value.
            include_empty: If True, also show unpopulated hangout rooms.
        """
        width = 68
        is_viewer_staff = is_staff(viewer)
        characters = get_connected_characters()

        # Group characters by room, filtering to hangout rooms only.
        populated = defaultdict(list)
        for char in characters:
            if not char.location:
                continue
            room = char.location
            room_type = getattr(room, "room_type", "ic") or "ic"

            # Staff rooms hidden from non-staff.
            if room_type == "staff" and not is_viewer_staff:
                continue

            # Only include designated hangout rooms.
            hangout = getattr(room, "hangout_type", None)
            if not hangout:
                continue

            # Apply hangout type filter if requested.
            if filter_type and hangout != filter_type:
                continue

            populated[room].append(char)

        # Sort populated rooms by population descending, then name ascending.
        sorted_populated = sorted(populated.items(), key=lambda r: (-len(r[1]), r[0].key))

        # For /all: find empty hangout rooms not already in the populated set.
        # ObjectDB.objects.get_by_attribute() is typeclass-agnostic — it
        # matches any object with a "hangout_type" Attribute set, regardless
        # of which Room subclass the game defines (unlike a typeclass path
        # filter, which would only match one exact class).
        empty_rooms = []
        if include_empty:
            all_hangout_rooms = ObjectDB.objects.get_by_attribute(key="hangout_type")
            for room in all_hangout_rooms:
                if room in populated:
                    continue
                room_type = getattr(room, "room_type", "ic") or "ic"
                if room_type == "staff" and not is_viewer_staff:
                    continue
                hangout = getattr(room, "hangout_type", None)
                if not hangout:
                    continue
                if filter_type and hangout != filter_type:
                    continue
                empty_rooms.append(room)
            empty_rooms.sort(key=lambda r: r.key)

        # Screen-reader mode: plain list instead of bordered table.
        if uses_screenreader(viewer):
            total_chars = sum(len(c) for _, c in sorted_populated)
            room_count = len(sorted_populated) + len(empty_rooms)
            lines = [
                f"Hangouts: {total_chars} character{'s' if total_chars != 1 else ''}"
                f" across {room_count} hangout{'s' if room_count != 1 else ''}"
            ]
            if not sorted_populated and not empty_rooms:
                lines = [f"No {''.join([filter_type + ' ']) if filter_type else ''}hangouts found."]
            else:
                for room, chars in sorted_populated:
                    room_type = getattr(room, "room_type", "ic") or "ic"
                    hangout = getattr(room, "hangout_type", "")
                    hangout_label = hangout.capitalize() if hangout else ""
                    count = len(chars)
                    pose_times = [c.last_pose_time for c in chars if c.last_pose_time]
                    activity = (
                        f"active {format_pose_time(max(pose_times))} ago"
                        if pose_times
                        else "active: --"
                    )
                    lines.append(
                        f"  {room.key} [{hangout_label}] ({room_type.upper()})"
                        f" — {count} character{'s' if count != 1 else ''}, {activity}"
                    )
                    mood = getattr(room, "room_mood", "") or ""
                    if mood:
                        lines.append(f"    Mood: {mood}")
                    char_names = ", ".join(c.get_display_name(viewer) for c in chars)
                    if char_names:
                        lines.append(f"    Characters: {char_names}")
                for room in empty_rooms:
                    room_type = getattr(room, "room_type", "ic") or "ic"
                    hangout = getattr(room, "hangout_type", "")
                    hangout_label = hangout.capitalize() if hangout else ""
                    lines.append(
                        f"  {room.key} [{hangout_label}] ({room_type.upper()}) — Empty ({room.dbref})"
                    )
            return "\n".join(lines)

        lines = []
        header = " Hangouts "
        lines.append(f"|w+{'=' * (width - 2)}+|n")
        pad = width - 2 - len(header)
        left = pad // 2
        right = pad - left
        lines.append(f"|w+{'=' * left}{header}{'=' * right}+|n")

        if not sorted_populated and not empty_rooms:
            if filter_type:
                lines.append(f" No {filter_type} hangouts found.")
            else:
                lines.append(" No hangouts found.")
        else:
            total_chars = 0

            # Populated hangout rooms.
            for room, chars in sorted_populated:
                total_chars += len(chars)
                CmdHangouts._append_room(lines, room, chars, width)

            # Empty hangout rooms (only with /all).
            for room in empty_rooms:
                CmdHangouts._append_room(lines, room, [], width)

            # Remove trailing blank line.
            if lines and lines[-1] == "":
                lines.pop()

            room_count = len(sorted_populated) + len(empty_rooms)
            lines.append(f"|w{'-' * width}|n")
            lines.append(
                f" {total_chars} character{'s' if total_chars != 1 else ''} "
                f"across {room_count} hangout{'s' if room_count != 1 else ''}"
            )

        lines.append(f"|w+{'=' * (width - 2)}+|n")
        return "\n".join(lines)

    @staticmethod
    def _append_room(lines, room, chars, width):
        """Append formatted lines for a single hangout room.

        Args:
            lines: List to append to.
            room: The Room object.
            chars: List of Character objects in the room (empty list if unpopulated).
            width: Display width.
        """
        room_type = getattr(room, "room_type", "ic") or "ic"
        type_label = room_type.upper()
        hangout = getattr(room, "hangout_type", "")
        hangout_label = hangout.capitalize() if hangout else ""
        count = len(chars)

        if count > 0:
            plural = "character" if count == 1 else "characters"

            # Most recent pose in the room.
            pose_times = [c.last_pose_time for c in chars if c.last_pose_time]
            if pose_times:
                most_recent = max(pose_times)
                activity = f"active {format_pose_time(most_recent)} ago"
            else:
                activity = "active: --"

            lines.append(
                f" |w{room.key}|n [{hangout_label}] ({type_label}) — {count} {plural}, {activity}"
            )
        else:
            # Empty room — show dbref for easy @tel.
            dbref = room.dbref
            lines.append(f" |w{room.key}|n [{hangout_label}] ({type_label}) — Empty ({dbref})")

        # Show room mood if set.
        mood = getattr(room, "room_mood", "") or ""
        if mood:
            max_mood_len = width - 12
            if len(mood) > max_mood_len:
                mood = mood[: max_mood_len - 3] + "..."
            lines.append(f"   |w[Mood]|n {mood}")

        lines.append("")  # blank separator
