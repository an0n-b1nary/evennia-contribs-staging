# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Atomic unlocks and crafts: resource/money logs commit with the resulting item."""

from collections import Counter

from django.apps import apps
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from evennia.objects.models import ObjectDB
from evennia_rp_resources import services as resources

from evennia_links.characters import account_ids
from evennia_links.runtime import get

from . import conf
from .behaviours import registry, text
from .catalog import validate_niche
from .composition import prepare
from .errors import CraftingError
from .models import CraftRecord, NicheDefinition, NicheUnlock, Workshop, WorkshopInvestment


def _require(actor, *, spending=True):
    if not conf.visible(actor):
        raise CraftingError("Crafting is unavailable.")
    if get("RP_CRAFTING_FROZEN"):
        raise CraftingError("Crafting is paused for the moment.")
    if spending and apps.is_installed("evennia_economy"):
        from evennia_economy.services import EconomyError, require_open

        try:
            require_open()
        except EconomyError as exc:
            raise CraftingError(str(exc)) from None


def active_unlocks(workshop):
    return workshop.unlocks.filter(abandoned_at__isnull=True)


def _workshop(actor):
    # Same first lock as economy and resources. Parallel unlocks serialize
    # before counting active slots or creating the one-to-one Workshop.
    ObjectDB.objects.select_for_update().get(pk=actor.pk)
    return Workshop.objects.get_or_create(character=actor)[0]


def niche(key):
    value = NicheDefinition.objects.filter(key=key, archived=False).first()
    if value is None:
        raise CraftingError("Unknown or archived niche.")
    return value


def unlock_cost(definition, active_count):
    validate_niche(definition)
    factor = conf.multiplier(active_count + 1)
    money = definition.unlock_money * factor if apps.is_installed("evennia_economy") else 0
    costs = {key: quantity * factor for key, quantity in definition.unlock_resources.items()}
    if money > conf.MAX_AMOUNT or sum(costs.values()) > conf.MAX_AMOUNT:
        raise CraftingError("Unlock cost exceeds the supported range.")
    return {"money": money, "resources": costs}


def payment(spec, costs, allowed):
    """Player-selected resources must satisfy each category exactly, not just a total."""
    if (
        not isinstance(spec, dict)
        or any(
            not isinstance(key, str) or not conf.positive(quantity)
            for key, quantity in spec.items()
        )
        or sum(spec.values()) > conf.MAX_AMOUNT
    ):
        raise CraftingError("Select resource keys with positive whole quantities.")
    totals = Counter()
    for key, quantity in sorted(spec.items()):
        try:
            resource = resources.definition(key)
        except resources.ResourceError as exc:
            raise CraftingError(str(exc)) from None
        if resource.category not in allowed:
            raise CraftingError(f"{resource.name} is not an input for this niche.")
        totals[resource.category] += quantity
    if dict(totals) != costs:
        expected = ", ".join(f"{quantity} {key}" for key, quantity in costs.items())
        raise CraftingError(f"Choose exactly these category totals: {expected}.")
    return dict(spec)


def _spend(actor, spec, note):
    for key, quantity in sorted(spec.items()):
        try:
            resources.spend(actor, key, quantity, note, source="craft")
        except resources.ResourceError as exc:
            raise CraftingError(str(exc)) from None


