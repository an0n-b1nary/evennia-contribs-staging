# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Scene display helpers for cross-app consumers.

Provides the RPTRACKER_SCENE_DISPLAY hook: a callable that renders a scene
reference from an integer scene_id (the soft-reference stored in
RPSessionSceneLink) into a human-readable string.

Usage in settings::

    RPTRACKER_SCENE_DISPLAY = "evennia_scenes.display.render_scene_ref"
"""


def render_scene_ref(scene_id):
    """Return a display string for a scene given its integer pk.

    Args:
        scene_id (int): The Scene pk stored in a soft-reference field.

    Returns:
        str: "Scene #<public number>: <title>" if the scene exists, else
            "Scene unavailable".
    """
    try:
        from evennia_scenes.models import Scene

        scene = Scene.objects.only("pk", "scene_number", "title").get(pk=scene_id)
        title = scene.title or "Untitled"
        return f"Scene #{scene.scene_number}: {title}"
    except Exception:
        return "Scene unavailable"
