# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Public capture hooks for scene logging.

Called by the game's character pose hooks and room receive hooks to feed
activity into the scene log. No Evennia typeclass inheritance is required —
games call these functions from their own typeclasses.

``capture_to_scene(character, content, log_type)`` — call from your
character's pose/emit/say recording hook whenever the character performs an IC
action.

``register_room_entry(room, character)`` — call from your Room.at_object_receive
inside whatever guard identifies player characters. Evennia ships no room-receive
signal, so this hook cannot be auto-wired in ScenesConfig.ready() — the game
must call it manually.
"""


def capture_to_scene(character, content, log_type="pose"):
    """
    Create a LogEntry in the character's room's active scene, if any.

    This is a no-op if:
    - The character has no location.
    - The room has no ``active_scene_id`` attribute.
    - The referenced scene no longer exists or is not open/active
      (stale id is cleared from the room).

    Args:
        character: The ObjectDB (Character) instance.
        content: The text to log.
        log_type: One of the LogEntry.LogType values (e.g., "pose",
            "emit", "say", "ooc").
    """
    location = character.location
    if not location:
        return

    scene_id = getattr(location, "active_scene_id", None)
    if not scene_id:
        return

    from evennia_scenes.models import LogEntry, Scene

    try:
        scene = Scene.objects.get(
            pk=scene_id,
            status__in=(Scene.Status.OPEN, Scene.Status.ACTIVE),
        )
    except Scene.DoesNotExist:
        # Stale active_scene_id — clear it.
        location.active_scene_id = None
        return

    LogEntry.create_entry(
        scene=scene,
        author=character,
        content=content,
        log_type=log_type,
    )


def register_room_entry(room, character):
    """
    Auto-register an arriving character as a scene participant.

    Call this from the game's Room.at_object_receive inside whatever guard
    confirms that the arriving object is a player character. Evennia ships no
    room-receive signal, so this hook cannot be auto-wired in
    ScenesConfig.ready() — the game must call it manually.

    This is a no-op if:
    - The room has no ``active_scene_id`` attribute.
    - The referenced scene no longer exists or is not open/active
      (stale id is cleared from the room).
    - The character is already an active participant (idempotent).

    Args:
        room: The Room (ObjectDB) instance the character entered.
        character: The ObjectDB (Character) instance that arrived.
    """
    scene_id = getattr(room, "active_scene_id", None)
    if not scene_id:
        return

    from evennia_scenes.models import Scene, SceneParticipant

    try:
        scene = Scene.objects.get(
            pk=scene_id,
            status__in=(Scene.Status.OPEN, Scene.Status.ACTIVE),
        )
    except Scene.DoesNotExist:
        # Stale active_scene_id — clear it.
        room.active_scene_id = None
        return

    participant, created = SceneParticipant.objects.get_or_create(
        scene=scene,
        character=character,
        defaults={"character_name": character.key},
    )
    if not created and not participant.is_active:
        participant.rejoin()