@transaction.atomic
def unlock(actor, key, selected):
    _require(actor)
    workshop = _workshop(actor)
    definition = NicheDefinition.objects.select_for_update().get(pk=niche(key).pk)
    if definition.archived:
        raise CraftingError("Unknown or archived niche.")
    count = active_unlocks(workshop).count()
    if active_unlocks(workshop).filter(niche=definition).exists():
        raise CraftingError("You already hold that niche.")
    if count >= get("RP_CRAFTING_NICHE_CAP"):
        raise CraftingError("Your Workshop is at its niche cap. Abandon a niche first.")
    cost = unlock_cost(definition, count)
    implementations = registry()
    if not any(implementations[key].available() for key in definition.behaviours):
        raise CraftingError("This niche's behaviours are unavailable.")
    selected = payment(selected, cost["resources"], definition.input_categories)
    if cost["money"]:
        from evennia_economy.services import EconomyError, debit

        try:
            debit(actor, cost["money"], kind="workshop", note=f"Unlock {definition.key}")
        except EconomyError as exc:
            raise CraftingError(str(exc)) from None
    _spend(actor, selected, f"Workshop investment: {definition.key}")
    if not Workshop.objects.filter(
        pk=workshop.pk, invested_money__lte=conf.MAX_AMOUNT - cost["money"]
    ).update(invested_money=F("invested_money") + cost["money"]):
        raise CraftingError("Workshop investment exceeds the supported range.")
    for key, quantity in selected.items():
        row, _ = WorkshopInvestment.objects.get_or_create(
            workshop=workshop, resource_key=key, defaults={"quantity": 0}
        )
        if not WorkshopInvestment.objects.filter(
            pk=row.pk, quantity__lte=conf.MAX_AMOUNT - quantity
        ).update(quantity=F("quantity") + quantity):
            raise CraftingError("Workshop investment exceeds the supported range.")
    return NicheUnlock.objects.create(
        workshop=workshop,
        niche=definition,
        position=count + 1,
        money_paid=cost["money"],
        resources_paid=selected,
    )


@transaction.atomic
def abandon(actor, key):
    _require(actor, spending=False)
    workshop = _workshop(actor)
    held = active_unlocks(workshop).filter(niche__key=key).first()
    if held is None:
        raise CraftingError("You don't hold that niche.")
    held.abandoned_at = timezone.now()
    held.save(update_fields=["abandoned_at"])
    return held


def craft_cost(actor, key, behaviour_key, configuration, *, include_fee=True, verbs=None):
    definition, composition = prepare(key, behaviour_key, configuration, verbs)
    money = 0
    if include_fee and apps.is_installed("evennia_economy"):
        from evennia_economy.services import fee

        money = fee("craft", actor, composition.context(key))
    return (
        definition,
        composition,
        composition.configuration,
        {
            "resources": composition.resources,
            "money": money,
        },
    )


@transaction.atomic
def craft(actor, key, behaviour_key, name, description, configuration, selected, *, verbs=None):
    _require(actor)
    workshop = _workshop(actor)
    # Catalogue locks are ordered independently of a draft's component order.
    # The actor lock above serializes concurrent unlock/abandon/craft calls.
    _, initial = prepare(key, behaviour_key, configuration, verbs)
    list(
        NicheDefinition.objects.select_for_update()
        .filter(pk__in=[definition.pk for definition in initial.definitions])
        .order_by("pk")
    )
    definition, implementation, config, cost = craft_cost(
        actor, key, behaviour_key, configuration, include_fee=False, verbs=verbs
    )
    if active_unlocks(workshop).filter(niche__in=implementation.definitions).count() != len(
        implementation.definitions
    ):
        raise CraftingError("Unlock that niche in your Workshop first.")
    name = text(name, "Item name", 80, required=True)
    description = text(description, "Description", 4000, required=True)
    selected = payment(selected, cost["resources"], implementation.input_categories)
    _spend(actor, selected, f"Craft: {definition.key}/{behaviour_key}")
    if apps.is_installed("evennia_economy"):
        from evennia_economy.services import EconomyError, charge_fee

        try:
            cost["money"] = charge_fee(
                "craft",
                actor,
                implementation.context(key),
            )
        except EconomyError as exc:
            raise CraftingError(str(exc)) from None
    item = implementation.create(actor, name, description, config)
    if item is None or not item.pk or item.location != actor:
        raise CraftingError("The behaviour did not produce an item in your hands.")
    item.tags.add(str(actor.pk), category="rp_crafting_maker")
    record = CraftRecord.objects.create(
        crafter_id=actor.pk,
        crafter_name=actor.key,
        crafter_accounts=account_ids(actor),
        niche=definition,
        niche_name=definition.name,
        behaviour=implementation.lifecycle_key,
        verbs=implementation.verbs,
        contributors=implementation.contributors,
        item_id=item.pk,
        resources_spent=selected,
        money_spent=cost["money"],
        prose={"name": name, "description": description, "configuration": config},
        hallmark=f"Made by {actor.key} ({', '.join(row['name'] for row in implementation.contributors)})",
    )
    Workshop.objects.filter(pk=workshop.pk).update(last_craft=record.created)
    return item
