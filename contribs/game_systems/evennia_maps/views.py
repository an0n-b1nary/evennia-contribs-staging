# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Website views for evennia_maps. Requires [web] extra.

Read-only views for browsing map planes and the rooms placed on them.

**Privacy.** A map tile exposes an individual room's identity *and its
position*, so tiles for staff-only or secret rooms are dropped for
non-staff visitors via ``permissions.is_room_web_visible()``. Tile
*counts* that would include hidden tiles are staff-only for the same
reason: publishing one tells a visitor exactly how many rooms they are
not being shown. If you also run evennia_regions, point both
``MAPS_ROOM_VISIBILITY`` and ``REGIONS_ROOM_VISIBILITY`` at the same
callable — a room hidden on one surface but named on the other is not
hidden at all.

**The map is a view, not a store.** Everything on a tile beyond its own
coordinates and terrain is aggregated at render time from whichever
partner contribs are installed, through the ``collect_tile_overlays``
seam — see overlays.py. Install none of them and the map still renders;
it just has nothing to say about any tile beyond where it is.

Views:
    PlaneListView    — /map/            paginated list of non-archived planes
    PlaneMapView     — /map/<pk>/       SVG grid of one plane's tiles
    PlaneLiveMapView — /map/<pk>/live/  Leaflet shell; tiles come from the API

``build_svg_context()`` / ``filter_visible_tiles()`` are public on purpose:
a game (or a partner contrib) rendering a mini-map of some subset of tiles
should reuse them rather than restate the privacy filter and the layout
math.

**Query cost.** The per-tile overlay lookups are one bulk pass for the
whole grid, not one per tile — a 500-room plane would otherwise cost
thousands of queries per request. The room *attribute* reads behind
``is_room_web_visible()`` are deliberately left per-room: they resolve
through Evennia's idmapper/AttributeHandler cache, which the webserver
shares with the game process, so they cost a handful of queries per room
only on a cold cache and one for the whole grid once warm. Batching those
would mean reaching into Evennia's Attribute storage directly — the
coupling ``MapsRoomMixin.set_terrain()`` exists to avoid — to fix a cost
that self-heals.
"""

from django.conf import settings
from django.db.models import Count
from django.urls import NoReverseMatch, reverse
from django.views.generic import DetailView, ListView

from evennia_maps.models import MapPlane, RoomTile
from evennia_maps.overlays import collect_overlays, overlay_url_templates
from evennia_maps.permissions import is_room_web_visible, is_staff_user, read_room_attr

TILE_SIZE = 32

DEFAULT_TILES_URL_NAME = "api-plane-tiles"
"""Route name for the DRF tiles action, reversed with a placeholder pk.

