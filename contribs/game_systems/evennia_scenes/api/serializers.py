# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""DRF serializers for evennia_scenes API."""

from rest_framework import serializers

from evennia_scenes.models import LogEntry, Scene


class SceneSerializer(serializers.ModelSerializer):
    """Scene summary including participant and entry counts."""

    participant_count = serializers.SerializerMethodField()
    entry_count = serializers.SerializerMethodField()

    class Meta:
        model = Scene
        fields = [  # noqa: RUF012
            "id",
            "title",
            "description",
            "status",
            "privacy",
            "room_name",
            "creator_name",
            "participant_count",
            "entry_count",
            "created_at",
            "started_at",
            "ended_at",
        ]

    def get_participant_count(self, obj):
        return obj.participants.count()

    def get_entry_count(self, obj):
        return obj.log_entries.filter(is_deleted=False).count()


class LogEntrySerializer(serializers.ModelSerializer):
    """Log entry with scene id and type display."""

    log_type_display = serializers.CharField(source="get_log_type_display", read_only=True)

    class Meta:
        model = LogEntry
        fields = [  # noqa: RUF012
            "id",
            "scene",
            "author_name",
            "content",
            "log_type",
            "log_type_display",
            "order",
            "is_deleted",
            "created_at",
        ]
