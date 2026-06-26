# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
DRF viewsets for evennia_calendar. Requires [web] extra.

Endpoints::

    /api/v1/events/            CalendarEventViewSet (list + detail)

All endpoints require authentication (SessionAuthentication + IsAuthenticated).
Privacy filtering: cancelled events are excluded.
"""

from rest_framework.viewsets import ReadOnlyModelViewSet

from evennia_calendar.api.filters import CalendarEventFilter
from evennia_calendar.api.pagination import CalendarCursorPagination
from evennia_calendar.api.serializers import CalendarEventSerializer
from evennia_calendar.models import CalendarEvent


class CalendarEventViewSet(ReadOnlyModelViewSet):
    """
    Non-cancelled calendar events.

    Filtering:
        after=YYYY-MM-DDTHH:MM:SS
        before=YYYY-MM-DDTHH:MM:SS
        emphasis=combat|skill|social|freeform
        is_staff_event=true|false
    """

    serializer_class = CalendarEventSerializer
    filterset_class = CalendarEventFilter
    pagination_class = CalendarCursorPagination
    ordering_fields = ["scheduled_time", "created_at"]  # noqa: RUF012
    ordering = ["scheduled_time"]  # noqa: RUF012

    def get_queryset(self):
        return CalendarEvent.objects.filter(is_cancelled=False).order_by("scheduled_time")
