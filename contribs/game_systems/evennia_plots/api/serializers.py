# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""DRF serializers for the evennia_plots API."""

from rest_framework import serializers

from evennia_plots.models import PlotTag, PlotThread


class PlotTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlotTag
        fields = ["id", "name", "is_major"]  # noqa: RUF012


class PlotThreadSerializer(serializers.ModelSerializer):
    tags = PlotTagSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

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
            "creator_name",
            "tags",
            "created_at",
        ]
