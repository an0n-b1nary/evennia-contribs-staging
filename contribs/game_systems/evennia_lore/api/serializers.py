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
    kind_display = serializers.CharField(source="kind_label", read_only=True)
    accuracy = serializers.SerializerMethodField()
    ooc_notes = serializers.SerializerMethodField()
    affirmation = serializers.SerializerMethodField()
    edited_since_affirmation = serializers.BooleanField(read_only=True)
    has_sealed_notes = serializers.BooleanField(read_only=True)

    class Meta:
        model = LoreEntry
        fields = [  # noqa: RUF012
            "id",
            "entry_number",
            "title",
            "summary",
            "body",
            "kind",
            "kind_display",
            "accuracy",
            "ooc_notes",
            "affirmation",
            "edited_since_affirmation",
            "has_sealed_notes",
            "status",
            "status_display",
            "privacy",
            "privacy_display",
            "author_name",
            "tags",
            "created_at",
            "updated_at",
        ]

    def _body_visible(self, obj):
        request = self.context.get("request")
        if obj.privacy == LoreEntry.Privacy.PUBLIC:
            return True
        if request is None or not request.user.is_authenticated:
            return False
        if _is_staff(request):
            return True
        char_id = get_character_id(request.user)
        if not char_id:
            return False
        return LoreAcquisition.objects.filter(entry=obj, character_id=char_id).exists()

    def get_body(self, obj):
        return obj.body if self._body_visible(obj) else None

    # The OOC layer follows the IC content: null wherever the body is.
    def get_accuracy(self, obj):
        return obj.accuracy if self._body_visible(obj) else None

    def get_ooc_notes(self, obj):
        return obj.ooc_notes if self._body_visible(obj) else None

    def get_affirmation(self, obj):
        """A decline reads as "none" to everyone but the author and staff."""
        request = self.context.get("request")
        if obj.affirmation != LoreEntry.Affirmation.DECLINED or request is None:
            return obj.public_affirmation()
        if _is_staff(request):
            return obj.affirmation
        char_id = get_character_id(request.user) if request.user.is_authenticated else None
        if char_id and obj.author_id == char_id:
            return obj.affirmation
        return obj.public_affirmation()
