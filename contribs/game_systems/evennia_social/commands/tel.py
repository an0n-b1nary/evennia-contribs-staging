# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Enhanced teleportation — @tel command.

Wraps Evennia's built-in @tel with partial/fuzzy room-name matching and
player-vs-staff permission tiers. Room access is controlled by per-room
``allow_teleport`` ("public"/"private"/"secret") and the game-wide
``TELEPORT_MODE`` setting ("visited"/"open").

The source project's staff module also carried a moderation command
(+softban) next to @tel. That command is unrelated to teleportation and is
not part of this contrib — see MIGRATION_NOTES.md.
"""

from evennia.commands.default.muxcommand import MuxCommand

from evennia_social.search import find_room, find_room_for_player


class CmdTel(MuxCommand):
    """
    Teleport to a room by name.

    Usage:
        @tel <room name>            - Teleport to a room (partial/fuzzy match)
        @tel <object>=<room name>   - Move an object to a room (staff only)
        @tel/quiet <room name>      - Teleport silently

    Enhanced wrapper around Evennia's @tel with fuzzy room name matching.

    Players can teleport to public rooms they have visited or control.
    Private rooms are restricted to the room's owner. Secret rooms are
    hidden from search suggestions entirely. Staff (Builder+) have
    unrestricted access to all rooms.
    """

    key = "@tel"
    aliases = ["@teleport"]  # noqa: RUF012
    help_category = "Travel"
    switch_options = ("quiet",)
    rhs_split = ("=",)
    locks = "cmd:all()"

    def _is_staff(self):
        """Check if the caller has Builder or higher permission."""
        return self.caller.locks.check_lockstring(self.caller, "perm(Builder)")

    def _format_suggestions(self, suggestions):
        """Format a list of room suggestions with MXP links."""
        lines = ["|wMultiple matches:|n"]
        for i, room in enumerate(suggestions, 1):
            name = room.get_display_name(self.caller)
            lines.append(f"  {i}. |lc@tel {room.key}|lt{name}|le (#{room.id})")
        return "\n".join(lines)

    def _do_teleport(self, obj, destination):
        """Execute the teleport move.

        Args:
            obj: The object to move.
            destination: The target room.

        Returns:
            bool: True if the move succeeded.
        """
        quiet = "quiet" in self.switches
        success = obj.move_to(
            destination,
            quiet=quiet,
            emit_to_obj=self.caller,
            move_type="teleport",
        )
        return success

    def func(self):
        """Execute command."""
        caller = self.caller

        if not self.args:
            caller.msg("Usage: @tel <room name>  or  @tel <object>=<room name>")
            return

        staff = self._is_staff()

        # Two-argument form: @tel <obj> = <destination>
        if self.rhs:
            if not staff:
                caller.msg("Only staff can teleport other objects.")
                return
            obj = caller.search(self.lhs, global_search=True)
            if not obj:
                return
            room, suggestions = find_room(caller, self.rhs)
            if room:
                if self._do_teleport(obj, room):
                    caller.msg(
                        f"Teleported {obj.get_display_name(caller)} to "
                        f"{room.get_display_name(caller)}."
                    )
                else:
                    caller.msg("Teleportation failed.")
            elif suggestions:
                caller.msg(self._format_suggestions(suggestions))
            else:
                caller.msg("No matching room found.")
            return

        # Single-argument form: @tel <destination>
        query = self.lhs

        # Optional combat-lock seam: games with a combat system can set
        # combat_state = "in_combat" to block teleportation; games without
        # one never trip this (defaults to "idle"). Not owned by this
        # contrib — same defensive-getattr pattern as room_type.
        if getattr(caller, "combat_state", "idle") == "in_combat":
            caller.msg("You can't teleport while in combat!")
            return

        if staff:
            room, suggestions = find_room(caller, query)
        else:
            room, suggestions = find_room_for_player(caller, query, caller)

        if room:
            if room == caller.location:
                caller.msg("You are already there.")
                return
            if self._do_teleport(caller, room):
                caller.msg(f"Teleported to {room.get_display_name(caller)}.")
            else:
                caller.msg("Teleportation failed.")
        elif suggestions:
            caller.msg(self._format_suggestions(suggestions))
        else:
            if not staff:
                caller.msg("No matching room found among your accessible rooms.")
            else:
                caller.msg("No matching room found.")
