# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Exact consent proposals and an Economy service asset, never editable base prose."""

from datetime import timedelta
from importlib import import_module

from django.apps import apps
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from evennia.objects.models import ObjectDB
from evennia.objects.objects import DefaultCharacter

from evennia_links.characters import account_ids
from evennia_links.guests import is_guest
from evennia_links.rooms import is_live, lock_state, owner_of
from evennia_links.runtime import get

from . import conf, services
from .behaviours import Behaviour, behaviour
from .errors import CraftingError
from .models import CraftRecord, FixtureInstallation, ModificationLayer, ModificationOffer
from .wave_two import line


class Modifier(Behaviour):
    role = "service"
    fields = ("line", "layer_id")
    kind = "aura"
    character_target = False

    def available(self):
        return apps.is_installed("evennia_economy") and hasattr(
            import_module("evennia_economy.assets"), "lock_provider_context"
        )

    def validate(self, config):
        config = super().validate(config)
        layer_id = config.get("layer_id")
        if layer_id is not None and not conf.positive(layer_id):
            raise CraftingError("Select a layer by its positive number.")
        if self.kind == "undo":
            if layer_id is None or config.get("line"):
                raise CraftingError("Undoing needs one selected layer and no replacement prose.")
            return {"layer_id": layer_id}
        return {"line": line(config.get("line", ""), "Modification"), "layer_id": layer_id}


class Mark(Modifier):
    kind = "mark"
    character_target = True


class Dye(Modifier):
    kind = "dye"


class Engrave(Modifier):
    kind = "engraving"


class Undo(Modifier):
    kind = "undo"


def _owner(target):
    if isinstance(target, DefaultCharacter):
        return target
    placement = FixtureInstallation.objects.filter(craft__item_id=target.pk, active=True).first()
    if placement:
        room = ObjectDB.objects.filter(pk=placement.room_id).first()
        if room and target.location == room and is_live(room):
            return owner_of(room)
        return None
    holder = target.location
    return holder if isinstance(holder, DefaultCharacter) else None


def _snapshot(target):
    # Read relevant state afresh: Evennia instances and Attribute handlers are cached.
    from evennia.utils.dbserialize import deserialize

    target.attributes.reset_cache()
    return {
        "object": list(
            ObjectDB.objects.filter(pk=target.pk)
            .values_list("db_key", "db_location_id", "db_typeclass_path", "db_lock_storage")
            .get()
        ),
        "base": {
            key: deserialize(target.attributes.get(key))
            for key in ("desc", "worn_line", "aura_line", "slot", "requirement_data", "sealed")
        },
        "craft": list(CraftRecord.objects.filter(item_id=target.pk).values_list("pk", flat=True)),
        "layers": list(
            ModificationLayer.objects.filter(target_id=target.pk)
            .order_by("pk")
            .values("id", "kind", "text", "hidden", "removed_by_id")
        ),
    }


def _lock(maker, customer, target):
    from evennia_economy.services import lock_characters, same_account

    # Match fixture/property services: host ownership before characters/items.
    placement = FixtureInstallation.objects.filter(craft__item_id=target.pk, active=True).first()
    if placement:
        room = ObjectDB.objects.filter(pk=placement.room_id).first()
        if room:
            lock_state(room)
    lock_characters(maker, customer)
    target = ObjectDB.objects.select_for_update().filter(pk=target.pk).first()
    if target is None:
        raise CraftingError("The target no longer exists.")
    for actor in (maker, customer):
        services._require(actor, wave_three=True)
        if is_guest(actor):
            raise CraftingError("Guests cannot request crafting services.")
    if maker != customer and same_account(maker, customer):
        raise CraftingError("Services cannot be exchanged between characters on the same account.")
    positions = dict(
        ObjectDB.objects.filter(pk__in=[maker.pk, customer.pk]).values_list("pk", "db_location_id")
    )
    room_id = positions.get(maker.pk)
    if room_id is None or positions.get(customer.pk) != room_id:
        raise CraftingError("Both characters must be in the same room.")
    if _owner(target) != customer:
        raise CraftingError("The consenting customer must currently own the target.")
    if target != customer and target.location not in (customer, customer.location):
        raise CraftingError("The target must be carried, worn or installed here.")
    return target, room_id


