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
    """Wave-two/three output; legacy events use deliver without these wave gates."""
    if not get(
        "RP_CRAFTING_WAVE_THREE_REVEALED" if wave_three else "RP_CRAFTING_WAVE_TWO_REVEALED"
    ):
        return
    deliver(room_id, actor_id, message, ambient=ambient)


def deliver(source_id, actor_id, message, *, ambient=False, destination_ids=()):
    """Deliver committed output and log it once per live room, never as posing.

    Source output is local unless explicitly ambient. Broadcast destinations
    always honour ambient mute and share account deduplication with the source.
    Audience and attributed actor are resolved at delivery, after consumption.
    """
    if not get("RP_CRAFTING_REVEALED") or get("RP_CRAFTING_FROZEN"):
        return
    source = ObjectDB.objects.filter(pk=source_id).first()
    actor = ObjectDB.objects.filter(pk=actor_id).first()
    if source is None or actor is None or not is_live(source):
        return
    mute = None
    if apps.is_installed("evennia_accessibility"):
        from evennia_accessibility import mutes_ambient

        mute = mutes_ambient
    if ambient and mute is None:
        return
    rooms = [source]
    if mute is not None:
        rooms.extend(
            ObjectDB.objects.filter(pk__in=set(destination_ids) - {source_id}).order_by("pk")
        )
    local = list(source.contents)
    delivered_accounts = {obj.account.pk for obj in local if getattr(obj, "account", None)}
    seen = set()
    for room in rooms:
        if not is_live(room):
            continue
        remote = room.pk != source_id
        for target in local if not remote else room.contents:
            account = getattr(target, "account", None)
            account_id = account.pk if account else None
            if remote and account_id is not None and account_id in delivered_accounts:
                continue
            identity = (target.__dbclass__, target.pk)
            if identity in seen:
                continue
            seen.add(identity)
            try:
                if (ambient or remote) and mute(target):
                    continue
                target.msg((message, {"type": "crafting_event"}), from_obj=actor)
                if account_id is not None:
                    delivered_accounts.add(account_id)
            except Exception:
                logger.log_trace("Crafted emission delivery failed.")
        if apps.is_installed("evennia_scenes"):
            try:
                from evennia_scenes.capture import capture_room_event

                capture_room_event(room, actor, message)
            except Exception:
                logger.log_trace("Crafted emission scene capture failed.")
