# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""DRF viewsets for evennia_regions API. Requires [web] extra.

Self-contained: explicit pagination/auth/permission/filter classes.
Does not rely on the consumer's global REST_FRAMEWORK configuration.
"""

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.authentication import SessionAuthentication
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ReadOnlyModelViewSet

from evennia_regions.api.filters import RegionFilter
from evennia_regions.api.pagination import RegionsCursorPagination
from evennia_regions.api.serializers import RegionSerializer
from evennia_regions.models import Region


class RegionViewSet(ReadOnlyModelViewSet):
    """Non-archived regions. Filter by ?name=<partial>."""

    serializer_class = RegionSerializer
    filterset_class = RegionFilter
    ordering_fields = ["name", "created_at"]  # noqa: RUF012
    ordering = ["name"]  # noqa: RUF012

    authentication_classes = [SessionAuthentication]  # noqa: RUF012
    permission_classes = [IsAuthenticated]  # noqa: RUF012
    pagination_class = RegionsCursorPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]  # noqa: RUF012

    def get_queryset(self):
        return Region.objects.filter(is_archived=False).order_by("name")
