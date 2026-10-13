# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Economy owns the optional Building integration; property IDs are soft refs."""

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from evennia.objects.models import ObjectDB
from evennia.utils.create import create_object

from evennia_links.rooms import can
from evennia_links.runtime import get
from evennia_links.transactions import atomic_objects

from . import conf
from .models import Storefront
from .services import EconomyError, charge_fee, journal, lock_characters


def property_for(store, *, lock=False):
    if store.kind != "shop" or not store.property_id or not apps.is_installed("evennia_building"):
        return None
    model = apps.get_model("evennia_building", "Property")
    query = model.objects.select_for_update() if lock else model.objects
    return query.filter(pk=store.property_id).first()


def lock_property(store):
    if store.kind == "shop":
        property_for(store, lock=True)


def operational(store, actor=None, *, managing=False):
    if store.kind != "shop":
        return True
    prop = property_for(store)
    if (
        not prop
        or prop.state != "live"
        or prop.owner_id != store.owner_id
        or not prop.owner_id
        or not prop.anchor_id
        or not prop.entrance_id
        or not store.room_id
        or prop.entrance.db_destination_id != store.room_id
        or not prop.rooms.filter(room_id=store.room_id, owner_id=store.owner_id).exists()
        or (not get("BUILDING_REVEALED") and not (actor and conf.is_staff(actor)))
    ):
        return False
    if actor and not managing:
        from evennia_building.access import can_enter

        if not can_enter(actor, store.room):
            return False
    return not managing or bool(
        actor and actor.pk == prop.owner_id and can(actor, store.room, "configure")
    )


@atomic_objects
def create_for_property(property, actor):
    from .batch import period_key

    if not apps.is_installed("evennia_building"):
        raise EconomyError("Building is not installed.")
    model = apps.get_model("evennia_building", "Property")
    prop = model.objects.select_for_update().get(pk=property.pk)
    existing = Storefront.objects.filter(property_id=prop.pk).first()
    if existing:
        return existing
    if prop.provenance.get("purpose") != "shop":
        raise EconomyError("Only an approved shop property can receive a storefront.")
    room = prop.entrance.destination if prop.entrance else None
    if (
        not prop.owner
        or not room
        or prop.state != "live"
        or not prop.rooms.filter(room=room).exists()
    ):
        raise EconomyError("Repair the approved shop's owner or entrance before opening it.")
    lock_characters(prop.owner)
    ObjectDB.objects.select_for_update().get(pk=room.pk)
    charge_fee("shop_approval", prop.owner, {"property_id": prop.pk})
    holding = create_object(
        "evennia_economy.typeclasses.StallStock", key="Shop stock", location=None
    )
    occupied = set(
        Storefront.objects.filter(room=room, status="open").values_list("slot", flat=True)
    )
    slot = next(n for n in range(1, len(occupied) + 2) if n not in occupied)
    store = Storefront.objects.create(
        kind="shop",
        property_id=prop.pk,
        owner=prop.owner,
        room=room,
        holding=holding,
        name=prop.name[:120],
        slot=slot,
        last_active=timezone.now(),
        upkeep_period=period_key(),
    )
    journal(
        "shop_approval",
        giver=prop.owner,
        by=actor,
        note=f"Opened shop #{store.pk} for property #{prop.pk}.",
    )
    return store


def on_promoted(sender, property, actor, **kwargs):
    if property.provenance.get("purpose") == "shop":
        try:
            create_for_property(property, actor)
        except EconomyError as exc:
            raise ValidationError(str(exc)) from exc


def reconcile(actor, property_id):
    if not conf.is_staff(actor):
        raise EconomyError("Only staff may reconcile approved shops.")
    if not apps.is_installed("evennia_building"):
        raise EconomyError("Building is not installed.")
    prop = apps.get_model("evennia_building", "Property").objects.filter(pk=property_id).first()
    if not prop:
        raise EconomyError("No such property.")
    return create_for_property(prop, actor)


def on_transferring(sender, property, actor, new_owner, stock_disposition, **kwargs):
    from .stalls import _return

    initial = Storefront.objects.filter(property_id=property.pk).first()
    if not initial:
        return
    if stock_disposition not in {"return", "transfer"}:
        raise ValidationError(
            "Choose shop stock disposition: return to the old owner, or transfer with the shop."
        )
    if not initial.owner:
        raise ValidationError("Repair the shop's owner before transferring the property.")
    lock_characters(initial.owner, new_owner)
    store = Storefront.objects.select_for_update().get(pk=initial.pk)
    try:
        if stock_disposition == "transfer":
            from . import assets
            from .services import same_account

            listings = list(store.listings.filter(status="active"))
            if listings and same_account(store.owner, new_owner):
                raise EconomyError(
                    "Shop stock cannot transfer between characters on the same account; choose return."
                )
            for listing in listings:
                if listing.assets[0]["kind"] == "item":
                    assets.check(store.holding, new_owner, listing.assets, item_giver=store.owner)
        if stock_disposition == "return":
            for listing in (
                store.listings.select_for_update().filter(status="active").order_by("pk")
            ):
                _return(store, listing)
        old_owner = store.owner
        store.owner = new_owner
        store.save(update_fields=["owner"])
        journal(
            "shop_transfer",
            giver=old_owner,
            recipient=new_owner,
            by=actor,
            note=f"Property #{property.pk}; shop #{store.pk}; stock disposition: {stock_disposition}.",
        )
    except EconomyError as exc:
        raise ValidationError(str(exc)) from exc


@transaction.atomic
def reopen(actor, store_id):
    from .services import require_open

    require_open()
    store = Storefront.objects.filter(pk=store_id, kind="shop").first()
    if not store or not store.owner:
        raise EconomyError("No such shop.")
    lock_property(store)
    lock_characters(actor, store.owner)
    store = Storefront.objects.select_for_update().get(pk=store_id)
    if not operational(store, actor, managing=True):
        raise EconomyError("Only the current owner can reopen a live shop.")
    if store.status == "open":
        return store
    ObjectDB.objects.select_for_update().get(pk=store.room_id)
    occupied = set(
        Storefront.objects.filter(room=store.room, status="open").values_list("slot", flat=True)
    )
    store.slot = next(n for n in range(1, len(occupied) + 2) if n not in occupied)
    store.status = "open"
    store.last_active = timezone.now()
    store.save(update_fields=["slot", "status", "last_active"])
    journal("shop_reopen", giver=actor, note=f"Reopened shop #{store.pk}.")
    return store
