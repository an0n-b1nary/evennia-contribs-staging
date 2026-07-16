# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Room configuration — +roomconfig command.

The in-game way to designate a room as a hangout, which is what populates
the ``+hangouts`` directory (see commands/discovery.py). Without this
command ``hangout_type`` could only be set from Python, so it ships here
even though the source project filed it with its building tools.

Only the hangout slice of the source's room-config command came along; its
room-creation/grid-building siblings are a separate concern and stayed
behind (see MIGRATION_NOTES.md).
"""

from evennia.commands.default.muxcommand import MuxCommand

from evennia_social.social import is_staff
from evennia_social.typeclasses import HANGOUT_TYPES


def _can_configure_room(character, room):
    """Check if character can configure the given room.

    Returns True for room owners (control access) and Builder+ staff.
    """
    return room.access(character, "control") or is_staff(character)


class CmdRoomConfig(MuxCommand):
    """
    View or modify room configuration.

    Usage:
        +roomconfig                         - Show current room settings
        +roomconfig/hangout <type>          - Designate as a hangout
        +roomconfig/hangout/clear           - Remove hangout designation

    Valid hangout types: bar, eatery, arena, market, park, temple,
    library, plaza, theater, docks.

    Permissions: room owner or Builder+ staff.
    See |w+hangouts|n to browse the hangout directory.
    """

    key = "+roomconfig"
    aliases = ["+rconfig"]  # noqa: RUF012
    help_category = "Building"
    locks = "cmd:all()"

    def func(self):
        caller = self.caller
        room = caller.location

        if not room:
            caller.msg("|rYou must be in a room to use this command.|n")
            return

        if not _can_configure_room(caller, room):
            caller.msg("|rYou don't have permission to configure this room.|n")
            return

        # No switches: show current configuration.
        if not self.switches:
            self._show_config(room)
            return

        switches = [s.lower() for s in self.switches]

        if switches == ["hangout"]:
            self._set_hangout(room)
        elif switches == ["hangout", "clear"] or switches == ["clear", "hangout"]:
            self._clear_hangout(room)
        else:
            caller.msg(
                f"|rUnknown switch:|n /{'/'.join(self.switches)}. "
                "See |whelp +roomconfig|n for usage."
            )

    def _show_config(self, room):
        """Display current room configuration."""
        caller = self.caller
        width = 68
        lines = []
        lines.append(f"|w+{'=' * (width - 2)}+|n")
        header = " Room Configuration "
        pad = width - 2 - len(header)
        left = pad // 2
        right = pad - left
        lines.append(f"|w+{'=' * left}{header}{'=' * right}+|n")

        lines.append(f" |wRoom:|n {room.key}")
        # room_type / room_mood are shared, contrib-agnostic Room attributes
        # owned by no contrib — read defensively. See README.
        room_type = getattr(room, "room_type", "ic") or "ic"
        lines.append(f" |wType:|n {room_type.upper()}")

        hangout = getattr(room, "hangout_type", None)
        if hangout:
            lines.append(f" |wHangout:|n {hangout.capitalize()}")
        else:
            lines.append(" |wHangout:|n None")

        mood = getattr(room, "room_mood", "") or ""
        if mood:
            lines.append(f" |wMood:|n {mood}")

        lines.append(f"|w+{'=' * (width - 2)}+|n")
        caller.msg("\n".join(lines))

    def _set_hangout(self, room):
        """Set the room's hangout type."""
        caller = self.caller
        hangout_type = self.args.strip().lower()

        if not hangout_type:
            valid = ", ".join(HANGOUT_TYPES)
            caller.msg(f"|rSpecify a hangout type.|n Valid types: {valid}")
            return

        if hangout_type not in HANGOUT_TYPES:
            valid = ", ".join(HANGOUT_TYPES)
            caller.msg(f"|rInvalid hangout type:|n {hangout_type}. Valid types: {valid}")
            return

        room.hangout_type = hangout_type
        caller.msg(f"|wHangout type set to|n {hangout_type.capitalize()} |wfor|n {room.key}|w.|n")

    def _clear_hangout(self, room):
        """Remove the room's hangout designation."""
        caller = self.caller
        if not room.hangout_type:
            caller.msg(f"{room.key} is not currently a hangout.")
            return
        old_type = room.hangout_type
        room.hangout_type = None
        caller.msg(
            f"|wRemoved|n {old_type.capitalize()} |whangout designation from|n {room.key}|w.|n"
        )
