# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Shared temporary atmosphere policy, independent of Social and Crafting."""

from django.apps import apps
from django.conf import settings

from .collect import resolve_dotted


def live_scene(room):
    label = getattr(settings, "SOCIAL_SCENES_APP_LABEL", "evennia_scenes")
    try:
        model = apps.get_model(label, "Scene")
    except LookupError:
        return None
    return (
        model.objects.filter(room_id=room.pk, status__in=(model.Status.OPEN, model.Status.ACTIVE))
        .order_by("-created_at")
        .first()
    )


def can_decorate(actor, room):
    """Owners/staff, public-scene participants, or private-scene hosts.

    Preserve Social's authoritative host extension, including fail-closed
    errors. A grant here never grants installation or configuration rights.
    """
    from .rooms import can

    if not actor or not room:
        return False
    provider = getattr(settings, "SOCIAL_ROOM_MOOD_PERMISSION", None)
    if provider:
        try:
            callback = resolve_dotted(provider) if isinstance(provider, str) else provider
            result = callback(actor, room)
        except Exception:
            return False
        if result is not None:
            return result if type(result) is bool else False
    if can(actor, room, "configure") or actor.locks.check_lockstring(actor, "perm(Builder)"):
        return True
    scene = live_scene(room)
    if scene is None:
        return False
    if scene.creator_id == actor.pk:
        return True
    if scene.privacy != scene.Privacy.PUBLIC:
        return False
    participant = apps.get_model(scene._meta.app_label, "SceneParticipant")
    return participant.objects.filter(
        scene=scene, character_id=actor.pk, is_active=True, role=participant.Role.PARTICIPANT
    ).exists()
