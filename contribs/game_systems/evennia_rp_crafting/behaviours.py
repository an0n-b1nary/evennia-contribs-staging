# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Code owns behaviours; niche data only grants access to their stable keys."""

from collections import Counter

from django.apps import apps
from django.conf import settings
from django.core.validators import validate_slug
from evennia.utils.create import create_object

from evennia_links.collect import resolve_dotted

from . import conf
from .catalog import category_cost
from .errors import CraftingError


def text(value, label, limit, *, required=False):
    if not isinstance(value, str):
        raise CraftingError(f"{label} must be text.")
    value = value.strip()
    if len(value) > limit or (required and not value):
        raise CraftingError(f"{label} must contain {'1' if required else '0'}-{limit} characters.")
    return value


def registry():
    result = {}
    for key, value in getattr(settings, "RP_CRAFTING_BEHAVIOURS", conf.DEFAULT_BEHAVIOURS).items():
        validate_slug(key)
        factory = resolve_dotted(value) if isinstance(value, str) else value
        result[key] = factory()
    return result


def behaviour(key):
    result = registry().get(key)
    if result is None or not result.available():
        raise CraftingError("That crafting behaviour is unavailable.")
    return result


class Behaviour:
    fields = ()
    typeclass = ""
    typeclass_setting = ""

    def available(self):
        return True

    def validate(self, config):
        if not isinstance(config, dict) or set(config) - set(self.fields):
            raise CraftingError("Unknown configuration fields for this behaviour.")
        return dict(config)

    def cost(self, key, config):
        rules = getattr(settings, "RP_CRAFTING_COSTS", conf.DEFAULT_COSTS).get(key)
        if not isinstance(rules, dict) or "base" not in rules:
            raise CraftingError("This behaviour has no configured cost rule.")
        total = Counter(category_cost(rules["base"]))
        for feature, costs in rules.items():
            if feature != "base" and config.get(feature):
                total.update(category_cost(costs))
        if not total or sum(total.values()) > conf.MAX_AMOUNT:
            raise CraftingError("Craft costs must include resources within the supported range.")
        return dict(total)

    def create(self, actor, name, description, config):
        item = create_object(
            getattr(settings, self.typeclass_setting, self.typeclass),
            key=name,
            location=actor,
            home=actor,
        )
        item.db.desc = description
        return item


class Readable(Behaviour):
    fields = ("text",)
    typeclass = "evennia_rp_crafting.typeclasses.Readable"
    typeclass_setting = "RP_CRAFTING_READABLE_TYPECLASS"

    def validate(self, config):
        config = super().validate(config)
        return {"text": text(config.get("text", ""), "Readable text", 12000, required=True)}


class Wearable(Behaviour):
    fields = ("worn_line", "aura_line", "slot", "requirements")
    typeclass = "evennia_rp_crafting.wearables.Wearable"
    typeclass_setting = "RP_CRAFTING_WEARABLE_TYPECLASS"

    def available(self):
        return apps.is_installed("evennia_rp_equipment")

    def validate(self, config):
        config = super().validate(config)
        from evennia_rp_equipment.requirements import RequirementError, parse

        requirements = config.get("requirements", [])
        if not isinstance(requirements, list) or len(requirements) > 20:
            raise CraftingError("Requirements must be a list of at most 20 rules.")
        try:
            parsed = [
                parse(text(value, "Requirement", 200, required=True)) for value in requirements
            ]
        except RequirementError as exc:
            raise CraftingError(str(exc)) from None
        identities = [(rule.kind, rule.stat, rule.ability, rule.tag) for rule in parsed]
        if len(set(identities)) != len(identities):
            raise CraftingError("Don't repeat a requirement.")
        return {
            "worn_line": text(config.get("worn_line", ""), "Worn line", 200),
            "aura_line": text(config.get("aura_line", ""), "Aura line", 200),
            "slot": text(config.get("slot", ""), "Slot", 30).lower(),
            "requirements": [rule.to_dict() for rule in parsed],
        }

    def create(self, actor, name, description, config):
        item = super().create(actor, name, description, config)
        item.maker_id = actor.pk
        item.maker_name = actor.key
        item.sealed = False
        item.slot = config["slot"]
        item.worn_line = config["worn_line"]
        item.requirement_data = config["requirements"]
        # Crafted stock deliberately has no plain-gear maker tag: its costs,
        # rather than RP_EQUIPMENT_ITEM_CAP, bound production.
        return item


class Consumable(Behaviour):
    fields = ("beats",)
    typeclass = "evennia_rp_crafting.typeclasses.Consumable"
    typeclass_setting = "RP_CRAFTING_CONSUMABLE_TYPECLASS"

    def validate(self, config):
        config = super().validate(config)
        beats = config.get("beats", [])
        if not isinstance(beats, list) or not 1 <= len(beats) <= 3:
            raise CraftingError("Choose 1-3 EVENT beats.")
        result = []
        for beat in beats:
            beat = text(beat, "EVENT beat", 400, required=True)
            if not beat.isprintable() or "|" in beat or "<EVENT>" in beat:
                raise CraftingError("EVENT beats must be plain, single-line prose.")
            result.append(beat)
        return {"beats": result}

    def cost(self, key, config):
        rules = getattr(settings, "RP_CRAFTING_COSTS", conf.DEFAULT_COSTS).get(key, {})
        if "extra_beat" not in rules:
            raise CraftingError("This behaviour has no extra-beat cost rule.")
        total = Counter(super().cost(key, config))
        for _ in config["beats"][1:]:
            total.update(category_cost(rules["extra_beat"]))
        if sum(total.values()) > conf.MAX_AMOUNT:
            raise CraftingError("Craft costs exceed the supported range.")
        return dict(total)


class Broadcast(Consumable):
    fields = ("beats", "reach", "channel")
    typeclass = "evennia_rp_crafting.typeclasses.Broadcast"
    typeclass_setting = "RP_CRAFTING_BROADCAST_TYPECLASS"

    def validate(self, config):
        result = super().validate(config)
        reach = config.get("reach", "adjacent")
        channel = text(config.get("channel", ""), "Channel", 80)
        if reach not in ("adjacent", "channel"):
            raise CraftingError("Broadcast reach must be adjacent or channel.")
        if reach == "channel" and channel not in getattr(settings, "RP_CRAFTING_CHANNELS", ()):
            raise CraftingError("Choose a staff-configured ambient channel.")
        if reach == "adjacent" and channel:
            raise CraftingError("Adjacent broadcasts don't use a channel.")
        return result | {"reach": reach, "channel": channel}
