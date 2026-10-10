# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Observe persisted drops/gets, including ordinary objects without a mixin."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from evennia.objects.models import ObjectDB

from evennia_links.characters import account_ids, same_account

from .models import DroppedItem, Listing, Storefront
from .review import flag_event
from .services import EconomyError, journal


def before_location_save(sender, instance, raw=False, update_fields=None, **kwargs):
    if raw or not isinstance(instance, ObjectDB) or not instance.pk:
        return
    if update_fields is not None and "db_location" not in update_fields:
        return
    old = ObjectDB.objects.filter(pk=instance.pk).values_list("db_location_id", flat=True).first()
    instance.__dict__["_economy_old_location"] = old
    if old == instance.db_location_id:
        return
    if (
        old
        and Storefront.objects.filter(holding_id=old).exists()
        and any(
            str(instance.pk) == a["key"] and a["kind"] == "item"
            for row in Listing.objects.filter(storefront__holding_id=old, status="active")
            for a in row.assets
        )
    ):
        raise EconomyError("Unlist or buy the item before moving stall stock.")


def after_location_save(sender, instance, raw=False, **kwargs):
    if (
        raw
        or not isinstance(instance, ObjectDB)
        or "_economy_old_location" not in instance.__dict__
    ):
        return
    old_id = instance.__dict__.pop("_economy_old_location", None)
    new_id = instance.db_location_id
    if old_id == new_id:
        return
    # A drop is from a playable character into that character's current room.
    old = ObjectDB.objects.filter(pk=old_id).first() if old_id else None
    new = ObjectDB.objects.filter(pk=new_id).first() if new_id else None
    old_accounts = account_ids(old) if old else []
    if old_accounts and new and old.db_location_id == new.pk:
        DroppedItem.objects.update_or_create(
            item=instance,
            defaults={
                "giver_id": old.pk,
                "giver_name": old.key,
                "accounts": old_accounts,
                "room_id": new.pk,
            },
        )
        return
    drop = DroppedItem.objects.filter(item=instance).first()
    if not drop:
        return
    with transaction.atomic():
        if (
            new
            and old_id == drop.room_id
            and new.db_location_id == old_id
            and drop.created >= timezone.now() - timedelta(days=7)
        ):
            giver = ObjectDB.objects.filter(pk=drop.giver_id).first()
            if new.pk != drop.giver_id and giver and same_account(giver, new):
                entry = journal(
                    "item_pass",
                    giver=giver,
                    recipient=new,
                    assets=[{"kind": "item", "key": str(instance.pk), "quantity": 1}],
                    note=f"Dropped by {drop.giver_name} (#{drop.giver_id}) in room #{drop.room_id}.",
                )
                flag_event(
                    "floor_pass",
                    f"floor:{entry.pk}",
                    "Economy: same-account floor transfer",
                    f"{drop.giver_name} (#{drop.giver_id}) dropped {instance.key} (#{instance.pk}) in room #{drop.room_id}; {new.key} (#{new.pk}) picked it up within seven days. The characters share a playable account. Review only; pickup was allowed.",
                    entry=entry,
                )
        drop.delete()


def guard_stock_deletion(sender, instance, **kwargs):
    if not isinstance(instance, ObjectDB):
        return
    if Storefront.objects.filter(holding_id=instance.pk).exists():
        raise EconomyError("Stall stock containers retain the storefront's history.")
    if any(
        a["kind"] == "item" and a["key"] == str(instance.pk)
        for row in Listing.objects.filter(status="active")
        for a in row.assets
    ):
        raise EconomyError("Unlist or buy the item before destroying stall stock.")
    # Fail closed instead of orphaning reserved stock when a host deletes an owner/room.
    if (
        Storefront.objects.filter(status="open").filter(owner=instance).exists()
        or Storefront.objects.filter(status="open", room=instance).exists()
    ):
        raise EconomyError("Close this object's stalls before deleting it.")
