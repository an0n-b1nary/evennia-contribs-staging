# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""DRF viewsets for the evennia_maps API. Requires [web] extra.

Self-contained: explicit pagination/auth/permission/filter classes.
Does not rely on the consumer's global REST_FRAMEWORK configuration.
"""

from django.db.models import Prefetch
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ReadOnlyModelViewSet

from evennia_maps.api.filters import PlaneFilter
from evennia_maps.api.pagination import MapsCursorPagination, TilePagination
from evennia_maps.api.serializers import PlaneSerializer, RoomTileSerializer
from evennia_maps.models import MapPlane, RoomTile
from evennia_maps.overlays import collect_overlays
from evennia_maps.permissions import is_room_web_visible, is_staff_user
from evennia_maps.views import (
    plane_tiles_queryset,
    tile_hangout_type,
    tile_sprite,
    visible_tiles_for_plane,
)


def portal_target_planes_by_room(room_ids, *, exclude_plane_id, staff):
    """
    room_id -> destination MapPlane id, for rooms with an exit onto a
    different, standalone (``zstack=""``) plane whose destination room is
    itself visible to the caller.

    Portals are geometry-inferred, not an in-game concept: a tile's own
    exits are the only signal. Two bulk queries (exits, then destination
    tiles) rather than a per-room ``room.exits()`` walk, since exits are
    ordinary ObjectDB rows — ``db_destination`` is Evennia's own exit
    marker — and don't need the idmapper/Attribute path the terrain and
    privacy reads do.

    The destination room's own visibility is still checked (one attribute
    read per candidate destination): a portal marker naming an otherwise
    hidden interior would undo ``is_room_web_visible()`` by the back door.

    Archived planes are excluded, because ``PlaneViewSet`` hides them and a
    marker pointing at one would navigate to a 404.
    """
    if not room_ids:
        return {}
    from evennia.objects.models import ObjectDB

    exit_rows = list(
        ObjectDB.objects.filter(
            db_location_id__in=room_ids, db_destination__isnull=False
        ).values_list("db_location_id", "db_destination_id")
    )
    if not exit_rows:
        return {}
    dest_room_ids = {dest_id for _, dest_id in exit_rows}
    dest_tiles = (
        RoomTile.objects.filter(
            room_id__in=dest_room_ids, plane__zstack="", plane__is_archived=False
        )
        .exclude(plane_id=exclude_plane_id)
        .select_related("room")
    )
    dest_plane_by_room = {}
    for tile in dest_tiles:
        if not staff and not is_room_web_visible(tile.room):
            continue
        dest_plane_by_room[tile.room_id] = tile.plane_id
    if not dest_plane_by_room:
        return {}
    result = {}
    for source_room_id, dest_room_id in exit_rows:
        target_plane_id = dest_plane_by_room.get(dest_room_id)
        if target_plane_id is not None:
            result.setdefault(source_room_id, target_plane_id)
    return result


class PlaneViewSet(ReadOnlyModelViewSet):
    """
    Non-archived map planes, plus a nested tiles endpoint.

    Filtering:
        name=<partial>
        zstack=<exact>
    """

    serializer_class = PlaneSerializer
    filterset_class = PlaneFilter
    ordering_fields = ["name", "zstack", "elevation"]  # noqa: RUF012
    ordering = ["name"]  # noqa: RUF012

    authentication_classes = [SessionAuthentication]  # noqa: RUF012
    permission_classes = [IsAuthenticated]  # noqa: RUF012
    pagination_class = MapsCursorPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]  # noqa: RUF012

    def get_queryset(self):
        # PlaneSerializer.bounds walks each plane's visible tiles, so a list
        # page would otherwise cost one tile query per plane. Prefetching
        # the canonical tile queryset makes it one query for the whole page;
        # visible_tiles_for_plane() reads the cache when it is populated.
        return (
            MapPlane.objects.filter(is_archived=False)
            .prefetch_related(Prefetch("tiles", queryset=plane_tiles_queryset()))
            .order_by("name")
        )

    @action(detail=True, methods=["get"], url_path="tiles")
    def tiles(self, request, pk=None):
        """
        Paginated, privacy-filtered tiles for this plane.

        Staff see every tile; non-staff never see a staff-only or secret
        room, via the same ``is_room_web_visible()`` predicate the SVG map
        uses — see evennia_maps.views.

        Overlays are collected in **one** signal send for the whole plane,
        never per tile. Each provider answers under its own privacy rule
        and a provider that raises simply contributes nothing; see
        evennia_maps/overlays.py.
        """
        plane = self.get_object()
        staff = is_staff_user(request)
        tiles = visible_tiles_for_plane(plane, staff=staff)

        room_ids = [tile.room_id for tile in tiles]
        portal_by_room = portal_target_planes_by_room(
            room_ids, exclude_plane_id=plane.pk, staff=staff
        )
        overlays = collect_overlays(room_ids, staff=staff)
        primary_region = overlays.get("primary_region", {})
        has_active_scene = overlays.get("has_active_scene", {})
        recent_scene_counts = overlays.get("recent_scene_count", {})
        recent_scenes_by_room = overlays.get("recent_scenes", {})
        has_lore = overlays.get("has_lore", {})
        upcoming_events_by_room = overlays.get("upcoming_events", {})

        data = [
            {
                "x": tile.x,
                "y": tile.y,
                "room_id": tile.room_id,
                "room_name": tile.room_name or f"Room #{tile.room_id}",
                "terrain": tile.terrain,
                "sprite_url": tile_sprite(tile.terrain),
                "portal_plane_id": portal_by_room.get(tile.room_id),
                "hangout_type": tile_hangout_type(tile.room),
                "primary_region_id": (primary_region.get(tile.room_id) or {}).get("id"),
                "has_active_scene": bool(has_active_scene.get(tile.room_id, False)),
                "recent_scene_count": recent_scene_counts.get(tile.room_id, 0),
                "has_lore": bool(has_lore.get(tile.room_id, False)),
                "recent_scenes": recent_scenes_by_room.get(tile.room_id, []),
                "upcoming_events": upcoming_events_by_room.get(tile.room_id, []),
            }
            for tile in tiles
        ]

        paginator = TilePagination()
        page = paginator.paginate_queryset(data, request)
        serializer = RoomTileSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)
