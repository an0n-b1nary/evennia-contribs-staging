# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Descriptive addressees, paid signet designs and durable physical seals."""

from django.conf import settings
from django.db.models import F
from django.utils import timezone
from evennia.objects.models import ObjectDB

from evennia_links.transactions import atomic_objects

from . import conf
from .behaviours import Behaviour, text
from .errors import CraftingError
from .models import CraftRecord, LetterState


def line(value, label, *, required=False):
    value = text(value, label, 255, required=required)
    if value and (not value.isprintable() or "|" in value):
        raise CraftingError(f"{label} must be plain single-line text.")
    return value


class LetterFacet:
    def prepare(self, actor, value, composition):
        if not isinstance(value, dict) or set(value) != {"addressee"}:
            raise CraftingError("A letter needs an addressee line.")
        if composition.lifecycle_key != "carried" or not any(
            row["key"] == "readable" for row in composition.verbs
        ):
            raise CraftingError("Letters require a carried Readable.")
        return {"addressee": line(value["addressee"], "Addressee")}, {}

    def display(self, looker, value):
        # Editable physical state is displayed separately, never a stale draft.
        return []


class SignetFacet:
    def prepare(self, actor, value, composition):
        if not isinstance(value, dict) or set(value) - {"design", "niche"}:
            raise CraftingError("A signet needs a design and optional contributing niche.")
        key = value.get("niche", composition.contributors[0]["key"])
        permitted = getattr(settings, "RP_CRAFTING_SIGNET_NICHES", ())
        if not isinstance(permitted, (list, tuple)) or any(
            not isinstance(entry, str) for entry in permitted
        ):
            raise CraftingError("Signet niches must be a list of niche keys.")
        definition = next((row for row in composition.definitions if row.key == key), None)
        if (
            composition.lifecycle_key != "wearable"
            or definition is None
            or key not in permitted
            or not any(
                row["key"] == key and "wearable" in row["behaviours"]
                for row in composition.contributors
            )
        ):
            raise CraftingError("Signets require a permitted contributing wearable niche.")
        design = line(value.get("design", ""), "Seal design", required=True)
        costs = Behaviour().cost("signet", {})
        if set(costs) - set(definition.input_categories):
            raise CraftingError("The signet niche does not permit its input categories.")
        return {"design": design, "niche": key}, costs

    def display(self, looker, value):
        return [f"Signet design (IC): {value['design']}"]


def provide(sender, **kwargs):
    return {"letter": LetterFacet(), "signet": SignetFacet()}


def initialize(record):
    value = record.prose.get("facets", {}).get("letter")
    if value is not None:
        LetterState.objects.create(craft=record, addressee=value["addressee"])


def lock_objects(actor, *items):
    """Match journal/economy lock order; reserve SQLite's writer before reads."""
    ObjectDB.objects.filter(pk=actor.pk).update(db_key=F("db_key"))
    ObjectDB.objects.select_for_update().get(pk=actor.pk)
    list(
        ObjectDB.objects.select_for_update()
        .filter(pk__in={item.pk for item in items} - {actor.pk})
        .order_by("pk")
    )


def require_open(record):
    state = LetterState.objects.filter(craft=record).first()
    if state and state.intact:
        raise CraftingError("Read a page to break the intact seal first.")
    return state


def carried_record(actor, item):
    from .pages import configuration
    from .services import _require

    _require(actor, spending=False)
    holder = ObjectDB.objects.filter(pk=item.pk).values_list("db_location_id", flat=True).first()
    if holder != actor.pk:
        raise CraftingError("Carry the letter to address or seal it.")
    record, pages = configuration(actor, item)
    if record.lifecycle != "carried":
        raise CraftingError("Letters require a carried Readable.")
    if not item.access(actor, "write", default=True):
        raise CraftingError("You cannot change that letter.")
    return record, pages


@atomic_objects
def address(actor, item, addressee):
    lock_objects(actor, item)
    record, _ = carried_record(actor, item)
    value = line(addressee, "Addressee")
    state, _ = LetterState.objects.get_or_create(craft=record)
    if state.seal_number:
        raise CraftingError("Sealing permanently freezes the letter and its addressee.")
    state.addressee = value
    state.save(update_fields=["addressee"])
    return state


@atomic_objects
def seal(actor, item, signet):
    lock_objects(actor, item, signet)
    record, pages = carried_record(actor, item)
    if not pages:
        raise CraftingError("Write at least one page before sealing the letter.")
    holder = ObjectDB.objects.filter(pk=signet.pk).values_list("db_location_id", flat=True).first()
    if (
        holder != actor.pk
        or not signet.access(actor, "view", default=True)
        or not signet.access(actor, "use", default=True)
    ):
        raise CraftingError("Carry a signet you can use.")
    stamp = CraftRecord.objects.filter(item_id=signet.pk).first()
    value = stamp.prose.get("facets", {}).get("signet") if stamp else None
    if not value or stamp.lifecycle != "wearable":
        raise CraftingError("That item has no crafted signet design.")
    state, _ = LetterState.objects.get_or_create(craft=record)
    if state.intact:
        raise CraftingError("The letter already has an intact seal.")
    if state.seal_number >= conf.MAX_AMOUNT:
        raise CraftingError("This letter has reached its seal limit.")
    state.seal_design = value["design"]
    state.signet = stamp
    state.sealed_by_id = actor.pk
    state.sealed_by_name = actor.key
    state.seal_number += 1
    state.sealed_at = timezone.now()
    state.opened_at = None
    state.save()
    return state


def open_on_read(record):
    """Called inside the locked successful-read transaction, before lore grants."""
    state = LetterState.objects.filter(craft=record).first()
    if state is None:
        return ""
    if not state.intact:
        return describe(state)
    state.opened_at = timezone.now()
    if state.first_opened_at is None:
        state.first_opened_at = state.opened_at
    state.save(update_fields=["opened_at", "first_opened_at"])
    return f"You break the seal: {state.seal_design}.\n{describe(state)}"


def display(record):
    state = LetterState.objects.filter(craft=record).first()
    if state is None:
        return ""
    return describe(state)


def describe(state):
    lines = [f"Addressed to (IC): {state.addressee}"] if state.addressee else []
    if state.seal_number:
        lines.append(f"Seal (IC): {state.seal_design} — {'intact' if state.intact else 'broken'}.")
        if state.seal_number > 1:
            lines.append(f"Previously opened; resealed (impression {state.seal_number}).")
        lines.append("Enclosed text and addressee are frozen.")
    return "\n".join(lines)
