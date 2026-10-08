"""Sandbox glue — the two dotted-path settings hooks that stay game-local,
plus the single ordered signal listener for evennia_posing's `pose_recorded`.

Every other cross-contrib wiring point in this game (XP collectors and
projection, antigaming sweeps and their staff-ticket reporter, scene display,
lore's session context) is a function shipped inside a contrib itself — see
server/conf/settings.py. Only these two are game-local, because they choose
between this sandbox's own content and an optional partner:

- RP_RULES_SUBJECT_ADAPTER / RP_RULES_VOCABULARY — select installed chargen
  sheets and catalog tags, with stat-block and ruleset fallbacks

This module also holds `on_pose_recorded`, the single ordered listener for
`evennia_posing.pose_recorded` (see that contrib's README §"Wire the
pose_recorded signal"). Unlike the hooks above, it isn't a dotted-path
setting — it's connected once in `world/sandbox/apps.py`'s `SandboxConfig.
ready()` with a `dispatch_uid`. It fans each recorded pose/emit/say out to
scenes, tracker and chargen in that order. Each consumer is optional.
"""

import logging

from django.apps import apps

_logger = logging.getLogger(__name__)


def rp_subject_adapter(obj):
    """Use a real chargen sheet, or the object's sandbox stat block.

    `rp_stat_block` in Attribute category `sandbox` holds {stat_key: rating}.
    No RP typeclass mixin is required, and a missing chargen app never imports it.
    """
    if apps.is_installed("evennia_rp_chargen"):
        from evennia_rp_chargen.subject import subject_adapter

        subject = subject_adapter(obj)
        if subject is not None:
            return subject
    attributes = getattr(obj, "attributes", None)
    ratings = attributes.get("rp_stat_block", category="sandbox") if attributes else None
    if ratings:
        from evennia_rp_rules.subjects import DictStatSource

        return DictStatSource(ratings, name=obj.key)
    return None


def rp_vocabulary():
    """Runtime catalog tags with chargen; the ruleset vocabulary without it."""
    if apps.is_installed("evennia_rp_chargen"):
        from evennia_rp_chargen.vocabulary import DBVocabulary

        return DBVocabulary()
    from evennia_rp_rules.vocabulary import RulesetVocabulary

    return RulesetVocabulary()


def on_pose_recorded(sender, character, pose_text, pose_type, location, **kwargs):
    """Single ordered listener for evennia_posing's pose_recorded signal.

    Connected once in world/sandbox/apps.py (SandboxConfig.ready) with a
    dispatch_uid. Django does not guarantee delivery order across multiple
    independent receivers, so the downstream consumers are called from
    this one receiver, in this order:

    1. evennia_scenes.capture.capture_to_scene — scene state first, so
       rptracker's session bookkeeping runs after any scene updates.
       log_type is passed through from pose_type; "ooc" (fired by
       evennia_social's CmdOoc) maps onto LogEntry.LogType.OOC.
    2. evennia_rptracker.record_rp_activity — skipped when location is
       None (the signal allows a None location; rptracker needs a room).

    3. evennia_rp_chargen.locks.note_ic_action — IC actions only. This runs
       after tracking, because recording a new pose can expire an old session
       and release its lock; the new action must then lock the new build again.

    Each call is gated on the app registry and wrapped so one failing consumer
    cannot break the others or the caller — record_pose() fires this synchronously from the
    pose/say code path, so an escaping exception would surface to the
    posing player. Failures are logged with traceback.
    """
    if apps.is_installed("evennia_scenes"):
        try:
            from evennia_scenes.capture import capture_to_scene

            capture_to_scene(character, pose_text, log_type=pose_type)
        except Exception:
            _logger.exception("on_pose_recorded: capture_to_scene failed")

    if pose_type == "ooc":
        return
    if location is not None and apps.is_installed("evennia_rptracker"):
        try:
            from evennia_rptracker import record_rp_activity

            record_rp_activity(character, location)
        except Exception:
            _logger.exception("on_pose_recorded: record_rp_activity failed")

    if apps.is_installed("evennia_rp_chargen"):
        try:
            from evennia_rp_chargen.locks import note_ic_action

            note_ic_action(character)
        except Exception:
            _logger.exception("on_pose_recorded: note_ic_action failed")
