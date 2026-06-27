# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Signal listeners for evennia_plots.

Registered by PlotsConfig.ready() when the scenes app is present (gated on
PLOTS_SCENES_APP_LABEL). Mirrors the on_scene_linked_to_thread listener that
shipped in the hub's links layer — the listener moves into the spoke (the plots
contrib) because it is plots-domain logic: auto-creating PlotParticipant rows
from a linked scene's participants.
"""

import logging

logger = logging.getLogger(__name__)


def on_scene_linked_to_thread(sender, thread, scene, linked_by, **kwargs):
    """Auto-create PlotParticipant records when a Scene is linked to a PlotThread.

    Called when the scene_linked_to_thread signal fires (from
    ScenePlotLink.create_link). Creates a PlotParticipant for each active
    SceneParticipant of the linked scene. Uses get_or_create to be idempotent
    — safe to call repeatedly if the same scene is linked more than once.

    Args:
        sender: The ScenePlotLink model class.
        thread: PlotThread instance.
        scene: Scene instance.
        linked_by: ObjectDB character who created the link (may be None).
    """
    from evennia_plots.models import PlotParticipant

    try:
        participants = scene.participants.filter(is_active=True).select_related("character")
        for sp in participants:
            if sp.character_id is None:
                continue
            PlotParticipant.objects.get_or_create(
                thread=thread,
                character_id=sp.character_id,
                defaults={"character_name": sp.character_name},
            )
    except Exception:
        logger.exception(
            "evennia_plots.listeners: failed to create PlotParticipants " "(thread=%s, scene=%s)",
            thread.pk,
            scene.pk,
        )