def _terms(maker, niche_key, modifier_key, configuration, target):
    definition = services.niche(niche_key)
    implementation = behaviour(modifier_key)
    if implementation.role != "service" or modifier_key not in definition.behaviours:
        raise CraftingError("That niche doesn't grant this Modifier service.")
    workshop = services._workshop(maker)
    if not services.active_unlocks(workshop).filter(niche=definition).exists():
        raise CraftingError("Unlock that niche in your Workshop first.")
    config = implementation.validate(configuration)
    if implementation.kind != "undo" and (
        isinstance(target, DefaultCharacter) != implementation.character_target
    ):
        raise CraftingError("That Modifier cannot be applied to this kind of target.")
    if config.get("layer_id"):
        layer = ModificationLayer.objects.filter(
            pk=config["layer_id"], target_id=target.pk, removed_by__isnull=True
        ).first()
        if layer is None or (implementation.kind != "undo" and layer.kind != implementation.kind):
            raise CraftingError("Select an active, compatible layer on this target.")
    elif (
        implementation.kind != "mark"
        and ModificationLayer.objects.filter(
            target_id=target.pk, kind=implementation.kind, removed_by__isnull=True
        ).exists()
    ):
        raise CraftingError("Name the existing layer to replace it explicitly.")
    costs = implementation.cost(modifier_key, config)
    return definition, implementation, config, costs


def _payment(modifier_key, selected, costs, categories):
    selected = services.payment(selected, costs, categories)
    keys = getattr(settings, "RP_CRAFTING_MODIFIER_RESOURCE_KEYS", {}).get(modifier_key)
    if keys is not None and (
        not isinstance(keys, (list, tuple))
        or not keys
        or any(not isinstance(key, str) for key in keys)
        or set(selected) - set(keys)
    ):
        raise CraftingError("This Modifier requires its configured resource keys.")
    return selected


def _trade_fees(row, maker, customer):
    from evennia_economy.services import fee

    if row.economy_offer_id is None:
        return {}
    return {
        "maker": fee(
            "trade",
            maker,
            {
                "offer_id": row.economy_offer_id,
                "assets": [{"kind": "service", "key": str(row.pk), "quantity": 1}],
            },
        ),
        "customer": fee(
            "trade",
            customer,
            {
                "offer_id": row.economy_offer_id,
                "assets": [{"kind": "money", "key": "", "quantity": row.commission}],
            },
        )
        if row.commission
        else 0,
    }


@transaction.atomic
def propose(
    maker, customer, target, niche_key, modifier_key, configuration, selected, *, commission=0
):
    if not apps.is_installed("evennia_economy"):
        raise CraftingError("Modifier services require Economy.")
    from evennia_economy.exchange import create_offer
    from evennia_economy.services import fee

    if not conf.nonnegative(commission) or (maker == customer and commission):
        raise CraftingError("Use a nonnegative commission; self services have no commission.")
    target, room_id = _lock(maker, customer, target)
    definition, _, config, costs = _terms(maker, niche_key, modifier_key, configuration, target)
    selected = _payment(modifier_key, selected, costs, definition.input_categories)
    row = ModificationOffer.objects.create(
        maker_id=maker.pk,
        customer_id=customer.pk,
        target_id=target.pk,
        room_id=room_id,
        niche=definition,
        modifier=modifier_key,
        configuration=config,
        snapshot={
            "target": _snapshot(target),
            "trade_fees": {},
            "maker_name": maker.key,
            "maker_accounts": account_ids(maker),
            "customer_name": customer.key,
            "niche_name": definition.name,
        },
        resources=selected,
        category_cost=costs,
        commission=commission,
        craft_fee=fee("craft", maker, {"behaviour": modifier_key, "target_id": target.pk}),
        expires_at=timezone.now() + timedelta(seconds=get("RP_ECONOMY_OFFER_TIMEOUT")),
    )
    if maker != customer:
        offer = create_offer(
            maker,
            customer,
            [{"kind": "service", "key": str(row.pk), "quantity": 1}],
            [{"kind": "money", "key": "", "quantity": commission}] if commission else [],
        )
        row.economy_offer_id = offer.pk
        row.snapshot["trade_fees"] = _trade_fees(row, maker, customer)
        row.save(update_fields=["economy_offer_id", "snapshot"])
    return row


