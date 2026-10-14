# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Transactional placements, bounded temporary layers and current-owner credit."""

import math
from datetime import timedelta

from django.apps import apps
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from evennia.objects.models import ObjectDB

from evennia_links.atmosphere import live_scene
from evennia_links.rooms import can, is_live, lock_state, owned_room_ids, owner_of
from evennia_links.runtime import get
from evennia_links.transactions import atomic_objects

from . import conf
from .emissions import emit, frame
from .errors import CraftingError
from .models import CraftRecord, EventRoomLimit, FixtureInstallation, RoomLayer


def _lock(actor, room, item=None):
    from .services import _require

    try:
        lock_state(room)
    except Exception as exc:
        raise CraftingError("Room ownership could not be locked; try again later.") from exc
    ObjectDB.objects.filter(pk=room.pk).update(db_key=F("db_key"))
    _require(actor, spending=False, wave_two=True)
    ids = sorted({actor.pk, room.pk, getattr(item, "pk", None)} - {None})
    locked = {
        row.pk: row
        for row in ObjectDB.objects.select_for_update().filter(pk__in=ids).order_by("pk")
    }
    if actor.pk not in locked or room.pk not in locked or (item and item.pk not in locked):
        raise CraftingError("The room or item is no longer available.")
    actor, room = locked[actor.pk], locked[room.pk]
    if (
        not room.is_typeclass("evennia.objects.objects.DefaultRoom", exact=False)
        or actor.location != room
    ):
        raise CraftingError("Visit the room first.")
    return actor, room, locked.get(getattr(item, "pk", None))


def active_layers(room, now=None):
    rows = RoomLayer.objects.filter(
        room_id=room.pk, cleared_at__isnull=True, expires_at__gt=now or timezone.now()
    ).select_related("craft")
    if apps.is_installed("evennia_scenes"):
        from evennia_scenes.models import Scene

        running = set(
            Scene.objects.filter(status__in=(Scene.Status.OPEN, Scene.Status.ACTIVE)).values_list(
                "pk", flat=True
            )
        )
        return [row for row in rows if row.scene_id is None or row.scene_id in running]
    return list(rows)


def installations(room):
    return FixtureInstallation.objects.filter(room_id=room.pk, active=True).select_related("craft")


def _config(record):
    return record.prose["configuration"]


def _emitter_available(room):
    return not any(
        _config(row.craft).get("ambient") for row in [*installations(room), *active_layers(room)]
    )


def _record(item, actor):
    record = CraftRecord.objects.filter(item_id=item.pk, behaviour="installable").first()
    if record is None or item.location != actor:
        raise CraftingError("Carry a crafted Installable fixture first.")
    return record


def _move(item, destination):
    item.ndb.crafting_placement = True
    try:
        if not item.move_to(destination, quiet=True, move_type="crafting"):
            raise CraftingError("The fixture could not be moved.")
        item.home = destination
    finally:
        item.ndb.crafting_placement = False


def ensure_script():
    from evennia.scripts.models import ScriptDB
    from evennia.utils.create import create_script

    if not ScriptDB.objects.filter(db_key="rp_crafting_ambients").exists():
        create_script("evennia_rp_crafting.scripts.AmbientScript", key="rp_crafting_ambients")


@atomic_objects
def install(actor, item, room):
    actor, room, item = _lock(actor, room, item)
    if not is_live(room) or not (can(actor, room, "install") or conf.is_staff(actor)):
        raise CraftingError("You do not have permission to install here.")
    record = _record(item, actor)
    if FixtureInstallation.objects.filter(craft=record, active=True).exists():
        raise CraftingError("That fixture is already installed.")
    if installations(room).count() >= get("RP_CRAFTING_FIXTURE_ROOM_LIMIT"):
        raise CraftingError("This room is at its fixture limit.")
    if _config(record).get("ambient") and not _emitter_available(room):
        raise CraftingError("This room already has an ambient emitter.")
    _move(item, room)
    row = FixtureInstallation.objects.create(craft=record, room_id=room.pk, installer_id=actor.pk)
    transaction.on_commit(ensure_script)
    return row


