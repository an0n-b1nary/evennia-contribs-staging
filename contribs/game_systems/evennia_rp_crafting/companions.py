# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Cosmetic objects with transferable ownership and explicit follow/stay state."""

from datetime import timedelta

from django.apps import apps
from django.db import transaction
from django.utils import timezone
from evennia.objects.models import ObjectDB
from evennia.objects.objects import DefaultCharacter, DefaultObject
from evennia.utils import logger

from evennia_links.communication import denial
from evennia_links.rooms import is_live
from evennia_links.runtime import get
from evennia_links.transactions import atomic_objects

from . import conf
from .behaviours import Behaviour
from .emissions import emit, frame
from .errors import CraftingError
from .models import CompanionState, CraftRecord
from .typeclasses import CraftedItemMixin
from .wave_two import line


class Companion(Behaviour):
    fields = ("arrival", "ambient")
    typeclass = "evennia_rp_crafting.companions.CompanionObject"
    typeclass_setting = "RP_CRAFTING_COMPANION_TYPECLASS"

    def validate(self, config):
        config = super().validate(config)
        result = {key: line(config[key], key) if config.get(key) else "" for key in self.fields}
        if any(result.values()) and not apps.is_installed("evennia_accessibility"):
            raise CraftingError("Automatic companion output requires Accessibility.")
        return result

    def create(self, actor, name, description, config):
        item = super().create(actor, name, description, config)
        CompanionState.objects.create(item=item, owner_id=actor.pk)
        return item


def state(item):
    row = CompanionState.objects.filter(item=item).first()
    if (
        row is None
        or not CraftRecord.objects.filter(item_id=item.pk, behaviour="companion").exists()
    ):
        raise CraftingError("That is not a crafted Companion.")
    return row


def _require(owner, item):
    from .services import _require as require_crafting

    require_crafting(owner, spending=False, wave_three=True)
    row = state(item)
    if row.owner_id != owner.pk:
        raise CraftingError("Only the current owner may direct this Companion.")
    if owner.location is None or item.location not in (owner, owner.location):
        raise CraftingError("Visit or carry your Companion first.")
    return row


@atomic_objects
def set_mode(owner, item, mode):
    ObjectDB.objects.select_for_update().get(pk=owner.pk)
    ObjectDB.objects.select_for_update().get(pk=item.pk)
    row = _require(owner, item)
    if mode not in ("follow", "stay"):
        raise CraftingError("Choose follow or stay.")
    if item.location == owner and (
        not is_live(owner.location)
        or not item.move_to(owner.location, quiet=True, move_type="companion")
    ):
        raise CraftingError("Your Companion cannot be placed here.")
    row.mode = mode
    row.save(update_fields=["mode"])
    return row


def moved(item, source_location):
    """Called by both ordinary handoffs and Economy's committed transfer hook."""
    row = CompanionState.objects.filter(item=item).first()
    if row is None:
        return
    # Read the authoritative holder, including Economy's direct SQL transfers.
    holder_id = ObjectDB.objects.filter(pk=item.pk).values_list("db_location_id", flat=True).get()
    holder = ObjectDB.objects.filter(pk=holder_id).first()
    if isinstance(holder, DefaultCharacter):
        item.home = holder
        row.owner_id = holder.pk
        row.mode = "stay"
        row.save(update_fields=["owner_id", "mode"])
    elif source_location and isinstance(source_location, DefaultCharacter):
        CompanionState.objects.filter(pk=row.pk).update(mode="stay")


class CompanionObject(CraftedItemMixin, DefaultObject):
    """No inventory, puppeting, combat statistics or autonomous mechanical actions."""

    def at_object_creation(self):
        super().at_object_creation()
        self.locks.add("puppet:false();call:false()")

    def access(self, accessing_obj, access_type="read", default=False, **kwargs):
        if access_type == "view" and apps.is_installed("evennia_social"):
            from evennia_links.characters import account_ids

            account = getattr(accessing_obj, "account", None)
            row = CompanionState.objects.filter(item=self).first()
            owner = ObjectDB.objects.filter(pk=row.owner_id).first() if row else None
            if account and owner:
                ids = set(account_ids(owner))
                if owner.account:
                    ids.add(owner.account.pk)
                if ids & set(account.db.ignore_list or []):
                    from evennia.accounts.models import AccountDB

                    if not any(
                        actor.check_permstring("Builder")
                        for actor in AccountDB.objects.filter(pk__in=ids)
                    ):
                        return False
        return super().access(accessing_obj, access_type, default, **kwargs)

    def at_pre_get(self, getter, **kwargs):
        row = CompanionState.objects.filter(item=self).first()
        if row is None or getter.pk != row.owner_id:
            getter.msg("Only its owner may pick up this Companion.")
            return False
        return super().at_pre_get(getter, **kwargs)

    def at_post_move(self, source_location, **kwargs):
        super().at_post_move(source_location, **kwargs)
        moved(self, source_location)

    def announce_move_from(self, destination, **kwargs):
        if not self.ndb.crafting_following:
            return super().announce_move_from(destination, **kwargs)
        return None

    def announce_move_to(self, source_location, **kwargs):
        if not self.ndb.crafting_following:
            return super().announce_move_to(source_location, **kwargs)
        return None

    def at_pre_object_receive(self, arriving_object, source_location, **kwargs):
        # No inventory: refuse before arrival so give/put report the failure.
        return False


