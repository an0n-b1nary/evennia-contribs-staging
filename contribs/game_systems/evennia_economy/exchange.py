# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Unreserved offers; acceptance rechecks and swaps both legs atomically."""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from evennia.objects.models import ObjectDB

from evennia_links.runtime import get

from . import assets
from .models import Offer
from .review import flag_round_trips
from .services import EconomyError, charge_fee, journal, lock_characters, require_open, same_account


def expire_offers():
    now = timezone.now()
    Offer.objects.filter(status="open", expires__lte=now).update(status="expired")


def on_location_saved(sender, instance, update_fields=None, **kwargs):
    """Evennia has no generic move signal. Object location saves cover teleports too."""
    if not isinstance(instance, ObjectDB) or (
        update_fields is not None and "db_location" not in update_fields
    ):
        return
    Offer.objects.filter(
        Q(giver_id=instance.pk) | Q(recipient_id=instance.pk), status="open"
    ).exclude(room_id=instance.db_location_id).update(status="expired")


def _parties(giver, recipient):
    if giver.pk == recipient.pk or same_account(giver, recipient):
        raise EconomyError("You cannot exchange assets between characters on the same account.")
    places = dict(
        ObjectDB.objects.filter(pk__in=[giver.pk, recipient.pk]).values_list("pk", "db_location_id")
    )
    room_id = places.get(giver.pk)
    if room_id is None or places.get(recipient.pk) != room_id:
        raise EconomyError("Both characters must be in the same room.")
    return room_id


def create_offer(giver, recipient, give, want=None, *, secret=False):
    give, want = assets.normalize(give), assets.normalize(want or [])
    if not give:
        raise EconomyError("An offer must give at least one asset.")
    with transaction.atomic():
        require_open()
        lock_characters(giver, recipient)
        room_id = _parties(giver, recipient)
        expire_offers()
        if Offer.objects.filter(giver=giver, status="open").count() >= get(
            "RP_ECONOMY_MAX_OPEN_OFFERS"
        ):
            raise EconomyError("You have too many open offers; cancel one first.")
        assets.check(giver, recipient, give)
        # Requested stock need not be available until acceptance, but unknown
        # kinds must never be persisted as a valid offer.
        known = {"money", "item", *assets.providers()}
        if any(asset["kind"] not in known for asset in want):
            raise EconomyError("Unknown requested asset provider.")
        if {a["key"] for a in give if a["kind"] == "item"} & {
            a["key"] for a in want if a["kind"] == "item"
        }:
            raise EconomyError("An item cannot appear on both sides of an offer.")
        return Offer.objects.create(
            giver=giver,
            recipient=recipient,
            room_id=room_id,
            give=give,
            want=want,
            secret=bool(secret),
            expires=timezone.now() + timedelta(seconds=get("RP_ECONOMY_OFFER_TIMEOUT")),
        )


def _announce(offer, giver, recipient, secret):
    giver.msg(f"Trade #{offer.pk} completed with {recipient.key}.")
    recipient.msg(f"Trade #{offer.pk} completed with {giver.key}.")
    if not (offer.secret or secret):
        room = ObjectDB.objects.filter(pk=offer.room_id).first()
        if room:
            room.msg_contents(
                f"{giver.key} and {recipient.key} complete a trade.", exclude=[giver, recipient]
            )


def accept_offer(recipient, offer_id, *, secret=False):
    expire_offers()
    initial = Offer.objects.filter(pk=offer_id).first()
    if not initial or initial.recipient_id != recipient.pk:
        raise EconomyError("No such offer addressed to you.")
    with transaction.atomic():
        require_open()
        # Same lock order as creation/currency/resources, then the offer row.
        lock_characters(initial.giver, recipient)
        offer = Offer.objects.select_for_update().get(pk=offer_id)
        if offer.status != "open" or offer.expires <= timezone.now():
            raise EconomyError("That offer is no longer open.")
        giver = offer.giver
        if _parties(giver, recipient) != offer.room_id:
            raise EconomyError("The offer's room has changed.")
        # Lock all item rows in one order before calling pre-give hooks.
        item_ids = sorted({int(a["key"]) for a in offer.give + offer.want if a["kind"] == "item"})
        list(ObjectDB.objects.select_for_update().filter(pk__in=item_ids).order_by("pk"))
        assets.check(giver, recipient, offer.give)
        assets.check(recipient, giver, offer.want)
        for actor, spec in ((giver, offer.give), (recipient, offer.want)):
            if spec:
                charge_fee(
                    "trade", actor, {"offer_id": offer.pk, "assets": spec}, exchange_id=offer.pk
                )
        assets.move(giver, recipient, offer.give, offer.pk)
        assets.move(recipient, giver, offer.want, offer.pk)
        for first, second, spec in ((giver, recipient, offer.give), (recipient, giver, offer.want)):
            if spec:
                entry = journal(
                    "exchange",
                    giver=first,
                    recipient=second,
                    amount=sum(a["quantity"] for a in spec if a["kind"] == "money"),
                    assets=spec,
                    exchange_id=offer.pk,
                    by=recipient,
                )
                flag_round_trips(entry)
        offer.status = "accepted"
        offer.save(update_fields=["status"])
        transaction.on_commit(lambda: _announce(offer, giver, recipient, secret))
        return offer


def cancel_offer(character, offer_id):
    # Cancellation is a read/administrative operation and remains available frozen.
    updated = Offer.objects.filter(
        Q(giver=character) | Q(recipient=character), pk=offer_id, status="open"
    ).update(status="cancelled")
    if not updated:
        raise EconomyError("No open offer belonging to you.")