def uninstall(actor, item):
    row = FixtureInstallation.objects.filter(craft__item_id=item.pk, active=True).first()
    if row is None:
        raise CraftingError("That fixture is not installed.")
    room = ObjectDB.objects.filter(pk=row.room_id).first()
    if room is None:
        raise CraftingError(
            "The installation room no longer exists; ask staff to recover the fixture."
        )
    return _uninstall(actor, item, room, row.pk)


@atomic_objects
def _uninstall(actor, item, room, placement_id):
    actor, room, item = _lock(actor, room, item)
    row = (
        FixtureInstallation.objects.select_for_update().filter(pk=placement_id, active=True).first()
    )
    if row is None:
        raise CraftingError("That fixture has already been removed.")
    owner = owner_of(room) or owner_of(room, include_inactive=True)
    if actor != owner and not conf.is_staff(actor):
        raise CraftingError("Only the property owner or staff may uninstall fixtures.")
    row.active = False
    row.removed_at = timezone.now()
    row.save(update_fields=["active", "removed_at"])
    _move(item, owner or actor)
    return row


@atomic_objects
def decorate(actor, item, room, *, seconds=None):
    actor, room, item = _lock(actor, room, item)
    if not is_live(room) or not can(actor, room, "decorate"):
        raise CraftingError("You do not have permission to decorate here.")
    record = _record(item, actor)
    limit = get("RP_CRAFTING_TEMPORARY_LAYER_SECONDS")
    seconds = limit if seconds is None else seconds
    if type(seconds) is not int or not 1 <= seconds <= limit:
        raise CraftingError(f"Choose a duration between 1 and {limit} seconds.")
    if len(active_layers(room)) >= get("RP_CRAFTING_TEMPORARY_LAYER_LIMIT"):
        raise CraftingError("This room is at its temporary layer limit.")
    if _config(record).get("ambient") and not _emitter_available(room):
        raise CraftingError("This room already has an ambient emitter.")
    scene = live_scene(room)
    row = RoomLayer.objects.create(
        craft=record,
        room_id=room.pk,
        actor_id=actor.pk,
        scene_id=scene.pk if scene else None,
        expires_at=timezone.now() + timedelta(seconds=seconds),
    )
    transaction.on_commit(ensure_script)
    return row


def clear_layer(actor, layer_id):
    row = RoomLayer.objects.filter(pk=layer_id, cleared_at__isnull=True).first()
    if row is None:
        raise CraftingError("That temporary layer is already cleared.")
    room = ObjectDB.objects.filter(pk=row.room_id).first()
    if room is None:
        raise CraftingError("The layer's room no longer exists.")
    return _clear_layer(actor, layer_id, room)


@atomic_objects
def _clear_layer(actor, layer_id, room):
    actor, room, _ = _lock(actor, room)
    row = RoomLayer.objects.select_for_update().filter(pk=layer_id, cleared_at__isnull=True).first()
    if row is None:
        raise CraftingError("That temporary layer is already cleared.")
    if (
        actor.pk != row.actor_id
        and actor != (owner_of(room) or owner_of(room, include_inactive=True))
        and not conf.is_staff(actor)
    ):
        raise CraftingError("Only its creator, the property owner or staff may clear this layer.")
    RoomLayer.objects.filter(pk=row.pk, cleared_at__isnull=True).update(cleared_at=timezone.now())
    return row


def scene_closed(sender, scene, **kwargs):
    RoomLayer.objects.filter(scene_id=scene.pk, cleared_at__isnull=True).update(
        cleared_at=timezone.now()
    )


def layers(room, field="room_line"):
    if (
        not get("RP_CRAFTING_REVEALED")
        or not get("RP_CRAFTING_WAVE_TWO_REVEALED")
        or not is_live(room)
    ):
        return []
    rows = [
        row
        for row in installations(room)
        if ObjectDB.objects.filter(pk=row.craft.item_id, db_location_id=room.pk).exists()
    ]
    rows += active_layers(room)
    return [
        f"{row.craft.prose['name']}: {_config(row.craft)[field]}"
        for row in rows
        if _config(row.craft).get(field)
    ]


