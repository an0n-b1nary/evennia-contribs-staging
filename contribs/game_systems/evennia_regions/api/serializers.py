# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""DRF serializers for evennia_regions API. Requires [web] extra."""

from rest_framework import serializers

from evennia_regions.models import Region
from evennia_regions.permissions import is_staff_user


class RegionSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Region
        fields = [  # noqa: RUF012
            "id",
            "name",
            "description",
            "created_by_name",
            "created_at",
            "member_count",
        ]

    def get_member_count(self, obj):
        # None for non-staff: the raw count includes rooms the region page
        # withholds from players (see permissions.is_room_web_visible), so
        # publishing it tells them how many rooms they are not being shown.
        # Nulled rather than dropped so the response shape stays stable.
        request = self.context.get("request")
        if request is None or not is_staff_user(request):
            return None
        return obj.member_count()
