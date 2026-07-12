"""
Characters

Characters are (by default) Objects setup to be puppeted by Accounts.
They are what you "see" in game. The Character class in this module
is setup to be the "default" character type created by the default
creation commands.

Contrib sandbox extensions:
- `last_pose_time` — required seam for evennia_rptracker (see its README
  §"Character and room seams"). Set on every pose/say, cleared on disconnect.
- `at_say` override — feeds evennia_rptracker + evennia_scenes on every say,
  per each contrib's "Integration recipe" / "Wire capture hooks" section.
  (Poses go through commands/pose_seam.py:CmdSandboxPose instead, since
  Evennia's stock pose command has no character-level hook to override.)
- `at_post_unpuppet` override — ends the RPTracker session on disconnect.
"""

import time

from evennia.objects.objects import DefaultCharacter
from evennia.typeclasses.attributes import AttributeProperty

from .objects import ObjectParent


class Character(ObjectParent, DefaultCharacter):
    """
    The Character just re-implements some of the Object's methods and hooks
    to represent a Character entity in-game.

    See mygame/typeclasses/objects.py for a list of
    properties and methods available on all Object child classes like this.

    """

    # Required by evennia_rptracker: float unix timestamp of the character's
    # last pose/say, used to determine who is "actively posing". Set here
    # (not left to autocreate) and cleared to None on disconnect.
    last_pose_time = AttributeProperty(default=None, autocreate=False)

    def at_say(
        self,
        message,
        msg_self=None,
        msg_location=None,
        receivers=None,
        msg_receivers=None,
        **kwargs,
    ):
        """Feed the rptracker/scenes seams for room-visible says.

        Whispers (explicit receivers) are excluded — they aren't RP activity
        in a shared IC room, and evennia_scenes' capture_to_scene only makes
        sense for content visible to the room.
        """
        super().at_say(
            message,
            msg_self=msg_self,
            msg_location=msg_location,
            receivers=receivers,
            msg_receivers=msg_receivers,
            **kwargs,
        )
        if receivers:
            return

        self.last_pose_time = time.time()

        if self.location:
            from evennia_rptracker import record_rp_activity

            record_rp_activity(self, self.location)

        from evennia_scenes.capture import capture_to_scene

        capture_to_scene(self, message, log_type="say")

    def at_post_unpuppet(self, account=None, session=None, **kwargs):
        """Clear the pose timer and end any active RPTracker session."""
        super().at_post_unpuppet(account=account, session=session, **kwargs)
        self.last_pose_time = None

        from evennia_rptracker import end_session

        end_session(self.id, manual=False)
