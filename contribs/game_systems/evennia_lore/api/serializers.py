# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""DRF serializers for evennia_lore API."""

from rest_framework import serializers

from evennia_lore.models import LoreAcquisition, LoreEntry, LoreTag
from evennia_lore.permissions import get_character_id, is_staff_user


def _is_staff(request):
    return is_staff_user(request) if request else False


class LoreTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoreTag
        fields = ["id", "name", "is_major", "created_by_name", "created_at"]  # noqa: RUF012


class LoreEntrySerializer(serializers.ModelSerializer):
    tags = LoreTagSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    privacy_display = serializers.CharField(source="get_privacy_display", read_only=True)
    body = serializers.SerializerMethodField()

    class Meta:
        model = LoreEntry
        fields = [  # noqa: RUF012
            "id",
            "entry_number",
            "title",
            "summary",
            "body",
            "status",
            "status_display",
            "privacy",
            "privacy_display",
            "author_name",
            "tags",
            "created_at",
            "updated_at",
        ]

    def get_body(self, obj):
        request = self.context.get("request")
        if obj.privacy == LoreEntry.Privacy.PUBLIC:
            return obj.body
        if request is None or not request.user.is_authenticated:
            return None
        if _is_staff(request):
            return obj.body
        char_id = get_character_id(request.user)
        if not char_id:
            return None
        if LoreAcquisition.objects.filter(entry=obj, character_id=char_id).exists():
            return obj.body
        return None
