# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Reserved stock, offline sales and explicit closure. Lock characters before stores."""

from django.db import transaction
from django.utils import timezone
from evennia.objects.models import ObjectDB
from evennia.utils.create import create_object

from evennia_links.runtime import get

from . import assets, conf
from .models import Listing, Storefront
from .review import flag_round_trips
from .services import (
    EconomyError,
    _adjust,
    charge_fee,
    journal,
    lock_characters,
    quantity,
    require_open,
    same_account,
)


def place(character):
    return ObjectDB.objects.filter(pk=character.pk).values_list("db_location_id", flat=True).get()


def _visible(character):
    if not conf.visible(character):
        raise EconomyError("The market is not available.")


def _store(actor, store_id, *, staff=False, here=True):
    store = Storefront.objects.select_for_update().filter(pk=store_id, status="open").first()
    if (
        not store
        or not store.owner
        or (actor.pk != store.owner_id and not (staff and conf.is_staff(actor)))
    ):
        raise EconomyError("No open stall belonging to you.")
    if here and place(actor) != store.room_id:
        raise EconomyError("Visit the stall's room first.")
    return store


def _lock_owner(actor, store_id):
    owner = Storefront.objects.filter(pk=store_id).values_list("owner_id", flat=True).first()
    owners = list(ObjectDB.objects.filter(pk=owner)) if owner else []
    lock_characters(actor, *owners)


def claim(character, *, name=None):
    from .batch import period_key

    _visible(character)
    with transaction.atomic():
        require_open()
        lock_characters(character)
        room = ObjectDB.objects.select_for_update().filter(pk=place(character)).first()
        if not room or not room.tags.has("market", category="rp_economy"):
            raise EconomyError("You must be in a market room to claim a stall.")
        if Storefront.objects.filter(owner=character, kind="stall", status="open").count() >= get(
            "RP_ECONOMY_MAX_STALLS"
        ):
            raise EconomyError("You already hold the maximum number of stalls.")
        slots = room.attributes.get("rp_economy_stall_slots", default=get("RP_ECONOMY_STALL_SLOTS"))
        if type(slots) is not int or slots < 1:
            raise EconomyError("This market has no available slots.")
        occupied = set(
            Storefront.objects.filter(room=room, status="open").values_list("slot", flat=True)
        )
        slot = next((n for n in range(1, slots + 1) if n not in occupied), None)
        if slot is None:
            raise EconomyError("This market has no available slots.")
        name = _name(name or f"{character.key}'s stall")
        charge_fee("stall_claim", character, {"room_id": room.pk})
        holding = create_object(
            "evennia_economy.typeclasses.StallStock", key="Stall stock", location=None
        )
        store = Storefront.objects.create(
            owner=character,
            room=room,
            holding=holding,
            slot=slot,
            name=name,
            last_active=timezone.now(),
            upkeep_period=period_key(),
        )
        journal(
            "stall_claim", giver=character, note=f"Claimed stall #{store.pk} in room #{room.pk}."
        )
        return store


def _name(value):
    value = value.strip()
    if not value or len(value) > 120 or "\n" in value or "\r" in value:
        raise EconomyError("Stall names must be one line, from 1 to 120 characters.")
    return value


def edit(character, store_id, *, name=None, description=None):
    _visible(character)
    with transaction.atomic():
        require_open()
        _lock_owner(character, store_id)
        store = _store(character, store_id)
        if name is not None:
            store.name = _name(name)
        if description is not None:
            if len(description) > 10000:
                raise EconomyError("Stall descriptions may contain at most 10000 characters.")
            store.description = description
        store.save(update_fields=["name", "description"])
        return store


def _touch(store, now=None):
    store.last_active = now or timezone.now()
    store.save(update_fields=["last_active"])