def furnishing_caps(sender, character, **kwargs):
    from decimal import Decimal

    if not get("RP_CRAFTING_WAVE_TWO_REVEALED") or not apps.is_installed("evennia_economy"):
        return {"furnishing": {"money": 0}}
    weeks = Decimal(0)
    ids = owned_room_ids(character)
    placements = FixtureInstallation.objects.filter(active=True).select_related("craft")
    if ids is not None:
        placements = placements.filter(room_id__in=ids)
    placements = list(placements)
    positions = dict(
        ObjectDB.objects.filter(pk__in=[row.craft.item_id for row in placements]).values_list(
            "pk", "db_location_id"
        )
    )
    rooms = {
        room.pk: room
        for room in ObjectDB.objects.filter(pk__in={row.room_id for row in placements})
    }
    valid = {pk for pk, room in rooms.items() if is_live(room) and owner_of(room) == character}
    for row in placements:
        if row.room_id in valid and positions.get(row.craft.item_id) == row.room_id:
            weeks += row.craft.furnishing_weeks
    amount = math.ceil(weeks * get("RP_ECONOMY_WEEKLY_AMOUNT"))
    return {"furnishing": {"money": min(amount, conf.MAX_AMOUNT)}}


def reserve_event(room, now):
    limit, _ = EventRoomLimit.objects.select_for_update().get_or_create(room_id=room.pk)
    if limit.last_used and now < limit.last_used + timedelta(
        seconds=get("RP_CRAFTING_EVENT_ROOM_COOLDOWN")
    ):
        raise CraftingError("An EVENT just happened here. Wait a moment before using this item.")
    limit.last_used = now
    limit.save(update_fields=["last_used"])


@transaction.atomic
def ambient_tick(now=None):
    now = now or timezone.now()
    RoomLayer.objects.filter(cleared_at__isnull=True, expires_at__lte=now).update(cleared_at=now)
    if (
        not get("RP_CRAFTING_REVEALED")
        or not get("RP_CRAFTING_WAVE_TWO_REVEALED")
        or get("RP_CRAFTING_FROZEN")
        or not apps.is_installed("evennia_accessibility")
    ):
        return 0
    emitted = 0
    rooms = set(
        FixtureInstallation.objects.filter(active=True).values_list("room_id", flat=True)
    ) | set(RoomLayer.objects.filter(cleared_at__isnull=True).values_list("room_id", flat=True))
    for room in ObjectDB.objects.select_for_update().filter(pk__in=rooms).order_by("pk"):
        if not is_live(room) or not any(
            getattr(obj, "has_account", False) for obj in room.contents
        ):
            continue
        # Combat is an optional partner. Its room coordinator owns fight state.
        if apps.is_installed("evennia_rp_combat"):
            fight = apps.get_model("evennia_rp_combat", "Fight")
            if fight.objects.filter(room=room, status=fight.OPEN).exists():
                continue
        for row in [*installations(room), *active_layers(room, now)]:
            config = _config(row.craft)
            if not config.get("ambient") or (
                row.last_emitted
                and now < row.last_emitted + timedelta(seconds=get("RP_CRAFTING_AMBIENT_INTERVAL"))
            ):
                continue
            if isinstance(row, FixtureInstallation):
                if not ObjectDB.objects.filter(
                    pk=row.craft.item_id, db_location_id=room.pk
                ).exists():
                    continue
                owner = owner_of(room)
                actor_id = owner.pk if owner else row.installer_id
            else:
                actor_id = row.actor_id
            if not ObjectDB.objects.filter(pk=actor_id).exists():
                continue
            try:
                reserve_event(room, now)
            except CraftingError:
                continue
            row.last_emitted = now
            row.save(update_fields=["last_emitted"])
            message = frame(config["ambient"])
            transaction.on_commit(
                lambda room_id=room.pk, actor_id=actor_id, message=message: emit(
                    room_id, actor_id, message, ambient=True
                )
            )
            emitted += 1
    return emitted
