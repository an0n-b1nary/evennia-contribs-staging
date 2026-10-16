# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Consume once, persist room limits, deliver framed prose only after commit."""

from datetime import timedelta

from django.apps import apps
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from evennia.objects.models import ObjectDB

from evennia_links.runtime import get

from .emissions import deliver
from .errors import CraftingError
from .models import CraftRecord, EventRoomLimit, EventUse
from .services import _require


def _remote(record, actor, room):
    """Rooms a Broadcast reaches; no accessibility means no remote recipients."""
    if record.behaviour != "broadcast" or not apps.is_installed("evennia_accessibility"):
        return []
    try:
        from evennia_accessibility import mutes_ambient  # noqa: F401
    except ImportError:
        return []  # Older partners have no working opt-out.
    destinations = {
        exit.destination.pk: exit.destination
        for exit in room.exits
        if exit.destination
        and exit.destination != room
        and exit.access(actor, "view", default=True)
        and exit.access(actor, "traverse", default=False)
    }
    return list(destinations.values())


@transaction.atomic
def use(actor, item):
    _require(actor, spending=False)
    location_id = (
        ObjectDB.objects.select_for_update()
        .values_list("db_location_id", flat=True)
        .get(pk=actor.pk)
    )
    if not location_id:
        raise CraftingError("Use the item in a room.")
    item_id = item.pk
    locked_item = (
        ObjectDB.objects.select_for_update().filter(pk=item_id).values("db_location_id").first()
        if item_id
        else None
    )
    if locked_item is None:
        raise CraftingError("That item has already been used or removed.")
    if locked_item["db_location_id"] != actor.pk or not item.access(actor, "use", default=True):
        raise CraftingError("Carry the item and have permission to use it.")
    record = CraftRecord.objects.filter(item_id=item_id).first()
    if record is None or record.behaviour not in ("consumable", "broadcast"):
        raise CraftingError("Only crafted Consumables and Broadcasts can emit an EVENT.")
    if EventUse.objects.filter(craft=record).exists():
        raise CraftingError("That item has already been used.")
    room = ObjectDB.objects.get(pk=location_id)
    rooms = _remote(record, actor, room)
    # Serialize on the actual rooms before creating their first limit rows.
    # Include destination rooms: separate sources cannot flood one audience.
    room_ids = sorted({room.pk, *(destination.pk for destination in rooms)})
    list(ObjectDB.objects.select_for_update().filter(pk__in=room_ids).order_by("pk"))
    now = timezone.now()
    limits = []
    for room_id in room_ids:
        limit, _ = EventRoomLimit.objects.get_or_create(room_id=room_id)
        if limit.last_used and now < limit.last_used + timedelta(
            seconds=get("RP_CRAFTING_EVENT_ROOM_COOLDOWN")
        ):
            raise CraftingError(
                "An EVENT just happened here. Wait a moment before using this item."
            )
        limits.append(limit)
    frame = getattr(settings, "RP_CRAFTING_EVENT_FRAME", "<EVENT> {text}")
    try:
        message = "\n".join(
            frame.format(text=beat) for beat in record.prose["configuration"]["beats"]
        )
    except (AttributeError, KeyError, ValueError, IndexError) as exc:
        raise CraftingError("The game's EVENT frame is misconfigured.") from exc
    destination_ids = [destination.pk for destination in rooms]
    result = EventUse.objects.create(
        craft=record,
        actor_id=actor.pk,
        actor_name=actor.key,
        room_id=room.pk,
        destinations={"rooms": destination_ids},
    )
    if not item.delete():
        raise CraftingError("The item cannot be consumed right now.")
    EventRoomLimit.objects.filter(pk__in=[limit.pk for limit in limits]).update(last_used=now)
    transaction.on_commit(
        lambda room_id=room.pk, actor_id=actor.pk: deliver(
            room_id, actor_id, message, destination_ids=destination_ids
        )
    )
    return result
