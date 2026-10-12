# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""DRF serializers for the evennia_plots API.

A PlotThread is what players call a plot; a StoryThread is a thread in it.
Thread sealed answers are never serialized, sealed or revealed, for anyone.
"""

from rest_framework import serializers

from evennia_plots.models import PlotTag, PlotThread, StoryThread


class PlotTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlotTag
        fields = ["id", "name", "is_major"]  # noqa: RUF012


class StoryThreadSerializer(serializers.ModelSerializer):
    ref = serializers.CharField(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    lead_count = serializers.SerializerMethodField()

    class Meta:
        model = StoryThread
        fields = [  # noqa: RUF012
            "number",
            "ref",
            "title",
            "detail",
            "status",
            "status_display",
            "is_held",
            "resolution",
            "lead_count",
        ]

    def get_lead_count(self, obj):
        return sum(1 for interest in obj.interests.all() if interest.is_lead)


# Requests and declined requests stay on the plot page, for owners and the
# requester; the API lists only threads the plot actually took up.
_LISTED_THREAD_STATUSES = (
    StoryThread.Status.OPEN,
    StoryThread.Status.RESOLVED,
    StoryThread.Status.DROPPED,
    StoryThread.Status.LOOSE_END,
    StoryThread.Status.CARRIED,
)


class PlotThreadSerializer(serializers.ModelSerializer):
    tags = PlotTagSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    owners = serializers.SerializerMethodField()
    threads = serializers.SerializerMethodField()

    class Meta:
        model = PlotThread
        fields = [  # noqa: RUF012
            "id",
            "plot_number",
            "name",
            "description",
            "status",
            "status_display",
            "privacy",
            "thread_policy",
            "creator_name",
            "owners",
            "tags",
            "threads",
            "created_at",
        ]

    def get_owners(self, obj):
        return [owner.character_name for owner in obj.owners.all()]

    def get_threads(self, obj):
        threads = [t for t in obj.story_threads.all() if t.status in _LISTED_THREAD_STATUSES]
        return StoryThreadSerializer(threads, many=True).data
