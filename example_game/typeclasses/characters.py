"""
Characters

Characters are (by default) Objects setup to be puppeted by Accounts.
They are what you "see" in game. The Character class in this module
is setup to be the "default" character type created by the default
creation commands.

Contrib sandbox extensions (mixin-based, no hand-rolled hooks):
- `SocialCharacterMixin` (evennia_social) — profile/page/ignore/summon/home
  state, plus the ignore-filtering half of the cooperative `msg()` chain.
- `PosingCharacterMixin` (evennia_posing) — `last_pose_time`/`last_pose_text`/
  `pose_status` state, pose-timer resets in `at_post_move`/`at_post_puppet`/
  `at_post_unpuppet`, the pose-header/highlight half of `msg()`, and
  `record_pose()`, which fires the `pose_recorded` signal consumed by the
  single ordered listener in `world/sandbox/glue.py` (connected in
  `world/sandbox/apps.py`). `last_pose_time` is the same seam
  evennia_rptracker's README documents as required from the game — this
  mixin satisfies it out of the box.

Mixin order matters: `SocialCharacterMixin` must come *before*
`PosingCharacterMixin` so ignore-filtering runs before header/highlight
processing in `msg()` — see both contribs' READMEs §"Integration recipe" /
"Layering with evennia-social".

- `at_post_unpuppet` override — kept here because it's game glue, not
  contrib behavior: `super()` (via `PosingCharacterMixin`) clears the pose
  timer; this override additionally ends any active RPTracker session, per
  evennia_rptracker's README §"Wire the disconnect hook".
"""

from evennia.objects.objects import DefaultCharacter

from evennia_posing import PosingCharacterMixin
from evennia_social import SocialCharacterMixin

from .objects import ObjectParent


class Character(SocialCharacterMixin, PosingCharacterMixin, ObjectParent, DefaultCharacter):
    """
    The Character just re-implements some of the Object's methods and hooks
    to represent a Character entity in-game.

    See mygame/typeclasses/objects.py for a list of
    properties and methods available on all Object child classes like this.

    """

    def at_post_unpuppet(self, account=None, session=None, **kwargs):
        """Clear the pose timer (PosingCharacterMixin, via super) and end
        any active RPTracker session — documented game glue per
        evennia_rptracker's README §"Wire the disconnect hook".
        """
        super().at_post_unpuppet(account=account, session=session, **kwargs)

        from evennia_rptracker import end_session

        end_session(self.id, manual=False)
