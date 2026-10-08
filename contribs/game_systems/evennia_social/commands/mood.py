# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Room mood — the +mood command.

Sets the line of atmosphere ``SocialRoomMixin`` shows under the room's
description. Permissions are decided by ``evennia_social.mood.can_set_mood``.
"""

from evennia.commands.default.muxcommand import MuxCommand

from evennia_social.mood import MOOD_MAX_LENGTH, can_set_mood, clear_mood, set_mood


class CmdMood(MuxCommand):
    """
    View or set the mood of the room you're in.

    Usage:
        +mood                - Show the current mood and who set it
        +mood <text>         - Set the mood
        +mood/clear          - Remove the mood

    The mood appears under the room's description for everyone who looks,
    and changing it is announced to the room.

    Who can set it: the room's owner and Builder+ staff. While a scene is
    running here, any active participant can too if the scene is public; in
    a private scene, only its host.
    """

    key = "+mood"
    aliases = []  # noqa: RUF012
    help_category = "Social"
    locks = "cmd:all()"

    def func(self):
        caller = self.caller
        room = caller.location
        if not room:
            caller.msg("|rYou must be in a room to use this command.|n")
            return

        switches = [s.lower() for s in self.switches]
        if switches and switches != ["clear"]:
            caller.msg(f"|rUnknown switch:|n /{'/'.join(self.switches)}. See |whelp +mood|n.")
            return

        if not switches and not self.args.strip():
            self._show(room)
            return

        if not can_set_mood(caller, room):
            caller.msg("|rYou can't set the mood here.|n See |whelp +mood|n for who can.")
            return

        if switches == ["clear"]:
            if not clear_mood(room):
                caller.msg("This room has no mood to clear.")
                return
            caller.msg("|wMood cleared.|n")
            room.msg_contents(f"{caller.key} clears the mood.", exclude=[caller])
            return

        try:
            text = set_mood(room, self.args, caller)
        except ValueError as exc:
            caller.msg(f"|r{exc}|n")
            return
        caller.msg(f"|wMood set:|n {text}")
        room.msg_contents(f"{caller.key} sets the mood: {text}", exclude=[caller])

    def _show(self, room):
        mood = getattr(room, "room_mood", "") or ""
        if not mood:
            self.caller.msg(
                f"No mood is set here. Use |w+mood <text>|n (up to {MOOD_MAX_LENGTH} "
                "characters) if you're allowed to set one."
            )
            return
        setter = getattr(room, "room_mood_setter", None)
        byline = f" |x(set by {setter})|n" if setter else ""
        self.caller.msg(f"|w[Mood]|n {mood}{byline}")
