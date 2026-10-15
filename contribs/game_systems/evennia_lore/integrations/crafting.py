# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Gated provider: lore owns knowledge, crafting owns immutable item snapshots."""

from collections import Counter

from django.apps import apps
from django.conf import settings

from evennia_lore.items import acquire_page, held_entry, label, staff, validate_citations
from evennia_lore.models import LoreAcquisition, LoreEntry


def supported():
    if not apps.is_installed("evennia_rp_crafting"):
        return False
    try:
        from evennia_rp_crafting import signals
    except ImportError:
        return False
    return all(hasattr(signals, key) for key in ("collect_facets", "page_read"))


class Citations:
    def prepare(self, actor, value, composition):
        from evennia_rp_crafting.errors import CraftingError
        from evennia_rp_crafting.pages import authored_pages

        entry = next((row for row in composition.verbs if row["key"] == "readable"), None)
        if entry is None:
            raise CraftingError("Citations require a Readable verb.")
        return validate_citations(actor, value, len(authored_pages(entry["configuration"]))), {}

    def display(self, looker, value):
        return []


class Recognition:
    def prepare(self, actor, value, composition):
        from evennia_rp_crafting.errors import CraftingError

        if not isinstance(value, list) or len(value) > 20:
            raise CraftingError("Choose at most 20 recognition features.")
        definitions = {row.key: row for row in composition.definitions}
        rows, costs = [], Counter()
        for row in value:
            if not isinstance(row, dict) or set(row) - {"entry", "text", "niche"}:
                raise CraftingError(
                    "Recognition needs an entry, text and optional contributing niche."
                )
            entry = held_entry(actor, row.get("entry"))
            line = row.get("text")
            if (
                not isinstance(line, str)
                or not 1 <= len(line.strip()) <= 400
                or not line.isprintable()
                or "|" in line
            ):
                raise CraftingError(
                    "Recognition text must be plain single-line prose of 1-400 characters."
                )
            key = row.get("niche", composition.contributors[0]["key"])
            definition = definitions.get(key)
            if definition is None:
                raise CraftingError("Recognition must use a contributing niche.")
            category = getattr(settings, "LORE_RECOGNITION_CATEGORIES", {}).get(key)
            if category is None:
                category = next(
                    (kind for kind in composition.resources if kind in definition.input_categories),
                    None,
                )
            if category not in definition.input_categories:
                raise CraftingError("Recognition has no permitted input category.")
            costs[category] += 1
            rows.append({"entry": entry.pk, "text": line.strip(), "niche": key})
        return rows, dict(costs)

    def display(self, looker, value):
        privileged = staff(looker)
        manager = LoreEntry.all_objects if privileged else LoreEntry.objects
        entries = {
            entry.pk: entry for entry in manager.filter(pk__in=[row["entry"] for row in value])
        }
        known = set(
            LoreAcquisition.objects.filter(character=looker, entry_id__in=entries).values_list(
                "entry_id", flat=True
            )
        )
        lines = []
        for row in value:
            entry = entries.get(row["entry"])
            if entry is None:
                if privileged:
                    lines.append(
                        f"{row['text']} (recognition gate: missing lore PK {row['entry']})"
                    )
                continue
            if not privileged and (
                entry.pk not in known or entry.status != LoreEntry.Status.PUBLISHED
            ):
                continue
            gate = "recognition gate" if privileged else "you recognise this"
            lines.append(f"{row['text']} ({gate}: {label(entry.title)}, #{entry.entry_number})")
        return lines


def provide(sender, **kwargs):
    if not apps.is_installed("evennia_lore"):
        return {}
    return {"lore_citations": Citations(), "lore_recognition": Recognition()}


def on_read(sender, actor, record, number, canonical, **kwargs):
    if not canonical or not apps.is_installed("evennia_lore"):
        return ""
    return acquire_page(actor, record.prose.get("facets", {}).get("lore_citations", []), number)
