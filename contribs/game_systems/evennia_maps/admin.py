# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django admin registration for evennia_maps."""

from django.contrib import admin

from evennia_maps.models import MapPlane, RoomTile


@admin.register(MapPlane)
class MapPlaneAdmin(admin.ModelAdmin):
    list_display = [  # noqa: RUF012
        "name",
        "zstack",
        "elevation",
        "created_by_name",
        "created_at",
        "is_archived",
    ]
    list_filter = ["zstack", "is_archived"]  # noqa: RUF012
    search_fields = ["name", "description"]  # noqa: RUF012
    readonly_fields = ["created_at", "archived_at"]  # noqa: RUF012


@admin.register(RoomTile)
class RoomTileAdmin(admin.ModelAdmin):
    list_display = ["room_name", "plane", "x", "y", "pinned", "terrain", "updated_at"]  # noqa: RUF012
    list_filter = ["plane", "pinned"]  # noqa: RUF012
    search_fields = ["room_name", "terrain"]  # noqa: RUF012
    readonly_fields = ["updated_at"]  # noqa: RUF012
