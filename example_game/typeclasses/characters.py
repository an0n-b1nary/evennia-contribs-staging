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

- `at_post_puppet` override — calls `evennia_xp.summary.notify_xp_summary`
  rather than mixing in `XPSummaryCharacterMixin`, because evennia_xp is an
  optional RP partner here (`ci_run_rp_sandbox_tests.py --absent evennia_xp`)
  and a mixin would have to be imported unconditionally.

- `get_display_desc` / `filter_visible` overrides — call evennia_rp_equipment's
  display helpers (worn lines in the description, worn items out of "You see")
  rather than mixing in `EquipmentCharacterMixin`, for the same reason as the
  XP summary: equipment requires chargen, an optional RP partner here, so it is
  absent whenever chargen is (`ci_run_rp_sandbox_tests.py --absent`).

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

    def at_post_puppet(self, **kwargs):
        """Record character activity independently of account web logins, and
        show the first-login XP summary after a weekly batch.
        """
        from django.apps import apps
        from django.utils import timezone

        super().at_post_puppet(**kwargs)
        self.attributes.add("sandbox_last_seen", timezone.now())

        if apps.is_installed("evennia_economy"):
            from evennia_economy.batch import ensure_stipends
            from evennia_economy.stalls import note_login
            from evennia_economy.summary import notify_economy_summary

            from evennia_links.runtime import get

            if not get("RP_ECONOMY_FROZEN"):
                ensure_stipends(self)
            notify_economy_summary(self)
            note_login(self)

        if apps.is_installed("evennia_rp_resources"):
            from evennia_rp_resources.summary import notify_resource_summary

            notify_resource_summary(self)

        if apps.is_installed("evennia_xp"):
            from evennia_xp.summary import notify_xp_summary

            notify_xp_summary(self)

    def get_display_desc(self, looker, **kwargs):
        """The description, followed by worn lines when evennia_rp_equipment is installed."""
        from django.apps import apps

        desc = super().get_display_desc(looker, **kwargs)
        if apps.is_installed("evennia_rp_equipment"):
            from evennia_rp_equipment.display import with_worn

            desc = with_worn(self, looker, desc)
        return desc

    def filter_visible(self, obj_list, looker, **kwargs):
        """Leave worn items out of "You see"; their worn lines describe them."""
        from django.apps import apps

        visible = super().filter_visible(obj_list, looker, **kwargs)
        if apps.is_installed("evennia_rp_equipment"):
            from evennia_rp_equipment.display import hide_worn

            visible = hide_worn(visible)
        return visible

    def at_post_unpuppet(self, account=None, session=None, **kwargs):
        """Clear the pose timer (PosingCharacterMixin, via super) and end
        any active RPTracker session — documented game glue per
        evennia_rptracker's README §"Wire the disconnect hook".
        """
        super().at_post_unpuppet(account=account, session=session, **kwargs)

        from django.apps import apps

        if apps.is_installed("evennia_rptracker"):
            from evennia_rptracker import end_character_channel_sessions, end_session

            end_session(self.id, manual=False)
            end_character_channel_sessions(self.id)

        from django.utils import timezone

        self.attributes.add("sandbox_last_seen", timezone.now())
