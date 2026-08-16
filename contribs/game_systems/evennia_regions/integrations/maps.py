# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Regions -> Maps tile overlay: which region a mapped room belongs to.

evennia_maps places rooms on a grid and knows nothing else about them. It
asks its installed partners once per map render, via the
``collect_tile_overlays`` collector signal, and this module answers for
regions. Nothing to configure: install both contribs and tiles gain a
region label and a link to the region page; uninstall either and the map
renders without them.

Overlay key
-----------
``primary_region`` — ``{room_id: {"id": int, "name": str}}`` for rooms that
have a visible region. evennia_maps renders the name on the tile and
reverses ``evennia_regions:region-detail`` against the id; a room with no
membership is simply absent from the dict.

Connected from RegionsConfig.ready(), gated on evennia_maps being
installed. This is the one place regions reaches *out* to another contrib
rather than being read by it, and it stays a one-way, optional edge:
evennia_regions declares no dependency on evennia_maps and imports it only
inside that gated branch.
"""

from evennia_regions.models import RegionMembership


def _primary_regions_by_room(room_ids):
    """
    Bulk equivalent of ``RegionMembership.primary_for()`` for many rooms, in
    one query.

    The ordering stays in step with ``primary_for()``: the flagged primary
    first, then the earliest membership, with pk breaking ties between rows
    created in the same transaction. ``setdefault`` keeps the first row seen
    per room, which is that same winner.

    **Divergence from primary_for(): archived regions are excluded.** The
    map's whole use for this is a clickable label, and ``RegionDetailView``
    resolves through ``Region.objects`` (which excludes archived), so an
    archived region would render a link straight to a 404. A room whose
    flagged primary is archived therefore falls through to its next
    non-archived membership rather than going blank — the best *visible*
    answer, which is the only kind a visitor can act on. The join has to
    say so explicitly: filtering on ``RegionMembership.objects`` does not
    apply Region's default manager to the joined table.
    """
    rows = (
        RegionMembership.objects.filter(room_id__in=room_ids, region__is_archived=False)
        .order_by("room_id", "-is_primary", "created_at", "pk")
        .values_list("room_id", "region_id", "region__name")
    )
    result = {}
    for room_id, region_id, region_name in rows:
        result.setdefault(room_id, {"id": region_id, "name": region_name})
    return result


def provide(sender, room_ids, staff, **kwargs):
    """
    ``collect_tile_overlays`` receiver — see the module docstring for the key.

    One query for the whole grid regardless of tile count. Region membership
    carries no privacy dimension of its own (the region pages are public,
    and the map has already withheld the tiles a visitor may not see), so
    *staff* does not change the answer.
    """
    if not room_ids:
        return {}
    return {"primary_region": _primary_regions_by_room(room_ids)}