def list_stock(character, store_id, spec, price):
    _visible(character)
    spec = assets.normalize(spec)
    quantity(price)
    if len(spec) != 1 or spec[0]["kind"] == "money":
        raise EconomyError("List one item or one resource lot at a time; money is the price.")
    with transaction.atomic():
        require_open()
        _lock_owner(character, store_id)
        store = _store(character, store_id)
        assets.check(character, store.holding if spec[0]["kind"] == "item" else character, spec)
        charge_fee("listing", character, {"storefront_id": store.pk, "assets": spec})
        listing = Listing.objects.create(storefront=store, assets=spec, price=price)
        asset = spec[0]
        if asset["kind"] == "item":
            assets.move(character, store.holding, spec, None)
        else:
            # The counter is held by the listing, not minted on a prop character.
            assets.providers(character)[asset["kind"]].debit(
                character, asset["key"], asset["quantity"], None
            )
        journal(
            "listing", giver=character, assets=spec, listing_id=listing.pk, note="Stock reserved."
        )
        _touch(store)
        return listing


def visible_listings(character, store):
    known = {"item", *assets.providers(character)}
    return [
        row
        for row in store.listings.filter(status="active").order_by("pk")
        if all(a["kind"] in known for a in row.assets)
    ]


def directory(character, search="", *, room=None):
    _visible(character)
    stores = (
        Storefront.objects.filter(status="open", owner__isnull=False, room__isnull=False)
        .select_related("room", "owner")
        .order_by("pk")
    )
    if room is not None:
        stores = stores.filter(room_id=getattr(room, "pk", room))
    result = []
    for store in stores:
        listings = visible_listings(character, store)
        keywords = []
        for row in listings:
            for asset in row.assets:
                if asset["kind"] == "item":
                    item = ObjectDB.objects.filter(pk=int(asset["key"])).first()
                    provider = getattr(item, "get_market_keywords", None)
                    if callable(provider):
                        keywords.extend(str(value) for value in (provider(character) or ()))
        text = " ".join(
            [
                store.name,
                store.description,
                *(assets.describe(row.assets) for row in listings),
                *keywords,
            ]
        )
        if not search or search.casefold() in text.casefold():
            result.append((store, listings))
    return result


def buy(buyer, listing_id):
    _visible(buyer)
    initial = Listing.objects.filter(pk=listing_id).select_related("storefront__owner").first()
    if not initial or not initial.storefront.owner:
        raise EconomyError("No such listing.")
    owner = initial.storefront.owner
    with transaction.atomic():
        require_open()
        lock_characters(buyer, owner)
        store = Storefront.objects.select_for_update().get(pk=initial.storefront_id)
        listing = Listing.objects.select_for_update().get(pk=listing_id)
        if listing.status != "active" or store.status != "open" or store.owner_id != owner.pk:
            raise EconomyError("That listing is no longer available.")
        if place(buyer) != store.room_id:
            raise EconomyError("Visit the stall's room to buy.")
        if buyer.pk == owner.pk or same_account(buyer, owner):
            raise EconomyError("You cannot buy from characters on the same account.")
        asset = listing.assets[0]
        available = assets.providers(owner, buyer)
        if asset["kind"] == "item":
            assets.check(store.holding, buyer, listing.assets, item_giver=owner)
        elif asset["kind"] not in available:
            raise EconomyError("That asset provider is unavailable.")
        _adjust(buyer, -listing.price)
        _adjust(owner, listing.price)
        charge_fee("sale", owner, {"listing_id": listing.pk, "price": listing.price})
        listing.status = "sold"
        listing.buyer_id = buyer.pk
        listing.completed = timezone.now()
        listing.save(update_fields=["status", "buyer_id", "completed"])
        if asset["kind"] == "item":
            assets.move(store.holding, buyer, listing.assets, None, item_giver=owner)
        else:
            available[asset["kind"]].credit(buyer, asset["key"], asset["quantity"], None)
        for giver, recipient, spec, amount in (
            (owner, buyer, listing.assets, 0),
            (
                buyer,
                owner,
                [{"kind": "money", "key": "", "quantity": listing.price}],
                listing.price,
            ),
        ):
            entry = journal(
                "exchange",
                giver=giver,
                recipient=recipient,
                amount=amount,
                assets=spec,
                listing_id=listing.pk,
                by=buyer,
            )
            flag_round_trips(entry)
        _touch(store)
        return listing


