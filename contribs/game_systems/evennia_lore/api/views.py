# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""DRF viewsets for evennia_lore API.

Self-contained: explicit pagination/auth/permission/filter classes.
Does not rely on the consumer's global REST_FRAMEWORK configuration.
"""

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.authentication import SessionAuthentication
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ReadOnlyModelViewSet

from evennia_lore.api.filters import LoreEntryFilter, LoreTagFilter
from evennia_lore.api.pagination import LoreCursorPagination
from evennia_lore.api.serializers import LoreEntrySerializer, LoreTagSerializer
from evennia_lore.models import LoreEntry, LoreTag
from evennia_lore.permissions import is_staff_user


class LoreTagViewSet(ReadOnlyModelViewSet):
    """All lore tags. Filter by ?name=<partial> or ?is_major=true|false."""

    serializer_class = LoreTagSerializer
    filterset_class = LoreTagFilter
    ordering_fields = ["name", "created_at"]  # noqa: RUF012
    ordering = ["name"]  # noqa: RUF012

    authentication_classes = [SessionAuthentication]  # noqa: RUF012
    permission_classes = [IsAuthenticated]  # noqa: RUF012
    pagination_class = LoreCursorPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]  # noqa: RUF012

    def get_queryset(self):
        return LoreTag.objects.all().order_by("name")


class LoreEntryViewSet(ReadOnlyModelViewSet):
    """
    Published lore entries. RESTRICTED body is hidden unless the caller has
    an acquisition row or is staff.

    Filtering: ?tag=<partial>, ?privacy=public|restricted,
               ?status=published|submitted|draft|rejected (staff only),
               ?region=<id>
    """

    serializer_class = LoreEntrySerializer
    filterset_class = LoreEntryFilter
    ordering_fields = ["entry_number", "created_at", "updated_at"]  # noqa: RUF012
    ordering = ["-created_at"]  # noqa: RUF012

    authentication_classes = [SessionAuthentication]  # noqa: RUF012
    permission_classes = [IsAuthenticated]  # noqa: RUF012
    pagination_class = LoreCursorPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]  # noqa: RUF012

    def get_queryset(self):
        if is_staff_user(self.request):
            return (
                LoreEntry.objects.filter(is_archived=False)
                .prefetch_related("tags")
                .order_by("-created_at")
            )
        return (
            LoreEntry.objects.filter(status=LoreEntry.Status.PUBLISHED, is_archived=False)
            .prefetch_related("tags")
            .order_by("-created_at")
        )
