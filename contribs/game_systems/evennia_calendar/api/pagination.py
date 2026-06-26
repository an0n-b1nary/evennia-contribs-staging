# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Cursor pagination for evennia_calendar API viewsets."""

from rest_framework.pagination import CursorPagination


class CalendarCursorPagination(CursorPagination):
    page_size = 20
    ordering = "scheduled_time"
    page_size_query_param = "page_size"
    max_page_size = 100
