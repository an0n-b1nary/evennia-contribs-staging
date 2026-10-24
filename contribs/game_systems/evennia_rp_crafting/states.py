# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Immutable wearable variants with a single persistent, holder-selected key."""

from django.apps import apps
from django.conf import settings
from django.db.models import F
from evennia.objects.models import ObjectDB

from evennia_links.transactions import atomic_objects

from . import conf
from .behaviours import text
from .errors import CraftingError
from .models import CraftRecord

MAX_STATES = 8
STATE_KEY = "selected"
STATE_CATEGORY = "rp_crafting_state"


def plain(value, label, limit):
    value = text(value, label, limit, required=True)
    if not value.isprintable() or "|" in value:
        raise CraftingError(f"{label} must be plain, single-line text.")
    return value


def name(value):
    value = plain(value, "State name", 40).casefold()
    if len(value) > 40 or "=" in value:
        raise CraftingError("State names need 1-40 characters without =.")
    return value


def validate(value):
    if not isinstance(value, dict) or set(value) != {"default", "variants"}:
        raise CraftingError("States need a default and named variants.")
    variants = value["variants"]
    if not isinstance(variants, dict) or not 1 <= len(variants) <= MAX_STATES:
        raise CraftingError(f"Choose between 1 and {MAX_STATES} states.")
    result = {}
    for key, fields in variants.items():
        key = name(key)
        if key in result:
            raise CraftingError("Don't repeat a state name.")
        if not isinstance(fields, dict) or not fields or set(fields) - {"description", "worn_line"}:
            raise CraftingError("States change only a description or worn line.")
        result[key] = {
            field: plain(prose, "State prose", 200 if field == "worn_line" else 2000)
            for field, prose in fields.items()
        }
    default = name(value["default"])
    if default not in result:
        raise CraftingError("Choose a default from the named states.")
    return {"default": default, "variants": result}


class States:
    def prepare(self, actor, value, composition):
        if composition.lifecycle_key != "wearable":
            raise CraftingError("States currently require a Wearable lifecycle.")
        data = validate(value)
        unit = getattr(settings, "RP_CRAFTING_STATE_UNIT_COST", 1)
        amount = unit * len(data["variants"]) if conf.positive(unit) else 0
        primary = composition.definitions[0]
        category = next(
            (key for key in composition.resources if key in primary.input_categories), None
        )
        if not category or not conf.positive(amount):
            raise CraftingError("States need a positive, bounded cost in a paid input category.")
        return data, {category: amount}

    def display(self, looker, value):
        return [f"States: {', '.join(value['variants'])}."]


def provide(sender, **kwargs):
    return {"states": States()}


def configuration(item):
    record = CraftRecord.objects.filter(item_id=item.pk).first()
    return record.prose.get("facets", {}).get("states", {}) if record else {}


def current(item, data):
    # Scalar values bypass both the Attribute handler and idmapper caches.
    selected = (
        item.db_attributes.filter(db_key=STATE_KEY, db_category=STATE_CATEGORY, db_attrtype=None)
        .values_list("db_value", flat=True)
        .first()
    )
    return (
        selected if isinstance(selected, str) and selected in data["variants"] else data["default"]
    )


def variant(item):
    data = configuration(item)
    return data["variants"].get(current(item, data), {}) if data else {}


def inspect(actor, item):
    if not conf.visible(actor):
        raise CraftingError("Crafting is unavailable.")
    # Read scalar location afresh rather than trusting a cached typeclass.
    if (
        ObjectDB.objects.filter(pk=item.pk).values_list("db_location_id", flat=True).first()
        != actor.pk
    ):
        raise CraftingError("You must be carrying that item.")
    if not item.access(actor, "view", default=True) or not item.access(
        actor, "adjust", default=True
    ):
        raise CraftingError("You cannot adjust that item.")
    data = configuration(item)
    if not data:
        raise CraftingError("That item has no wearable states.")
    return data


@atomic_objects
def select(actor, item, key):
    from .services import _require

    # Acquire the writer before runtime/access reads: SQLite cannot safely
    # upgrade a concurrent deferred read transaction to a writer.
    ObjectDB.objects.filter(pk=actor.pk).update(db_key=F("db_key"))
    ObjectDB.objects.select_for_update().get(pk=actor.pk)
    # Write before reading for SQLite; all changes serialize on the item.
    ObjectDB.objects.filter(pk=item.pk).update(db_key=F("db_key"))
    ObjectDB.objects.select_for_update().get(pk=item.pk)
    _require(actor, spending=False)
    data = inspect(actor, item)
    if apps.is_installed("evennia_rp_equipment") and item.tags.has("worn", category="rp_equipment"):
        from evennia_rp_chargen import locks

        if locks.frozen(actor):
            raise CraftingError(locks.locked_message(actor))
    key = name(key)
    if key not in data["variants"]:
        raise CraftingError("Choose one of this item's named states.")
    # A stale negative cache from another worker must not create a second row.
    item.attributes.reset_cache()
    item.attributes.add(STATE_KEY, key, category=STATE_CATEGORY)
    return key


def edit_draft(command, switch, draft):
    if draft["behaviour"] != "wearable":
        raise CraftingError("States currently require a Wearable lifecycle.")
    facets = dict(draft.get("facets", {}))
    data = dict(facets.get("states", {}))
    variants = {key: dict(fields) for key, fields in data.get("variants", {}).items()}
    key = name(command.lhs)
    if switch == "unstate":
        if key not in variants:
            raise CraftingError("No such draft state.")
        del variants[key]
        if key == data.get("default"):
            data["default"] = next(iter(variants), "")
    elif switch == "defaultstate":
        if key not in variants:
            raise CraftingError("Choose an existing draft state.")
        data["default"] = key
    else:
        if command.rhs is None:
            raise CraftingError(f"Usage: +craft/{switch} name = prose")
        field = "description" if switch == "statedesc" else "worn_line"
        variants.setdefault(key, {})[field] = command.rhs
        data.setdefault("default", key)
    if variants:
        facets["states"] = validate({"default": data["default"], "variants": variants})
    else:
        facets.pop("states", None)
    draft["facets"] = facets
