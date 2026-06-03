# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Cursor pagination for evennia_xp API viewsets."""

from rest_framework.pagination import CursorPagination


class XPCursorPagination(CursorPagination):
    page_size = 50
    ordering = "-awarded_at"
    page_size_query_param = "page_size"
    max_page_size = 200
