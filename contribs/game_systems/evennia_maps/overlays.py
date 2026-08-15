# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
The tile-overlay seam: how other contribs light up this map without
evennia_maps importing any of them.

``collect_tile_overlays`` (evennia_maps.signals) is a *collector* signal.
It is sent **once per map render** — never per tile — with the room ids
being drawn and whether the caller is staff. Every connected provider
answers for the rooms it has data about, and the responses are merged by
``evennia_links.collect_dicts()``, which ``send_robust()``s: a provider
that raises degrades its own overlay to absent rather than 500-ing the
map.

Why a signal instead of reading the partner models directly
-----------------------------------------------------------
Five of the six overlays carry a privacy rule *only the owning domain
knows*. ``evennia_scenes`` exposes ``room.active_scene_id`` as a bare pk
with no privacy dimension — light a pin from it and a view-private scene
announces itself to every anonymous visitor. Same for the heatmap (window
+ visibility tiers) and the calendar (staff-only events). A standalone
evennia_maps must not re-encode any of those rules, so it asks instead.

Overlay keys evennia_maps reads
-------------------------------
Each value is a ``{room_id: value}`` dict; missing rooms simply have no
overlay. Providers must write **disjoint** top-level keys — receiver order
is not guaranteed, so two providers claiming one key is a bug in the
providers.

===================  ============  ===============================================
Key                  Owner         Value
===================  ============  ===============================================
``primary_region``   regions       ``{"id": int, "name": str}`` — the room's
                                   primary region, for the tile link
``has_active_scene`` scenes        ``True`` for a room with a live scene
``recent_scene_count`` scenes      ``int`` — heatmap weight
``recent_scenes``    scenes        ``[{"id": int, "title": str}, ...]``
``has_lore``         lore          ``True`` where lore is attached
``upcoming_events``  calendar      ``[{"id": int, "title": str}, ...]``
===================  ============  ===============================================

``hangout_type`` is *not* collected here. It is a bare room attribute with
no table and no privacy rule, so evennia_maps reads it duck-typed exactly
as it already reads ``terrain_tags`` — see ``views.tile_hangout_type``.

A provider connects itself from its own ``AppConfig.ready()``, gated on
evennia_maps being installed, e.g.::

    maps_label = getattr(settings, "SCENES_MAPS_APP_LABEL", "evennia_maps")
    if _app_present(maps_label):
        from evennia_maps.signals import collect_tile_overlays
        from evennia_scenes.integrations import maps as maps_overlays

        collect_tile_overlays.connect(
            maps_overlays.provide, dispatch_uid="evennia_scenes.tile_overlays"
        )

**Every provider must stay one bulk query per overlay.** The whole design
rests on the tile cost being flat in tile count;
``test_overlay_query_count_is_flat_in_tile_count`` is what stands between
it and an N+1 per tile.

Outbound links
--------------
Overlay values name *other contribs'* pages, which evennia_maps cannot
``{% url %}`` unconditionally — the partner may not be installed, or may
be mounted under a different namespace. ``overlay_url_templates()``
reverses each one with a ``0`` placeholder pk and drops the ones that do
not resolve; the SVG page and the Leaflet JS both render a link only when
its template came back non-empty.
"""

import logging

from django.conf import settings
from django.urls import NoReverseMatch, reverse

from evennia_links import collect_dicts
from evennia_maps.models import MapPlane
from evennia_maps.signals import collect_tile_overlays

logger = logging.getLogger("evennia")

DEFAULT_OVERLAY_URL_NAMES = {
    "region": "evennia_regions:region-detail",
    "scene": "evennia_scenes:scene-detail",
    "event": "evennia_calendar:calendar-event-detail",
}
"""Named routes the map links out to, keyed by the role the link plays.

Override individual entries via ``MAPS_OVERLAY_URL_NAMES``; the setting is
merged *over* these defaults, so a game renaming only its scene route
writes one key rather than restating the table (the same merge idiom
``MAPS_DIRECTION_OFFSETS`` already uses). Set a value to ``""`` to
suppress that link entirely.
"""


def overlay_url_names():
    """The link table, with ``MAPS_OVERLAY_URL_NAMES`` merged over the defaults."""
    names = dict(DEFAULT_OVERLAY_URL_NAMES)
    names.update(getattr(settings, "MAPS_OVERLAY_URL_NAMES", {}) or {})
    return names


def overlay_url_templates():
    """
    ``{role: "/path/0/"}`` for every outbound link that currently resolves.

    A role whose route is not mounted (partner contrib not installed, or
    included without the expected namespace) is **absent** from the result
    rather than present-and-broken, so callers can test for the key. Not
    cached: ``reverse()`` has its own resolver cache, and caching here
    would survive an ``override_settings`` in a game's own tests.
    """
    templates = {}
    for role, name in overlay_url_names().items():
        if not name:
            continue
        try:
            templates[role] = reverse(name, args=[0])
        except NoReverseMatch:
            logger.debug(
                "evennia_maps: no route named %r for the %s link; omitting it from the map",
                name,
                role,
            )
    return templates


def collect_overlays(room_ids, *, staff):
    """
    Merge every connected provider's answer into one
    ``{overlay_key: {room_id: value}}`` dict.

    sender is ``MapPlane`` rather than the calling view: the signal belongs
    to the models layer, and a provider that ever wants to filter on sender
    should be able to import it without reaching into the web layer.
    """
    if not room_ids:
        return {}
    return collect_dicts(
        collect_tile_overlays, sender=MapPlane, room_ids=list(room_ids), staff=staff
    )
