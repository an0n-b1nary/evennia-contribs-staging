# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Opt-in, local basic-resource backstop. Purchases burn currency."""

from decimal import ROUND_CEILING, Decimal

from django.apps import apps
from django.db import transaction
from evennia.objects.models import ObjectDB

from evennia_links.guests import is_guest
from evennia_links.runtime import get

from . import conf
from .services import EconomyError, _adjust, journal, lock_characters, quantity, require_open
from .stalls import place


def catalog(actor):
    if is_guest(actor):
        return []
    if not conf.visible(actor) or not get("RP_ECONOMY_SYSTEM_SELLER"):
        return []
    if not apps.is_installed("evennia_rp_resources"):
        return []
    from evennia_rp_resources import conf as resources_conf

    if not resources_conf.visible(actor):
        return []
    prices = conf.hook("RP_ECONOMY_BASIC_PRICES") or {}
    if callable(prices):
        prices = prices()
    if not isinstance(prices, dict):
        raise EconomyError("Basic resource prices must be a mapping.")
    model = apps.get_model("evennia_rp_resources", "ResourceDefinition")
    result = []
    for resource in model.objects.filter(basic=True, in_trickle=True, archived=False).order_by(
        "key"
    ):
        base = prices.get(resource.key)
        if type(base) is not int or base <= 0:
            continue
        price = int(
            (Decimal(base) * Decimal(str(get("RP_ECONOMY_SELLER_PREMIUM")))).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
        quantity(price)
        result.append((resource, price))
    return result


def local_catalog(actor):
    room = ObjectDB.objects.filter(pk=place(actor)).first()
    if not room or not room.tags.has("system_seller", category="rp_economy"):
        raise EconomyError("Visit a system seller to browse or buy basic resources.")
    return catalog(actor)


@transaction.atomic
def buy(actor, key, amount):
    quantity(amount)
    require_open()
    lock_characters(actor)
    choices = {resource.key: (resource, price) for resource, price in local_catalog(actor)}
    if key not in choices:
        raise EconomyError("That resource is not available from the system seller.")
    from evennia_rp_resources.services import grant

    resource, price = choices[key]
    # Lock and recheck the catalogue row before minting; never sell rarity.
    resource = type(resource).objects.select_for_update().get(pk=resource.pk)
    if not resource.basic or not resource.in_trickle or resource.archived:
        raise EconomyError("That resource is no longer available.")
    total = quantity(price * amount)
    _adjust(actor, -total)
    entry = journal(
        "system_purchase",
        giver=actor,
        amount=total,
        assets=[{"kind": "resource", "key": key, "quantity": amount}],
        by=actor,
        note="System seller; currency removed from circulation.",
    )
    grant(
        actor,
        key,
        amount,
        "exchange",
        details={"system_purchase": entry.pk},
        by=actor,
        note="System seller purchase.",
    )
    return total
