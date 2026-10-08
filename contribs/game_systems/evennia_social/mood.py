# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Room mood — a line of atmosphere shown under a room's description.

State lives on ``SocialRoomMixin`` (``room_mood``, ``room_mood_setter``); the
``+mood`` command (commands/mood.py) is the in-game way to change it.

Who may set it (``can_set_mood``):

* The room's owner (``control`` access) or Builder+ staff, always — the same
  gate as ``+roomconfig``.
* With ``evennia-scenes`` installed and a scene running in the room:
    - **public** scene: any active participant (observers excluded);
    - any other privacy tier: the scene's host only. A tier this module does
      not know about is treated as private, so a new tier fails closed.

``evennia-scenes`` is a soft partner, located through the
``SOCIAL_SCENES_APP_LABEL`` setting (default ``"evennia_scenes"``). Without it,
only owners and staff can set a mood.
"""

from django.apps import apps
from django.conf import settings

from evennia_social.social import is_staff

#: Longest mood accepted, in characters. A mood is one line of atmosphere,
#: not a second room description.
MOOD_MAX_LENGTH = 200


def _scene_models():
    """Return ``(Scene, SceneParticipant)`` from the scenes partner, or None."""
    label = getattr(settings, "SOCIAL_SCENES_APP_LABEL", "evennia_scenes")
    if not apps.is_installed(label) and not any(
        cfg.label == label for cfg in apps.get_app_configs()
    ):
        return None
    try:
        return apps.get_model(label, "Scene"), apps.get_model(label, "SceneParticipant")
    except LookupError:
        return None


def live_scene(room):
    """The scene currently running in *room* (open or active), or None."""
    models = _scene_models()
    if models is None:
        return None
    scene_model, _participant = models
    running = (scene_model.Status.OPEN, scene_model.Status.ACTIVE)
    return (
        scene_model.objects.filter(room_id=room.pk, status__in=running)
        .order_by("-created_at")
        .first()
    )


def can_set_mood(character, room):
    """True if *character* may set or clear *room*'s mood. See module docstring."""
    if room.access(character, "control") or is_staff(character):
        return True
    scene = live_scene(room)
    if scene is None:
        return False
    if scene.creator_id == character.pk:
        return True
    scene_model, participant_model = _scene_models()
    if scene.privacy != scene_model.Privacy.PUBLIC:
        return False
    return participant_model.objects.filter(
        scene=scene,
        character_id=character.pk,
        is_active=True,
        role=participant_model.Role.PARTICIPANT,
    ).exists()


def set_mood(room, text, setter):
    """Set *room*'s mood to *text*, attributed to *setter*. Returns the stored text.

    Raises:
        ValueError: *text* is empty or longer than ``MOOD_MAX_LENGTH``.
    """
    text = " ".join(text.split())
    if not text:
        raise ValueError("A mood can't be empty; use +mood/clear to remove it.")
    if len(text) > MOOD_MAX_LENGTH:
        raise ValueError(f"Keep a mood to {MOOD_MAX_LENGTH} characters (that was {len(text)}).")
    room.room_mood = text
    room.room_mood_setter = setter.key
    return text


def clear_mood(room):
    """Remove *room*'s mood. Returns the text that was cleared ("" if none)."""
    old = room.room_mood or ""
    room.room_mood = ""
    room.room_mood_setter = None
    return old