def owner_moved(owner, source_location):
    if source_location is None or not conf.wave_three_visible(owner) or get("RP_CRAFTING_FROZEN"):
        return
    destination = owner.location
    if destination is None or not is_live(destination):
        return
    for row in CompanionState.objects.filter(owner_id=owner.pk, mode="follow").select_related(
        "item"
    ):
        item = row.item
        if item.location != source_location:
            continue
        paths = [
            exit_obj for exit_obj in source_location.exits if exit_obj.destination == destination
        ]
        path = next((exit_obj for exit_obj in paths if exit_obj.access(item, "traverse")), None)
        if path and destination.access(item, "enter", default=True):
            # Run the host exit's actual traversal hook, including property and
            # custom route checks. Suppress stock arrivals in favour of muted,
            # attributed companion prose after a successful move.
            item.ndb.crafting_following = True
            try:
                path.at_traverse(item, destination)
            except Exception:
                logger.log_trace("Companion traversal failed.")
            finally:
                item.ndb.crafting_following = False
        if item.location != destination:
            owner.msg(f"{item.key} stays behind; it could not follow you.")
            continue
        record = CraftRecord.objects.filter(item_id=item.pk, behaviour="companion").first()
        arrival = record.prose["configuration"].get("arrival") if record else ""
        if arrival:
            from .fixtures import reserve_event

            # Arrivals are automatic output: share the room's EVENT limit, so
            # pacing between rooms arrives quietly instead of repeating prose.
            try:
                with transaction.atomic():
                    reserve_event(destination, timezone.now())
            except CraftingError:
                continue
            emit(destination.pk, owner.pk, frame(arrival), ambient=True, wave_three=True)


def pose(owner, item, prose):
    _require(owner, item)
    blocked = denial(owner, "room")
    if blocked:
        raise CraftingError(blocked)
    recorder = getattr(owner, "record_pose", None)
    if recorder is None:
        raise CraftingError("Companion poses require the host's owner posing integration.")
    prose = line(prose, "Companion pose")
    message = f"{item.key} {prose}"
    owner.location.msg_contents((message, {"type": "pose"}), from_obj=owner)
    recorder(message, pose_type="emit")


@transaction.atomic
def ambient_tick(now=None):
    if (
        not get("RP_CRAFTING_REVEALED")
        or not get("RP_CRAFTING_WAVE_THREE_REVEALED")
        or get("RP_CRAFTING_FROZEN")
        or not apps.is_installed("evennia_accessibility")
    ):
        return 0
    now = now or timezone.now()
    count = 0
    for row in CompanionState.objects.select_for_update().select_related("item").order_by("pk"):
        owner = ObjectDB.objects.filter(pk=row.owner_id).first()
        room = row.item.location
        if (
            owner is None
            or not owner.has_account
            or room is None
            or not is_live(room)
            or not room.is_typeclass("evennia.objects.objects.DefaultRoom", exact=False)
            or not any(obj.has_account for obj in room.contents)
        ):
            continue
        if apps.is_installed("evennia_rp_combat"):
            fight_model = apps.get_model("evennia_rp_combat", "Fight")
            if fight_model.objects.filter(
                room_id__in=[owner.db_location_id, room.pk], status=fight_model.OPEN
            ).exists():
                continue
        if row.last_emitted and now < row.last_emitted + timedelta(
            seconds=get("RP_CRAFTING_AMBIENT_INTERVAL")
        ):
            continue
        record = CraftRecord.objects.filter(item_id=row.item_id, behaviour="companion").first()
        ambient = record.prose["configuration"].get("ambient") if record else ""
        if not ambient:
            continue
        from .fixtures import reserve_event

        try:
            reserve_event(room, now)
        except CraftingError:
            continue
        row.last_emitted = now
        row.save(update_fields=["last_emitted"])
        message = frame(ambient)
        transaction.on_commit(
            lambda room_id=room.pk, owner_id=owner.pk, message=message: emit(
                room_id, owner_id, message, ambient=True, wave_three=True
            )
        )
        count += 1
    return count


class CompanionCharacterMixin:
    """Place before the host Character; cooperate with all movement hooks."""

    def at_post_move(self, source_location, **kwargs):
        super().at_post_move(source_location, **kwargs)
        owner_moved(self, source_location)
