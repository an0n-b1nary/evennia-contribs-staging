# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
DRF viewsets for the evennia_plots API.

Authentication: SessionAuthentication (explicit — does not rely on global
REST_FRAMEWORK defaults). Requires IsAuthenticated.

Routes:
    GET /api/v1/plots/       PlotThreadViewSet list
    GET /api/v1/plots/<pk>/  PlotThreadViewSet detail

Filtering:
    tag=<partial name>
    status=active|proposed|concluded|archived
"""

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.authentication import SessionAuthentication
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ReadOnlyModelViewSet

from evennia_plots.api.filters import PlotThreadFilter
from evennia_plots.api.pagination import PlotsCursorPagination
from evennia_plots.api.serializers import PlotThreadSerializer
from evennia_plots.models import PlotThread
from evennia_plots.permissions import is_staff_user


class PlotThreadViewSet(ReadOnlyModelViewSet):
    """Active public and invite-only plot threads.

    Staff see all threads regardless of status or privacy.

    Filtering:
        tag=<partial name>
        status=active|proposed|concluded|archived
    """

    serializer_class = PlotThreadSerializer
    authentication_classes = [SessionAuthentication]  # noqa: RUF012
    permission_classes = [IsAuthenticated]  # noqa: RUF012
    pagination_class = PlotsCursorPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]  # noqa: RUF012
    filterset_class = PlotThreadFilter
    ordering_fields = ["created_at", "plot_number"]  # noqa: RUF012
    ordering = ["-created_at"]  # noqa: RUF012

    def get_queryset(self):
        if is_staff_user(self.request):
            return PlotThread.objects.prefetch_related("tags").order_by("-created_at")
        return (
            PlotThread.objects.filter(
                status=PlotThread.Status.ACTIVE,
                privacy__in=[PlotThread.Privacy.PUBLIC, PlotThread.Privacy.INVITE_ONLY],
            )
            .prefetch_related("tags")
            .order_by("-created_at")
        )