def _validate(row):
    from evennia_economy.services import fee

    maker = ObjectDB.objects.filter(pk=row.maker_id).first()
    customer = ObjectDB.objects.filter(pk=row.customer_id).first()
    target = ObjectDB.objects.filter(pk=row.target_id).first()
    if not maker or not customer or not target:
        raise CraftingError("A service participant or target no longer exists.")
    target, room_id = _lock(maker, customer, target)
    row = ModificationOffer.objects.select_for_update().get(pk=row.pk)
    if row.applied_at or row.cancelled_at or row.expires_at <= timezone.now():
        raise CraftingError("That service is no longer open.")
    definition, implementation, config, costs = _terms(
        maker, row.niche.key, row.modifier, row.configuration, target
    )
    if (
        room_id != row.room_id
        or _snapshot(target) != row.snapshot["target"]
        or costs != row.category_cost
    ):
        raise CraftingError("The target or terms changed; request a new offer.")
    _payment(row.modifier, row.resources, costs, definition.input_categories)
    current_fee = fee("craft", maker, {"behaviour": row.modifier, "target_id": target.pk})
    if current_fee != row.craft_fee:
        raise CraftingError("The craft fee changed; request a new offer.")
    if _trade_fees(row, maker, customer) != row.snapshot["trade_fees"]:
        raise CraftingError("The trade fee changed; request a new offer.")
    return row, maker, customer, target, implementation, config


def _apply(row):
    from evennia_economy.services import charge_fee

    row, maker, _, target, implementation, config = _validate(row)
    services._spend(maker, row.resources, f"Modifier service #{row.pk}: {row.modifier}")
    charged = charge_fee("craft", maker, {"behaviour": row.modifier, "target_id": target.pk})
    if charged != row.craft_fee:
        raise CraftingError("The craft fee changed; request a new offer.")
    if config.get("layer_id"):
        updated = ModificationLayer.objects.filter(
            pk=config["layer_id"], target_id=target.pk, removed_by__isnull=True
        ).update(removed_by=row)
        if not updated:
            raise CraftingError("The layer changed; request a new offer.")
    if implementation.kind != "undo":
        ModificationLayer.objects.create(
            target_id=target.pk,
            service=row,
            kind=implementation.kind,
            text=config["line"],
            maker_id=maker.pk,
            hallmark=f"{implementation.kind.title()} by {maker.key} ({row.niche.name})",
        )
    row.applied_at = timezone.now()
    row.save(update_fields=["applied_at"])
    return row


def accept(customer, service_id):
    if not apps.is_installed("evennia_economy"):
        raise CraftingError("Modifier services require Economy.")
    row = ModificationOffer.objects.filter(pk=service_id, customer_id=customer.pk).first()
    if row is None:
        raise CraftingError("No such service addressed to you.")
    if row.economy_offer_id:
        from evennia_economy.exchange import accept_offer

        accept_offer(customer, row.economy_offer_id)
        row.refresh_from_db()
        return row
    # Economy owns its external acceptance transaction. An enclosing read
    # transaction here would prevent its SQLite expiry write from waiting for
    # a competing acceptance to commit. Self services serialize before reading.
    with transaction.atomic():
        ObjectDB.objects.filter(pk=row.maker_id).update(db_key=F("db_key"))
        return _apply(row)


def cancel(actor, service_id):
    row = ModificationOffer.objects.filter(pk=service_id).first()
    if row is None or actor.pk not in (row.maker_id, row.customer_id) or row.applied_at:
        raise CraftingError("No open service belonging to you.")
    with transaction.atomic():
        # Match acceptance's order: Economy offer before service row. Start
        # with a write so SQLite can wait without holding a read transaction.
        if row.economy_offer_id and apps.is_installed("evennia_economy"):
            from evennia_economy.exchange import cancel_offer

            cancel_offer(actor, row.economy_offer_id)
        else:
            ObjectDB.objects.filter(pk=row.maker_id).update(db_key=F("db_key"))
        row = ModificationOffer.objects.select_for_update().get(pk=row.pk)
        if row.applied_at:
            raise CraftingError("That service was already accepted.")
        row.cancelled_at = timezone.now()
        row.save(update_fields=["cancelled_at"])


