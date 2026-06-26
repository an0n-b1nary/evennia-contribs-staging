# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""django-filter FilterSet for the evennia_calendar REST API. Requires [web] extra."""

import django_filters

from evennia_calendar.models import CalendarEvent


class CalendarEventFilter(django_filters.FilterSet):
    after = django_filters.DateTimeFilter(field_name="scheduled_time", lookup_expr="gte")
    before = django_filters.DateTimeFilter(field_name="scheduled_time", lookup_expr="lte")
    emphasis = django_filters.CharFilter(field_name="emphasis", lookup_expr="exact")
    is_staff_event = django_filters.BooleanFilter(field_name="is_staff_event")

    class Meta:
        model = CalendarEvent
        fields = ["emphasis", "is_staff_event"]  # noqa: RUF012