def _return(store, listing):
    asset = listing.assets[0]
    listing.status = "returned"
    listing.completed = timezone.now()
    listing.save(update_fields=["status", "completed"])
    if asset["kind"] == "item":
        # Returning stock must not depend on trade permissions or a new fee.
        assets.move(store.holding, store.owner, listing.assets, None)
    else:
        provider = assets.providers().get(asset["kind"])
        if provider is None:
            raise EconomyError("Restore the missing asset provider before returning this stock.")
        refund = getattr(provider, "refund", provider.credit)
        refund(store.owner, asset["key"], asset["quantity"], None)
    journal(
        "unlisting",
        recipient=store.owner,
        assets=listing.assets,
        listing_id=listing.pk,
        note="Reserved stock returned.",
    )


def unlist(character, listing_id):
    _visible(character)
    initial = Listing.objects.filter(pk=listing_id).first()
    if not initial:
        raise EconomyError("No such listing.")
    with transaction.atomic():
        require_open()
        _lock_owner(character, initial.storefront_id)
        store = _store(character, initial.storefront_id)
        listing = Listing.objects.select_for_update().get(pk=listing_id)
        if listing.status != "active":
            raise EconomyError("That listing is no longer available.")
        _return(store, listing)
        _touch(store)
        return listing


def close(character, store_id):
    """Staff may recover stock remotely, even during a freeze or while hidden."""
    if not conf.is_staff(character):
        _visible(character)
    with transaction.atomic():
        if not conf.is_staff(character):
            require_open()
        _lock_owner(character, store_id)
        store = _store(character, store_id, staff=True, here=not conf.is_staff(character))
        return _close(store, by=character)


def _close(store, *, by=None):
    for listing in store.listings.select_for_update().filter(status="active").order_by("pk"):
        _return(store, listing)
    store.status = "closed"
    store.save(update_fields=["status"])
    journal(
        "stall_close",
        recipient=store.owner,
        by=by,
        note=f"Closed stall #{store.pk}; stock returned.",
    )
    return store


def recover(store_id):
    """Trusted host reset API, never a player command. Return stock before deletion."""
    initial = Storefront.objects.select_related("owner").get(pk=store_id)
    if not initial.owner:
        raise EconomyError("No open storefront to recover.")
    with transaction.atomic():
        lock_characters(initial.owner)
        store = Storefront.objects.select_for_update().get(pk=store_id)
        if store.status != "open" or not store.owner:
            raise EconomyError("No open storefront to recover.")
        return _close(store)


def note_login(character):
    Storefront.objects.filter(owner=character, status="open").update(last_active=timezone.now())


def run_upkeep(period=None):
    """One upkeep boundary per current income period; never close for a shortfall."""
    from .batch import period_key
    from .review import flag_event

    if get("RP_ECONOMY_FROZEN"):
        return
    period = period or period_key()
    for initial in (
        Storefront.objects.filter(status="open", kind="stall", owner__isnull=False)
        .exclude(upkeep_period=period)
        .select_related("owner")
    ):
        try:
            with transaction.atomic():
                lock_characters(initial.owner)
                store = Storefront.objects.select_for_update().get(pk=initial.pk)
                if store.status != "open" or store.upkeep_period == period:
                    continue
                charge_fee(
                    "stall_upkeep", store.owner, {"storefront_id": store.pk, "period": period}
                )
                store.upkeep_period = period
                store.save(update_fields=["upkeep_period"])
        except EconomyError as exc:
            with transaction.atomic():
                flag_event(
                    "stall_upkeep",
                    f"upkeep:{initial.pk}:{period}",
                    "Economy: stall upkeep shortfall",
                    f"Stall #{initial.pk}, owner #{initial.owner_id}, period {period}: {exc}. Stock retained; review only.",
                )


def cap_contribution(sender, character, **kwargs):
    count = Storefront.objects.filter(owner=character, status="open", kind="stall").count()
    return {"stalls": {"money": count * get("RP_ECONOMY_STALL_CAP_RAISE")}}


def figures(sender, **kwargs):
    escrow = {}
    active = Listing.objects.filter(status="active")
    for row in active:
        for asset in row.assets:
            key = f"{asset['kind']}:{asset['key']}"
            escrow[key] = escrow.get(key, 0) + asset["quantity"]
    return {
        "stalls": {
            "open": Storefront.objects.filter(status="open").count(),
            "listings": active.count(),
            "escrow": escrow,
        }
    }
