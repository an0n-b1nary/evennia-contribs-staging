# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
The room panel: what the live map shows when a player clicks a tile.

The bulk tile feed stays small: enough for a tooltip, a badge and a pin.
Clicking a tile asks for **that one room's** detail, which is where content
that depends on *who is looking* can live: lore the viewer's character
knows, who is standing beside them, what their gathering lean would find.

Two seams feed the panel:

- ``collect_tile_overlays``, asked about the one room with the viewer
  passed along, supplies the fixed parts maps already understands: the
  region, who's here, live scenes, recent logs and upcoming events.
- ``collect_tile_detail`` supplies **sections**: whole blocks owned by a
  partner contrib, which maps renders without knowing what they mean.
  A new partner adds a section without a maps release.

Section shape
-------------
A provider returns ``{section_key: section}``. Keys must be disjoint across
providers, as overlay keys are. A section is a dict::

    {
        "title": "Lore",             # required
        "order": 40,                 # optional; lower sorts first (default 100)
        "summary": "4 entries ...",  # optional line under the title
        "items": [                   # optional
            {
                "label": "The Salt Road",   # required
                "url": "/lore/12/",         # optional; site-relative only
                "note": "Not yet known",    # optional, shown after the label
                "locked": True,             # optional; drawn as not yet known
            },
        ],
    }

Maps validates rather than trusts. A section without a title, or an item
without a label, is dropped; a URL that is not a site-relative path
(``/...``, never ``//host``) is dropped, so a provider bug cannot put a
``javascript:`` link in the panel; the JS sets every string as text. Each
section keeps at most ``MAX_ITEMS`` items.

Privacy stays with the owner, exactly as for overlays: each provider
decides what the viewer may see. The room itself has already passed the
same ``is_room_web_visible()`` check as its tile.

Order guide for providers: lore 40, plots 50, resources 60. Leave gaps.
"""

from django.utils.text import Truncator
from evennia.utils.ansi import strip_ansi

from evennia_links import collect_dicts
from evennia_maps.models import MapPlane
from evennia_maps.overlays import collect_overlays, overlay_url_templates
from evennia_maps.permissions import read_room_attr
from evennia_maps.signals import collect_tile_detail
from evennia_maps.terrain import terrain_style

MAX_ITEMS = 25
DESCRIPTION_CHARS = 280
DEFAULT_ORDER = 100


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _safe_url(value):
    """A site-relative path, or "" for anything else."""
    # Browsers normalize backslashes and remove ASCII controls before
    # resolving URLs, which can turn an apparently relative path into //host.
    if (
        isinstance(value, str)
        and value.startswith("/")
        and not value.startswith("//")
        and "\\" not in value
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        return value
    return ""


def clean_item(item):
    """A validated panel item, or None to drop it."""
    if not isinstance(item, dict):
        return None
    label = _text(item.get("label"))
    if not label:
        return None
    return {
        "label": label,
        "url": _safe_url(item.get("url")),
        "note": _text(item.get("note")),
        "locked": bool(item.get("locked", False)),
    }


def clean_section(key, section):
    """A validated panel section, or None to drop it."""
    if not isinstance(section, dict):
        return None
    title = _text(section.get("title"))
    if not title:
        return None
    order = section.get("order", DEFAULT_ORDER)
    if type(order) is not int:
        order = DEFAULT_ORDER
    items = section.get("items") or []
    if not isinstance(items, (list, tuple)):
        items = []
    cleaned = [item for item in map(clean_item, items) if item][:MAX_ITEMS]
    summary = _text(section.get("summary"))
    if not cleaned and not summary:
        return None
    return {
        "key": str(key),
        "title": title,
        "order": order,
        "summary": summary,
        "items": cleaned,
    }


def collect_sections(room, *, staff, viewer=None):
    """Every partner's panel sections for *room*, validated and in display order."""
    raw = collect_dicts(
        collect_tile_detail,
        sender=MapPlane,
        room_id=room.pk,
        room=room,
        viewer=viewer,
        staff=staff,
    )
    sections = [section for key, value in raw.items() if (section := clean_section(key, value))]
    return sorted(sections, key=lambda section: (section["order"], section["key"]))


def room_description(room):
    """The room's description as plain text, cut to a panel-sized excerpt."""
    desc = read_room_attr(room, "desc", default="")
    if not isinstance(desc, str):
        return ""
    text = " ".join(strip_ansi(desc).split())
    return Truncator(text).chars(DESCRIPTION_CHARS)


def _linked(items, template):
    """Popup-link dicts (``{"id", "title"}``) with their page URL filled in."""
    return [
        {
            "id": item["id"],
            "title": item["title"],
            "url": template.replace("/0/", f"/{item['id']}/") if template else "",
        }
        for item in items or []
        if isinstance(item, dict) and "id" in item and "title" in item
    ]


def build_detail(tile, *, staff, viewer=None):
    """
    The panel payload for one placed, visible tile.

    One overlay collect for the single room, then one detail collect: the
    cost of a click does not depend on the size of the plane.
    """
    room = tile.room
    room_id = tile.room_id
    overlays = collect_overlays([room_id], staff=staff, viewer=viewer)
    urls = overlay_url_templates()

    def overlay(key, default):
        return overlays.get(key, {}).get(room_id, default)

    region = overlay("primary_region", None)
    if isinstance(region, dict) and "id" in region:
        region = {
            "id": region["id"],
            "name": region.get("name", ""),
            "url": urls["region"].replace("/0/", f"/{region['id']}/") if "region" in urls else "",
        }
    else:
        region = None

    return {
        "room_id": room_id,
        "room_name": tile.room_name or f"Room #{room_id}",
        "room_url": urls["room"].replace("/0/", f"/{room_id}/") if "room" in urls else "",
        "description": room_description(room),
        "terrain_label": terrain_style(tile.terrain)["label"],
        "hangout_type": read_room_attr(room, "hangout_type", default=None),
        "region": region,
        "present": list(overlay("present", [])),
        "active_scenes": _linked(overlay("active_scenes", []), urls.get("scene", "")),
        "recent_scenes": _linked(overlay("recent_scenes", []), urls.get("scene", "")),
        "upcoming_events": _linked(overlay("upcoming_events", []), urls.get("event", "")),
        "sections": collect_sections(room, staff=staff, viewer=viewer),
    }
