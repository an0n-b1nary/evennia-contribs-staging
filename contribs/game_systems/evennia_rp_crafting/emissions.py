# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Attributed item output: scene content, never posing or RP activity."""

from django.apps import apps
from django.conf import settings
from evennia.objects.models import ObjectDB
from evennia.utils import logger

from evennia_links.rooms import is_live
from evennia_links.runtime import get


def frame(text):
    return getattr(settings, "RP_CRAFTING_EVENT_FRAME", "<EVENT> {text}").format(text=text)


def emit(room_id, actor_id, message, *, ambient=False, wave_three=False):
    if (
        not get("RP_CRAFTING_REVEALED")
        or not get(
            "RP_CRAFTING_WAVE_THREE_REVEALED" if wave_three else "RP_CRAFTING_WAVE_TWO_REVEALED"
        )
        or get("RP_CRAFTING_FROZEN")
    ):
        return
    room = ObjectDB.objects.filter(pk=room_id).first()
    actor = ObjectDB.objects.filter(pk=actor_id).first()
    if room is None or actor is None or not is_live(room):
        return
    if ambient and not apps.is_installed("evennia_accessibility"):
        return
    for target in room.contents:
        if ambient:
            from evennia_accessibility import mutes_ambient

            if mutes_ambient(target):
                continue
        try:
            target.msg((message, {"type": "crafting_event"}), from_obj=actor)
        except Exception:
            logger.log_trace("Crafted emission delivery failed.")
    if apps.is_installed("evennia_scenes"):
        from evennia_scenes.models import LogEntry, Scene

        scene = (
            Scene.objects.filter(
                room_id=room_id, status__in=(Scene.Status.OPEN, Scene.Status.ACTIVE)
            )
            .order_by("-created_at")
            .first()
        )
        if scene:
            LogEntry.create_entry(scene=scene, author=actor, content=message, log_type="emit")
