# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""DRF viewsets for evennia_xp API.

Self-contained: explicit pagination/auth/permission/filter classes.
Does not rely on the consumer's global REST_FRAMEWORK configuration.
"""

from rest_framework.authentication import SessionAuthentication
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ReadOnlyModelViewSet

from evennia_xp.api.pagination import XPCursorPagination
from evennia_xp.api.serializers import XPLogSerializer
from evennia_xp.models import XPLog
from evennia_xp.permissions import get_character_id


class XPLogViewSet(ReadOnlyModelViewSet):
    """XP award log for the requesting character only.

    Returns only rows owned by the authenticated user's active character.
    No staff browse surface — use Django admin for cross-character queries.
    """

    serializer_class = XPLogSerializer
    ordering_fields = ["awarded_at", "week", "amount"]  # noqa: RUF012
    ordering = ["-awarded_at"]  # noqa: RUF012

    authentication_classes = [SessionAuthentication]  # noqa: RUF012
    permission_classes = [IsAuthenticated]  # noqa: RUF012
    pagination_class = XPCursorPagination
    filter_backends = [OrderingFilter]  # noqa: RUF012

    def get_queryset(self):
        character_id = get_character_id(self.request.user)
        if not character_id:
            return XPLog.objects.none()
        return XPLog.objects.filter(character_id=character_id).order_by("-awarded_at")
