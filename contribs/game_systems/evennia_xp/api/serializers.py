# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""DRF serializers for evennia_xp API."""

from rest_framework import serializers

from evennia_xp.models import XPLog


class XPLogSerializer(serializers.ModelSerializer):
    source_type_display = serializers.CharField(source="get_source_type_display", read_only=True)

    class Meta:
        model = XPLog
        fields = [  # noqa: RUF012
            "id",
            "character_id",
            "source_type",
            "source_type_display",
            "source_ref_id",
            "amount",
            "week",
            "reason",
            "granted_by_name",
            "awarded_at",
        ]
