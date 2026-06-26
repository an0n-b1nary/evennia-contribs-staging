# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""DRF serializers for evennia_calendar API. Requires [web] extra."""

from rest_framework import serializers

from evennia_calendar.models import CalendarEvent


class CalendarEventSerializer(serializers.ModelSerializer):
    emphasis_display = serializers.CharField(source="get_emphasis_display", read_only=True)
    cluster_title = serializers.SerializerMethodField()

    class Meta:
        model = CalendarEvent
        fields = [  # noqa: RUF012
            "id",
            "title",
            "description",
            "scheduled_time",
            "emphasis",
            "emphasis_display",
            "creator_name",
            "is_staff_event",
            "is_cancelled",
            "cluster",
            "cluster_title",
        ]

    def get_cluster_title(self, obj):
        return obj.cluster.title if obj.cluster_id else None