The Leaflet page fetches its tiles from the API rather than being handed
server-rendered data, so the privacy branching lives in exactly one place.
Override with ``MAPS_TILES_URL_NAME`` if you mount the API router under a
namespace; set it to ``""`` to turn the live map off. When it does not
resolve, the live page says so instead of rendering an empty canvas.
"""


def filter_visible_tiles(tiles, *, staff):
    """Drop staff-only/secret-room tiles from *tiles* unless *staff*."""
    tiles = list(tiles)
    if staff:
        return tiles
    return [tile for tile in tiles if is_room_web_visible(tile.room)]


def plane_tiles_queryset():
    """
    The canonical tile queryset for a plane, in render order.

    ``-y, x`` so the legend below the grid reads in the same order the grid
    renders: north row first, then west to east.

    Exposed so a caller serializing *many* planes at once (the API's
    ``PlaneViewSet`` list route) can hand the same queryset to
    ``prefetch_related()`` and have ``visible_tiles_for_plane()`` pick the
    cache up, instead of paying one tile query per plane.
    """
    return RoomTile.objects.select_related("room").order_by("-y", "x")


def visible_tiles_for_plane(plane, *, staff):
    """RoomTile list for *plane*, privacy-filtered unless *staff*."""
    cache = getattr(plane, "_prefetched_objects_cache", None) or {}
    if "tiles" in cache:
        tiles = cache["tiles"]
    else:
        tiles = plane.tiles.select_related("room").order_by("-y", "x")
    return filter_visible_tiles(tiles, staff=staff)


def tile_hangout_type(room):
    """
    The room's hangout type, or None.

    Duck-typed exactly as ``terrain_tags`` is: ``hangout_type`` is an
    ``evennia_social.SocialRoomMixin`` attribute, and evennia_maps neither
    depends on nor checks for that contrib. It is the one overlay with no
    table and no privacy rule behind it, which is why it is read here
    rather than collected from its owner like the other five.
    """
    return read_room_attr(room, "hangout_type", default=None)


def tile_sprite(terrain):
    """Sprite URL for a resolved terrain key, or an empty string for the fallback swatch."""
    # getattr, not settings.MAPS_TERRAIN_TILESET: a host game need not
    # define it, matching terrain.py's handling of MAPS_TERRAIN_PRECEDENCE.
    return getattr(settings, "MAPS_TERRAIN_TILESET", {}).get(terrain, "")


def tiles_url_template():
    """The tiles endpoint reversed with a placeholder pk, or "" if unmounted."""
    name = getattr(settings, "MAPS_TILES_URL_NAME", DEFAULT_TILES_URL_NAME)
    if not name:
        return ""
    try:
        return reverse(name, args=[0])
    except NoReverseMatch:
        return ""


def _url_for(template, obj_id):
    """Substitute a real pk into a URL reversed with a ``0`` placeholder."""
    return template.replace("/0/", f"/{obj_id}/") if template else ""


def _build_tile_context(tile, overlays, urls):
    """Render a RoomTile into the dict the SVG partial iterates over."""
    room = tile.room
    region = overlays.get("primary_region", {}).get(tile.room_id)
    recent_scenes = overlays.get("recent_scenes", {}).get(tile.room_id) or []
    # The SVG legend links one recent log per tile; the Leaflet popup lists
    # the whole set. Both come from the same single overlay query.
    latest_scene = recent_scenes[0] if recent_scenes else None
    return {
        "x": tile.x,
        "y": tile.y,
        "room_id": tile.room_id,
        "room_name": tile.room_name or (room.key if room else f"Room #{tile.room_id}"),
        "terrain": tile.terrain,
        "sprite": tile_sprite(tile.terrain),
        "region": region,
        "region_url": _url_for(urls.get("region", ""), region["id"]) if region else "",
        "latest_scene": latest_scene,
        "latest_scene_url": (
            _url_for(urls.get("scene", ""), latest_scene["id"]) if latest_scene else ""
        ),
    }


def build_svg_context(tiles, *, staff=False, tile_size=TILE_SIZE, padding=1):
    """
    Shared layout math for the SVG grid: bounding box + per-tile context.

    One overlay pass for the whole grid regardless of tile count — see the
    module docstring on query cost.

    Returns None if *tiles* is empty, so the caller can show an empty state
    rather than a blank ``<svg>``.
    """
    if not tiles:
        return None
    room_ids = [tile.room_id for tile in tiles]
    overlays = collect_overlays(room_ids, staff=staff)
    urls = overlay_url_templates()
    rendered = [_build_tile_context(tile, overlays, urls) for tile in tiles]
    xs = [t["x"] for t in rendered]
    ys = [t["y"] for t in rendered]
    min_x, max_x = min(xs) - padding, max(xs) + padding
    min_y, max_y = min(ys) - padding, max(ys) + padding
    for t in rendered:
        # SVG y grows downward; flip so north (+y) renders up.
        t["svg_x"] = (t["x"] - min_x) * tile_size
        t["svg_y"] = (max_y - t["y"]) * tile_size
    return {
        "tiles": rendered,
        "tile_size": tile_size,
        "svg_width": (max_x - min_x + 1) * tile_size,
        "svg_height": (max_y - min_y + 1) * tile_size,
    }


class PlaneListView(ListView):
    """Paginated list of all non-archived map planes."""

    model = MapPlane
    template_name = "evennia_maps/plane_list.html"
    context_object_name = "planes"
    paginate_by = 25

    def get_queryset(self):
        queryset = MapPlane.objects.filter(is_archived=False).order_by("name")
        if is_staff_user(self.request):
            # Annotated rather than counted per row in the template, which
            # would be one query per plane.
            queryset = queryset.annotate(tile_count=Count("tiles"))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Map"
        # Staff-only: a raw plane.tiles.count() includes tiles the privacy
        # filter hides, so publishing it would tell a player exactly how
        # many secret/staff rooms a plane holds — the existence fact the
        # filter is there to withhold. Staff see every tile anyway, so for
        # them the count is both accurate and free.
        context["show_tile_counts"] = is_staff_user(self.request)
        return context


class PlaneMapView(DetailView):
    """SVG grid of one plane's placed rooms, privacy-filtered."""

    model = MapPlane
    template_name = "evennia_maps/plane_map.html"
    context_object_name = "plane"

    def get_queryset(self):
        return MapPlane.objects.filter(is_archived=False)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.object.name
        staff = is_staff_user(self.request)
        tiles = visible_tiles_for_plane(self.object, staff=staff)
        context["svg"] = build_svg_context(tiles, staff=staff)
        context["tile_count"] = len(tiles)
        # No link to a live map the game has not mounted the API for.
        context["has_live_map"] = bool(tiles_url_template())
        return context


class PlaneLiveMapView(DetailView):
    """
    Leaflet dynamic map for one plane.

    Renders an empty container; the JS pulls tiles from the API
    client-side, so the staff-vs-player branching applies there rather than
    here — this view supplies only the sibling-elevation list for the layer
    control and the outbound link templates.
    """

    model = MapPlane
    template_name = "evennia_maps/plane_live_map.html"
    context_object_name = "plane"

    def get_queryset(self):
        return MapPlane.objects.filter(is_archived=False)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        plane = self.object
        context["page_title"] = f"{plane.name} (live)"
        if plane.zstack:
            siblings = MapPlane.objects.filter(zstack=plane.zstack, is_archived=False).order_by(
                "-elevation"
            )
        else:
            siblings = [plane]
        context["layers"] = [
            {
                "id": sibling.pk,
                "name": sibling.name,
                "elevation": sibling.elevation,
                "is_current": sibling.pk == plane.pk,
            }
            for sibling in siblings
        ]
        context["tiles_url_template"] = tiles_url_template()
        # Outbound links for popups. An absent role renders no link at all —
        # the partner contrib that owns that page is not installed.
        urls = overlay_url_templates()
        context["region_url_template"] = urls.get("region", "")
        context["scene_url_template"] = urls.get("scene", "")
        context["event_url_template"] = urls.get("event", "")
        return context
