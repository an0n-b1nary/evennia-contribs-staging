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

Connected from LoreConfig.ready(), gated on evennia_maps being installed.
"""

from django.apps import apps
from django.conf import settings

from evennia_lore.models import LoreEntry, LoreRegionLink


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
