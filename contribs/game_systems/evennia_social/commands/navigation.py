# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Navigation shortcuts — +ooc and +home instant teleport commands.

Provides quick movement to well-known destinations without acceptance
handshakes. Bypasses allow_teleport restrictions since destinations are
either public hubs or player-owned rooms.
"""

from django.conf import settings
from evennia.commands.default.muxcommand import MuxCommand
from evennia.objects.models import ObjectDB
from evennia.utils.search import search_object

from evennia_social.social import is_staff


def _resolve_ooc_room():
    """Look up the OOC Nexus room from settings.

    Returns:
        Room or None: The OOC room object, or None if not configured/found.
    """
    dbref = getattr(settings, "OOC_ROOM_DBREF", None)
    if not dbref:
        return None
    matches = search_object(dbref)
    return matches[0] if matches else None


class CmdOocTeleport(MuxCommand):
    """
    Teleport to the OOC Nexus.

    Usage:
        +ooc

    Instantly teleports you to the OOC Nexus room, a public hub for
    out-of-character socializing. No acceptance required.

    Requires ``settings.OOC_ROOM_DBREF`` to be set (see README).
    """

    key = "+ooc"
    help_category = "Social"
    locks = "cmd:all()"

    def func(self):
        """Teleport to the OOC room."""
        destination = _resolve_ooc_room()
        if not destination:
            self.caller.msg("The OOC room is not configured. Contact staff.")
            return
        if self.caller.location == destination:
            self.caller.msg("You are already in the OOC room.")
            return
        self.caller.move_to(destination, quiet=False)
        self.caller.msg("You teleport to the OOC Nexus.")


class CmdHome(MuxCommand):
    """
    Teleport to your home room.

    Usage:
        +home              - Teleport to your home (or OOC Nexus if none set)
        +home/set          - Set current room as your home (requires control)
        +home/clear        - Clear your home (reverts to OOC Nexus fallback)

    Your home room is a personal shortcut destination. If you haven't
    set one, +home takes you to the OOC Nexus instead.
    """

    key = "+home"
    help_category = "Social"
    locks = "cmd:all()"
    switch_options = ("set", "clear")

    def func(self):
        """Dispatch to the appropriate sub-method."""
        if not self.switches:
            self._do_home()
        elif "set" in self.switches:
            self._do_set()
        elif "clear" in self.switches:
            self._do_clear()
        else:
            self.caller.msg(
                f"Unknown switch '{''.join(self.switches)}'. Use +home, +home/set, or +home/clear."
            )

    def _do_home(self):
        """Teleport to home room or OOC fallback."""
        caller = self.caller
        destination = None
        label = "home"

        # Try personal home room first.
        if caller.home_room is not None:
            try:
                destination = ObjectDB.objects.get(id=caller.home_room)
            except ObjectDB.DoesNotExist:
                caller.home_room = None
                caller.msg("Your home room no longer exists. Falling back to OOC Nexus.")

        # Fall back to OOC Nexus.
        if destination is None:
            destination = _resolve_ooc_room()
            label = "the OOC Nexus"
            if destination is None:
                caller.msg("You have no home set and the OOC room is not configured.")
                return

        # Staff room guard — room may have been converted after being set as home.
        if getattr(destination, "room_type", "ic") == "staff" and not is_staff(caller):
            caller.msg("Your home is in a staff-only area you can no longer access.")
            return

        if caller.location == destination:
            if label == "home":
                caller.msg("You are already home.")
            else:
                caller.msg("You are already in the OOC room.")
            return

        caller.move_to(destination, quiet=False)
        caller.msg(f"You teleport to {label}.")

    def _do_set(self):
        """Set current room as home."""
        caller = self.caller
        room = caller.location
        if not room:
            caller.msg("You have no location.")
            return

        # Require room control or staff.
        if not room.access(caller, "control") and not is_staff(caller):
            caller.msg("You can only set your home in a room you control.")
            return

        # Staff room guard for non-staff.
        if getattr(room, "room_type", "ic") == "staff" and not is_staff(caller):
            caller.msg("Only staff can set a staff room as home.")
            return

        caller.home_room = room.id
        caller.msg(f"Home set to |w{room.get_display_name(caller)}|n.")

    def _do_clear(self):
        """Clear the home room."""
        caller = self.caller
        if caller.home_room is None:
            caller.msg("You have no custom home set.")
            return
        caller.home_room = None
        caller.msg("Home cleared. +home will now go to the OOC Nexus.")
