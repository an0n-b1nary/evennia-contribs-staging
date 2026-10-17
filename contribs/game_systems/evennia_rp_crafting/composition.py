# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""One lifecycle, explicit complete verb sets, and separately paid components."""

from collections import Counter
from dataclasses import dataclass, field

from django.conf import settings

from . import conf
from .behaviours import behaviour
from .catalog import validate_niche
from .errors import CraftingError


def check_combination(lifecycle, keys, *, partial=False):
    allowed = getattr(settings, "RP_CRAFTING_COMBINATIONS", conf.DEFAULT_COMBINATIONS)
    if not isinstance(allowed, dict):
        raise CraftingError("The crafting combinations setting must be a mapping.")
    choices = allowed.get(lifecycle, [])
    if not isinstance(choices, (list, tuple)) or any(
        not isinstance(choice, (list, tuple))
        or any(not isinstance(key, str) for key in choice)
        or len(set(choice)) != len(choice)
        for choice in choices
    ):
        raise CraftingError("Crafting combinations must list complete verb sets.")
    if len(keys) != len(set(keys)):
        raise CraftingError("Don't repeat a crafting verb.")
    if not any(
        set(keys) <= set(choice) if partial else set(keys) == set(choice) for choice in choices
    ):
        raise CraftingError("That lifecycle and verb combination is unavailable.")


def specifications(key, behaviour_key, configuration, verbs=None, *, partial=False):
    """The single-behaviour entry point remains shorthand for the same product."""
    implementation = behaviour(behaviour_key)
    if verbs is not None and not isinstance(verbs, list):
        raise CraftingError("Crafting verbs must be a list.")
    entries = list(verbs or [])
    if implementation.role == "verb":
        entries.insert(0, {"key": behaviour_key, "niche": key, "configuration": configuration})
        behaviour_key, configuration = "carried", {}
        implementation = behaviour(behaviour_key)
    if implementation.role != "lifecycle":
        raise CraftingError("Choose exactly one crafting lifecycle.")
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"key", "niche", "configuration"}
            or not isinstance(entry["key"], str)
            or not isinstance(entry["niche"], str)
        ):
            raise CraftingError("Each verb needs a key, contributing niche and configuration.")
        if behaviour(entry["key"]).role != "verb":
            raise CraftingError("A lifecycle cannot be added as a verb.")
    check_combination(behaviour_key, [entry["key"] for entry in entries], partial=partial)
    return behaviour_key, implementation, configuration, entries


@dataclass
class Composition:
    lifecycle_key: str
    implementation: object
    configuration: dict
    verbs: list
    contributors: list
    definitions: list
    resources: dict
    input_categories: set
    facets: dict = field(default_factory=dict)

    def create(self, actor, name, description, config):
        return self.implementation.create(actor, name, description, config)

    def context(self, key):
        return {
            "niche": key,
            "behaviour": self.lifecycle_key,
            "configuration": self.configuration,
            "verbs": self.verbs,
            "contributors": self.contributors,
        } | ({"facets": self.facets} if self.facets else {})


def prepare(key, behaviour_key, configuration, verbs=None):
    from .services import niche

    lifecycle, implementation, config, entries = specifications(
        key, behaviour_key, configuration, verbs
    )
    primary = niche(key)
    validate_niche(primary)
    config = implementation.validate(config)
    total = Counter()
    categories = set()
    definitions = {}
    contributors = {}

    def contribute(niche_key, component_key, component, component_config):
        definition = definitions.get(niche_key)
        if definition is None:
            definition = niche(niche_key)
            validate_niche(definition)
            definitions[niche_key] = definition
        if component_key not in definition.behaviours:
            raise CraftingError("That niche doesn't grant this behaviour.")
        costs = component.cost(component_key, component_config)
        if set(costs) - set(definition.input_categories):
            raise CraftingError("This feature needs an input category the niche doesn't allow.")
        total.update(costs)
        categories.update(definition.input_categories)
        row = contributors.setdefault(
            niche_key,
            {
                "key": niche_key,
                "name": definition.name,
                "behaviours": [],
            },
        )
        row["behaviours"].append(component_key)

    # Neutral Carried grants nothing and costs nothing. Its primary niche must
    # still be a contributor; choosing an unrelated niche cannot bypass access.
    if lifecycle != "carried":
        contribute(key, lifecycle, implementation, config)
    normalized = []
    for entry in sorted(entries, key=lambda entry: entry["key"]):
        verb = behaviour(entry["key"])
        verb_config = verb.validate(entry["configuration"])
        contribute(entry["niche"], entry["key"], verb, verb_config)
        normalized.append(entry | {"configuration": verb_config})
    if key not in contributors:
        raise CraftingError("The primary niche must contribute to the item.")
    if not total or sum(total.values()) > conf.MAX_AMOUNT:
        raise CraftingError("Craft costs must include resources within the supported range.")
    return primary, Composition(
        lifecycle,
        implementation,
        config,
        normalized,
        list(contributors.values()),
        list(definitions.values()),
        dict(total),
        categories,
    )


def invoke(actor, item, key):
    """Dispatch from verified provenance; production settings never revoke items."""
    from .models import CraftRecord

    if key == "readable":
        from .pages import read

        return read(actor, item)
    record = CraftRecord.objects.filter(item_id=item.pk).first()
    entry = (
        next((entry for entry in record.verb_data if entry["key"] == key), None) if record else None
    )
    if entry is None:
        raise CraftingError("That action is unavailable.")
    implementation = behaviour(key)
    if implementation.role != "verb":
        raise CraftingError("That action is unavailable.")
    return implementation.invoke(actor, item, entry["configuration"])
