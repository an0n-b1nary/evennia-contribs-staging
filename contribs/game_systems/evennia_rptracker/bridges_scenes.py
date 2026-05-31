# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Scene bridge listener for evennia_rptracker.

This module is imported by EvenniaRptrackerConfig.ready() only when the
configured scenes app (RPTRACKER_SCENES_APP_LABEL, default "scenes") is
in INSTALLED_APPS. Importing it registers the rp_activity_recorded listener
that creates RPSessionSceneLink rows.

The bridge MODEL itself lives in evennia_rptracker.models (always shipped);
this module only adds the behavioral listener.
"""

import logging

from django.dispatch import receiver

from evennia_rptracker.signals import rp_activity_recorded

logger = logging.getLogger("evennia")


@receiver(rp_activity_recorded)
def on_rp_activity_recorded(sender, character, session_id, room, **kwargs):
    """Create an RPSessionSceneLink when a session overlaps with an active scene.

    Fires on every qualifying pose in an active RPSession. Does nothing if
    the room has no active_scene_id. Uses get_or_create to handle repeated
    fires for the same (session, scene) pair.

    Args:
        character: The posing Character typeclass instance.
        session_id (int): RPSession primary key.
        room: The Room typeclass instance.
    """
    scene_id = getattr(room, "active_scene_id", None)
    if not scene_id:
        return

    from evennia_rptracker.models import RPSessionSceneLink

    try:
        RPSessionSceneLink.objects.get_or_create(
            session_id=session_id,
            scene_id=scene_id,
        )
    except Exception:
        logger.exception(
            "rptracker: failed to create RPSessionSceneLink " "(session=%s, scene=%s)",
            session_id,
            scene_id,
        )
