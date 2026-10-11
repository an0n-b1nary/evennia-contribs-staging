# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Lore -> Maps tile overlay: which parts of the world have lore written about them.

evennia_maps asks its installed partners once per map render, via the
``collect_tile_overlays`` collector signal, and this module answers for
lore. Nothing to configure: install both contribs and the lore pin layer
appears; uninstall either and the map renders without it.

Overlay key
-----------
``has_lore`` — ``{room_id: True}`` for rooms whose primary region has at
least one lore entry a web visitor could actually read.

Visibility
----------
Gated to the same eligibility the compendium's own passive pool uses —
PUBLISHED + PUBLIC + not archived — **regardless of the caller's staff
flag**. A pin is not a link to one entry; it says "there is lore here",
and it is drawn on a public page. Widening it for staff would only make
the map disagree with the compendium, and staff already have full lore
browse there.

Rooms, regions, and the third contrib
-------------------------------------
Lore attaches to *regions*, the map draws *rooms*, and evennia_maps sends
room ids only. So this module resolves each room's primary region itself
via evennia_regions, gated on ``LORE_REGIONS_APP_LABEL`` and resolved
through ``apps.get_model`` — the same soft, optional edge
``LoreRegionLink.region_id`` already is. With regions absent there is
nothing to attach lore to, and the overlay is simply empty.

Room panel section
------------------
``provide_detail`` answers evennia_maps' ``collect_tile_detail`` seam with a
``lore`` section for the clicked room's primary region: how many published
entries are tied to it, and how many of them the viewer's character knows
(holds a ``LoreAcquisition`` row for). Per viewer:

- an entry the character knows is listed with a link;
- a public entry it doesn't know yet is listed by title, locked, with
  ``LORE_MAP_LOCKED_NOTE`` beside it. Showing it is the point: it tells a
  player there is lore here they could still pick up through play;
- a restricted entry it doesn't know is counted, never titled. Only a
  storyteller's ``+share`` grants those, so naming one would publish what
  the restriction withholds.

Staff see every entry listed and linked, restricted ones noted as such.

Connected from LoreConfig.ready(), gated on evennia_maps being installed.
"""

from django.apps import apps
from django.conf import settings
from django.urls import NoReverseMatch, reverse

from evennia_lore.models import LoreAcquisition, LoreEntry, LoreRegionLink

DEFAULT_LOCKED_NOTE = "not yet known: learned through roleplay"


def _regions_model():
    """The Region membership model, or None when evennia_regions is absent."""
    regions_label = getattr(settings, "LORE_REGIONS_APP_LABEL", "evennia_regions")
    try:
        return apps.get_model(regions_label, "RegionMembership")
    except LookupError:
        return None


def _primary_region_ids_by_room(room_ids):
    """
    ``{room_id: region_id}`` — the bulk equivalent of regions'
    ``RegionMembership.primary_for()``, in one query.

    The ordering stays in step with ``primary_for()``: the flagged primary
    first, then the earliest membership, with pk breaking ties between rows
    created in the same transaction.

    Archived regions are excluded, matching what regions' own map overlay
    reports: a tile whose only region is archived should not claim lore that
    the visitor cannot navigate to. The filter has to be spelled out on the
    join — querying through RegionMembership does not apply Region's default
    (archive-excluding) manager to the joined table.
    """
    RegionMembership = _regions_model()
    if RegionMembership is None:
        return {}
    rows = (
        RegionMembership.objects.filter(room_id__in=room_ids, region__is_archived=False)
        .order_by("room_id", "-is_primary", "created_at", "pk")
        .values_list("room_id", "region_id")
    )
    result = {}
    for room_id, region_id in rows:
        result.setdefault(room_id, region_id)
    return result


def _region_ids_with_public_lore(region_ids):
    """Subset of *region_ids* with at least one published, public, unarchived entry."""
    if not region_ids:
        return set()
    return set(
        LoreRegionLink.objects.filter(
            region_id__in=region_ids,
            entry__status=LoreEntry.Status.PUBLISHED,
            entry__privacy=LoreEntry.Privacy.PUBLIC,
            entry__is_archived=False,
        )
        .values_list("region_id", flat=True)
        .distinct()
    )


def provide(sender, room_ids, staff, **kwargs):
    """
    ``collect_tile_overlays`` receiver — see the module docstring for the key.

    Two queries for the whole grid, flat in tile count: one to resolve the
    rooms' regions, one to ask which of those regions have readable lore.
    """
    if not room_ids:
        return {}
    region_by_room = _primary_region_ids_by_room(room_ids)
    if not region_by_room:
        return {"has_lore": {}}
    lore_region_ids = _region_ids_with_public_lore(set(region_by_room.values()))
    return {
        "has_lore": {
            room_id: True
            for room_id, region_id in region_by_room.items()
            if region_id in lore_region_ids
        }
    }


def _entry_url(pk):
    name = getattr(settings, "LORE_MAP_ENTRY_URL_NAME", "lore-detail")
    if not name:
        return ""
    try:
        return reverse(name, args=[pk])
    except NoReverseMatch:
        return ""


def _count(n, singular, plural):
    return f"{n} {singular if n == 1 else plural}"


def provide_detail(sender, room_id, room, staff, viewer=None, **kwargs):
    """
    ``collect_tile_detail`` receiver: the ``lore`` section, see the module
    docstring. Three queries: the room's region, its entries, and which of
    them the viewer knows.
    """
    region_id = _primary_region_ids_by_room([room_id]).get(room_id)
    if region_id is None:
        return {}
    entries = list(
        LoreEntry.objects.filter(
            region_links__region_id=region_id,
            status=LoreEntry.Status.PUBLISHED,
            is_archived=False,
        )
        .order_by("title", "pk")
        .values_list("pk", "title", "privacy")
        .distinct()
    )
    if not entries:
        return {}
    total = _count(len(entries), "entry is", "entries are")
    if staff:
        items = [
            {
                "label": title,
                "url": _entry_url(pk),
                "note": "restricted" if privacy == LoreEntry.Privacy.RESTRICTED else "",
            }
            for pk, title, privacy in entries
        ]
        return {
            "lore": {
                "title": "Lore",
                "order": 40,
                "summary": f"{total} tied to this region.",
                "items": items,
            }
        }

    known = set()
    if viewer is not None:
        known = set(
            LoreAcquisition.objects.filter(
                character=viewer, entry_id__in=[pk for pk, _, _ in entries]
            ).values_list("entry_id", flat=True)
        )
    note = getattr(settings, "LORE_MAP_LOCKED_NOTE", DEFAULT_LOCKED_NOTE)
    known_items, locked_items, unlisted = [], [], 0
    for pk, title, privacy in entries:
        if pk in known:
            known_items.append({"label": title, "url": _entry_url(pk)})
        elif privacy == LoreEntry.Privacy.PUBLIC:
            locked_items.append({"label": title, "locked": True, "note": note})
        else:
            unlisted += 1
    summary = f"{total} tied to this region."
    if viewer is not None:
        summary += f" You know {len(known_items)}."
    if unlisted:
        summary += f" {_count(unlisted, 'other is', 'others are')} only shared by a storyteller."
    return {
        "lore": {
            "title": "Lore",
            "order": 40,
            "summary": summary,
            "items": known_items + locked_items,
        }
    }
