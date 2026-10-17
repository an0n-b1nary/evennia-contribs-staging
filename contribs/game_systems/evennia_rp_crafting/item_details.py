# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Paid exterior details and self-directed senses from immutable craft snapshots."""

from django.conf import settings

from . import conf
from .behaviours import text
from .errors import CraftingError
from .models import CraftRecord

MAX_DETAILS = 8
SENSES = ("smell", "sound", "touch")


def plain(value, label, limit):
    """Validate bounded prose that cannot inject terminal markup or extra lines."""
    value = text(value, label, limit, required=True)
    if not value.isprintable() or "|" in value:
        raise CraftingError(f"{label} must be plain, single-line text.")
    return value


def detail_name(value):
    """Normalize a detail's exact, case-insensitive name."""
    value = plain(value, "Detail name", 40).casefold()
    if len(value) > 40:
        raise CraftingError("Normalized detail names must contain 1-40 characters.")
    if "=" in value:
        raise CraftingError("Detail names cannot contain =.")
    return value


def validate_details(value):
    """Return an independent normalized mapping of at most eight details."""
    if not isinstance(value, dict) or len(value) > MAX_DETAILS:
        raise CraftingError(f"Choose at most {MAX_DETAILS} named details.")
    result = {}
    for key, prose in value.items():
        name = detail_name(key)
        if name in result:
            raise CraftingError("Don't repeat a detail name.")
        result[name] = plain(prose, "Detail text", 1000)
    return result


def validate_senses(value):
    """Return the optional smell, sound and touch lines."""
    if not isinstance(value, dict) or set(value) - set(SENSES):
        raise CraftingError("Item senses allow smell, sound and touch.")
    return {key: plain(prose, "Sensory text", 400) for key, prose in value.items()}


def cost(key, count, composition):
    """Charge each entry in the first contributor's first paid input category."""
    if not count:
        return {}
    rules = getattr(settings, "RP_CRAFTING_FACET_UNIT_COSTS", {"details": 1, "senses": 1})
    amount = rules.get(key) if isinstance(rules, dict) else None
    if not conf.positive(amount) or amount * count > conf.MAX_AMOUNT:
        raise CraftingError("Item facets need a positive, bounded unit cost.")
    primary = composition.definitions[0]
    category = next(
        (name for name in composition.resources if name in primary.input_categories), None
    )
    if category is None:
        raise CraftingError("Item facets need a permitted input category.")
    return {category: amount * count}


class Details:
    """Named close examination, available on every crafting lifecycle."""

    def prepare(self, actor, value, composition):
        data = validate_details(value)
        return data, cost("details", len(data), composition)

    def display(self, looker, value):
        return [f"Details: {', '.join(value)}."] if value else []


class Senses:
    """Private sensory prose, independent of fixture room layers and emissions."""

    def prepare(self, actor, value, composition):
        data = validate_senses(value)
        return data, cost("senses", len(data), composition)

    def display(self, looker, value):
        return (
            [f"Item senses: {', '.join(key for key in SENSES if key in value)}."] if value else []
        )


def provide(sender, **kwargs):
    """Register core facets alongside optional partner providers."""
    return {"details": Details(), "senses": Senses()}


def local_items(actor):
    """Search only carried items and objects in the actor's current room."""
    return list(actor.contents) + list(actor.location.contents if actor.location else [])


def record_for(actor, item, action):
    """Check proximity and access before looking up any stored facet prose."""
    if not conf.visible(actor):
        raise CraftingError("Crafting is unavailable.")
    locations = {actor.pk}
    if actor.db_location_id:
        locations.add(actor.db_location_id)
    if item.db_location_id not in locations or not item.access(actor, "view", default=True):
        raise CraftingError("You cannot examine that item here.")
    if not item.access(actor, action, default=True):
        raise CraftingError("You cannot examine that item here.")
    record = CraftRecord.objects.filter(item_id=item.pk).first()
    if record is None:
        raise CraftingError("Nothing stands out.")
    return record


def examine(actor, item, name):
    """Read one exterior detail without invoking Readable or changing state."""
    record = record_for(actor, item, "view")
    value = record.prose.get("facets", {}).get("details", {}).get(detail_name(name))
    if not value:
        raise CraftingError("No such item detail.")
    return value


def sense(actor, item, key):
    """Inspect one sense without room output, consumption, bookmarks or lore."""
    if key not in SENSES:
        raise CraftingError("Choose smell, sound or touch.")
    record = record_for(actor, item, "listen" if key == "sound" else key)
    value = record.prose.get("facets", {}).get("senses", {}).get(key)
    if not value:
        raise CraftingError("Nothing stands out.")
    return value


def edit_draft(command, switch, draft):
    """Edit only exterior facet metadata, leaving lifecycle fields untouched."""
    facets = dict(draft.get("facets", {}))
    detail = switch in ("detail", "undetail")
    facet = "details" if detail else "senses"
    values = dict(facets.get(facet, {}))
    key = detail_name(command.lhs) if detail else command.lhs.strip().casefold()
    if not detail and key not in SENSES:
        raise CraftingError("Choose smell, sound or touch.")
    if switch in ("undetail", "unsense"):
        if key not in values:
            raise CraftingError("No such draft detail or sense.")
        del values[key]
    else:
        if command.rhs is None:
            raise CraftingError(f"Usage: +craft/{switch} name = prose")
        values[key] = command.rhs
    normalized = validate_details(values) if detail else validate_senses(values)
    if normalized:
        facets[facet] = normalized
    else:
        facets.pop(facet, None)
    draft["facets"] = facets