@transaction.atomic
def set_hidden(actor, layer_id, hidden):
    row = ModificationLayer.objects.filter(pk=layer_id).first()
    target = ObjectDB.objects.filter(pk=row.target_id).first() if row else None
    if target:
        placement = FixtureInstallation.objects.filter(
            craft__item_id=target.pk, active=True
        ).first()
        if placement:
            room = ObjectDB.objects.filter(pk=placement.room_id).first()
            if room:
                lock_state(room)
        target = ObjectDB.objects.select_for_update().get(pk=target.pk)
    if not target or _owner(target) != actor:
        raise CraftingError("Only the current owner may hide or show this layer.")
    ModificationLayer.objects.filter(pk=row.pk).update(hidden=bool(hidden))


def display(target):
    if not get("RP_CRAFTING_REVEALED") or not get("RP_CRAFTING_WAVE_THREE_REVEALED"):
        return ""
    return "\n".join(
        f"{row.kind.title()}: {row.text}\n  Hallmark (OOC): {row.hallmark}"
        for row in ModificationLayer.objects.filter(
            target_id=target.pk, hidden=False, removed_by__isnull=True
        ).order_by("pk")
    )


class ServiceAsset:
    """One nontransferable proposal per offer; cannot be gifted, listed or replayed."""

    def available(self, character):
        return Modifier().available() and conf.wave_three_visible(character)

    def lock_context(self, giver, recipient, key, quantity):
        row = ModificationOffer.objects.filter(pk=int(key)).first() if key.isdecimal() else None
        if row:
            placement = FixtureInstallation.objects.filter(
                craft__item_id=row.target_id, active=True
            ).first()
            if placement:
                room = ObjectDB.objects.filter(pk=placement.room_id).first()
                if room:
                    lock_state(room)

    def describe(self, key):
        row = ModificationOffer.objects.filter(pk=int(key)).first() if key.isdecimal() else None
        if not row:
            return "unavailable service"
        if apps.is_installed("evennia_economy"):
            from evennia_economy.conf import currency
        else:
            currency = str

        name = ObjectDB.objects.filter(pk=row.target_id).values_list("db_key", flat=True).first()
        selected = row.configuration.get("layer_id")
        change = (
            f"remove layer #{selected}"
            if row.modifier == "modifier_undo"
            else (
                (f"replace layer #{selected}: " if selected else "add layer: ")
                + row.configuration["line"]
            )
        )
        materials = ", ".join(f"{quantity} {key}" for key, quantity in row.resources.items())
        fees = row.snapshot["trade_fees"]
        return (
            f"service #{row.pk}: {name or 'deleted target'} (#{row.target_id}); {change}; "
            f"materials {materials} supplied by maker; maker craft fee {currency(row.craft_fee)}; "
            f"customer payment {currency(row.commission)}; maker trade fee {currency(fees.get('maker', 0))}; "
            f"customer trade fee {currency(fees.get('customer', 0))}"
        )

    def check(self, giver, recipient, key, quantity):
        if quantity != 1 or not key.isdecimal():
            raise CraftingError("A service is one exact proposal.")
        row = ModificationOffer.objects.filter(pk=int(key)).first()
        if row is None or row.maker_id != giver.pk or row.customer_id != recipient.pk:
            raise CraftingError("That service does not belong to this exchange.")
        _validate(row)

    def debit(self, character, key, quantity, exchange_id):
        row = ModificationOffer.objects.get(pk=int(key))
        if (
            quantity != 1
            or exchange_id is None
            or row.economy_offer_id is None
            or row.maker_id != character.pk
            or row.economy_offer_id != exchange_id
        ):
            raise CraftingError(
                "Accept the original service offer; services cannot be transferred."
            )
        _apply(row)

    def credit(self, character, key, quantity, exchange_id):
        row = ModificationOffer.objects.get(pk=int(key))
        if (
            row.customer_id != character.pk
            or not row.applied_at
            or row.economy_offer_id != exchange_id
        ):
            raise CraftingError("That service cannot be transferred.")


def service_assets(sender, **kwargs):
    return {"service": ServiceAsset()}
