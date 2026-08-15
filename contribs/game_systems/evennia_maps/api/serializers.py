# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""DRF serializers for the evennia_maps API. Requires [web] extra."""

from rest_framework import serializers

from evennia_maps.models import MapPlane
from evennia_maps.permissions import is_staff_user
from evennia_maps.views import visible_tiles_for_plane


class PlaneSerializer(serializers.ModelSerializer):
    bounds = serializers.SerializerMethodField()

    class Meta:
        model = MapPlane
        fields = ["id", "name", "zstack", "elevation", "bounds"]  # noqa: RUF012

    def get_bounds(self, obj):
        # Bounds are computed from the *visible* tile set, not every tile —
        # a bounding box that hugs staff-only rooms would leak their extent
        # to a player who can never see them. None when nothing is visible,
        # so the frontend can fall back to a default viewport.
        request = self.context.get("request")
        tiles = visible_tiles_for_plane(obj, staff=is_staff_user(request))
        if not tiles:
            return None
        xs = [tile.x for tile in tiles]
        ys = [tile.y for tile in tiles]
        return {"min_x": min(xs), "max_x": max(xs), "min_y": min(ys), "max_y": max(ys)}


class MapPopupLinkSerializer(serializers.Serializer):
    """
    One clickable entry in a map tile's popup list.

    The title is resolved server-side, including its fallback, by whichever
    contrib owns the linked object — so the map frontend never has to know
    how a scene or a calendar event names itself.
    """

    id = serializers.IntegerField()
    title = serializers.CharField()


class RoomTileSerializer(serializers.Serializer):
    """
    Serializes the plain dicts built by ``PlaneViewSet.tiles()``, not
    ``RoomTile`` instances directly — the payload blends denormalized tile
    fields with values collected from partner contribs and from exit
    geometry at the view layer.

    Every overlay field is present in the response whether or not any
    contrib provides it, at its empty value. A frontend keyed off the
    presence of a field would otherwise have to care which contribs the
    game installed.
    """

    x = serializers.IntegerField()
    y = serializers.IntegerField()
    room_id = serializers.IntegerField()
    room_name = serializers.CharField()
    terrain = serializers.CharField()
    sprite_url = serializers.CharField()
    # Geometry-inferred portal: set when this room has an exit onto a
    # different, standalone (zstack="") plane. There is no in-game portal
    # concept — this is a rendering-layer interpretation of the exits.
    portal_plane_id = serializers.IntegerField(allow_null=True)
    # Read locally: a bare room attribute with no privacy rule.
    hangout_type = serializers.CharField(allow_null=True)
    # Collected through collect_tile_overlays — each one queried by the
    # contrib that owns it, under that contrib's own privacy rule. See
    # evennia_maps/overlays.py.
    primary_region_id = serializers.IntegerField(allow_null=True)
    has_active_scene = serializers.BooleanField()
    recent_scene_count = serializers.IntegerField()
    has_lore = serializers.BooleanField()
    recent_scenes = MapPopupLinkSerializer(many=True)
    upcoming_events = MapPopupLinkSerializer(many=True)
