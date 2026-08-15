# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Pagination for evennia_maps API viewsets."""

from rest_framework.pagination import CursorPagination, PageNumberPagination


class MapsCursorPagination(CursorPagination):
    page_size = 20
    ordering = "name"
    page_size_query_param = "page_size"
    max_page_size = 100


class TilePagination(PageNumberPagination):
    """
    Page-number pagination for ``PlaneViewSet.tiles()``.

    Tile visibility is filtered in Python — room privacy lives in Evennia
    Attributes, not database columns (see
    ``evennia_maps.permissions.is_room_web_visible``) — so the tiles
    endpoint paginates a plain list of dicts rather than a queryset.
    ``CursorPagination`` can't: it slices via a SQL ``ORDER BY`` on its
    input, which a Python-filtered list has no way to provide. Django's
    ``Paginator`` (what ``PageNumberPagination`` wraps) works over any
    sequence supporting ``len()`` and slicing, a list included.

    The page size is large because the Leaflet frontend walks every page to
    draw a complete plane, and each extra page is another round trip.
    """

    page_size = 200
    page_size_query_param = "page_size"
    max_page_size = 500
