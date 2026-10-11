# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Resources -> Maps room panel: what gathering in this room's terrain can find.

evennia_maps asks its installed partners about one room when a player clicks
it on the live map, via the ``collect_tile_detail`` collector signal. This
module answers with a ``resources`` section: the categories of resource tied
to the room's terrain, each with its resource names. It's qualitative on
purpose, with no weights, quantities or odds.

- **Reveal:** nothing for players until ``RP_RESOURCES_REVEALED`` is on.
  Staff always see it.
- **Closed terrains:** a terrain outside ``RP_RESOURCES_OPEN_TERRAINS`` shows
  players nothing, so a room in a stage that hasn't opened doesn't give away
  what it will hold. Staff see the list, marked not open yet. With the
  setting unset every terrain on a room is open.
- **Common pool:** resources with no terrain are found everywhere, so the
  panel leaves them out. It's about this place.
- **Lean:** when the viewer's gathering lean matches something here, the
  summary says so.
"""

from django.conf import settings

from evennia_links.runtime import get

from . import conf
from .gathering import lean, matches_lean, open_terrains, terrain_for
from .models import ResourceDefinition


def _is_open(terrain):
    if getattr(settings, "RP_RESOURCES_OPEN_TERRAINS", None) is None:
        return True
    return terrain in open_terrains()


def provide_detail(sender, room_id, room, staff, viewer=None, **kwargs):
    """``collect_tile_detail`` receiver: the ``resources`` section."""
    if not (staff or get("RP_RESOURCES_REVEALED")):
        return {}
    terrain = terrain_for(room)
    if not terrain:
        return {}
    is_open = _is_open(terrain)
    if not (is_open or staff):
        return {}
    # A JSON list: filtered here rather than with a JSON lookup, which not
    # every database backend supports. The catalog is small.
    found = [
        resource
        for resource in ResourceDefinition.objects.filter(in_trickle=True, archived=False)
        if terrain in (resource.terrains or [])
    ]
    if not found:
        return {}
    names = conf.categories()
    by_category = {}
    for resource in sorted(found, key=lambda resource: resource.name.casefold()):
        by_category.setdefault(resource.category, []).append(resource.name)
    items = [
        {"label": names.get(category, category), "note": ", ".join(resources)}
        for category, resources in sorted(
            by_category.items(), key=lambda pair: names.get(pair[0], pair[0]).casefold()
        )
    ]
    summary = "Gathering in this terrain can turn up:"
    if not is_open:
        summary = "This terrain isn't open to gathering yet. When it opens, it can turn up:"
    choice = lean(viewer) if viewer is not None else None
    if is_open and any(matches_lean(resource, choice) for resource in found):
        summary += " (your gathering lean finds something here)"
    return {
        "resources": {
            "title": "Gathering here",
            "order": 60,
            "summary": summary,
            "items": items,
        }
    }
