# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
OOC room chat — out-of-character messaging to the current room.

Fires evennia_posing's ``pose_recorded`` signal with ``pose_type="ooc"`` so
a game's scene-logging glue can capture OOC chat as a distinct log type
(the same seam +pose/+emit/+say use — see evennia_posing README). This does
**not** call ``record_pose()``, so OOC chat does not touch pose order
(+pot) or the pose timer — it only reaches downstream consumers wired to
the signal.
"""

from evennia.commands.default.muxcommand import MuxCommand

from evennia_posing.signals import pose_recorded


class CmdOoc(MuxCommand):
    """
    Send an out-of-character message to the room.

    Usage:
        ooc <message>

    Broadcasts an OOC message to everyone in your current room, visually
    tagged to distinguish it from IC poses. Useful for quick coordination,
    scene logistics, or banter that shouldn't mix with IC content.

    OOC messages do not affect pose order (+pot) or pose tracking.
    """

    key = "ooc"
    help_category = "Social"
    locks = "cmd:all()"

    def func(self):
        """Broadcast an OOC message to the room."""
        if not self.args:
            self.caller.msg("What do you want to say OOC?")
            return
        if not self.caller.location:
            self.caller.msg("You have no location to send OOC chat to.")
            return

        message = self.args.strip()
        # mapping: {name} resolves per-viewer via caller.get_display_name(looker=receiver).
        # {message} is a plain string, so str() passthrough.
        self.caller.location.msg_contents(
            text=(
                "{name} |w[OOC]|n: {message}",
                {"type": "ooc"},
            ),
            from_obj=self.caller,
            mapping={"name": self.caller, "message": message},
        )

        # Let downstream consumers (scene logging, etc.) react without this
        # contrib importing them directly. See evennia_posing's README
        # "Integration recipe" step 4 for the single-ordered-listener
        # wiring pattern this signal expects.
        pose_recorded.send(
            sender=self.caller.__class__,
            character=self.caller,
            pose_text=message,
            pose_type="ooc",
            location=self.caller.location,
        )
