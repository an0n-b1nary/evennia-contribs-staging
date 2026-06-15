# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
DRF viewsets for evennia_scenes API.

Authentication: SessionAuthentication (explicit — does not rely on global
REST_FRAMEWORK defaults). Requires IsAuthenticated.

SceneViewSet is read-only. Scenes can be filtered by status with
?status=<value>. Log entries for a scene are accessible at
/api/v1/scenes/<pk>/log/.
"""

from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ReadOnlyModelViewSet

from evennia_scenes.api.pagination import ScenesCursorPagination
from evennia_scenes.api.serializers import LogEntrySerializer, SceneSerializer
from evennia_scenes.models import LogEntry, Scene


class SceneViewSet(ReadOnlyModelViewSet):
    """Closed public scenes.

    Only PUBLIC and POSE_PRIVATE scenes are exposed in the API.
    VIEW_PRIVATE scenes are excluded to avoid leaking sensitive content to
    unauthenticated or uninvited observers.

    Usage::

        /api/v1/scenes/
        /api/v1/scenes/<pk>/
        /api/v1/scenes/<pk>/log/
        /api/v1/scenes/?status=closed
        /api/v1/scenes/?status=active
    """

    serializer_class = SceneSerializer
    authentication_classes = [SessionAuthentication]  # noqa: RUF012
    permission_classes = [IsAuthenticated]  # noqa: RUF012
    pagination_class = ScenesCursorPagination
    filter_backends = [OrderingFilter]  # noqa: RUF012
    ordering_fields = ["created_at", "ended_at"]  # noqa: RUF012
    ordering = ["-created_at"]  # noqa: RUF012

    def get_queryset(self):
        qs = Scene.objects.filter(privacy__in=[Scene.Privacy.PUBLIC, Scene.Privacy.POSE_PRIVATE])
        status = self.request.query_params.get("status")
        qs = qs.filter(status=status) if status else qs.filter(status=Scene.Status.CLOSED)
        return qs

    @action(detail=True, url_path="log", url_name="log")
    def log(self, request, pk=None):
        """Return paginated log entries for this scene."""
        scene = self.get_object()
        qs = LogEntry.objects.filter(scene=scene, is_deleted=False).order_by("order", "created_at")
        log_type = request.query_params.get("log_type")
        if log_type:
            qs = qs.filter(log_type=log_type)

        paginator = ScenesCursorPagination()
        paginator.ordering = "order"
        page = paginator.paginate_queryset(qs, request)
        serializer = LogEntrySerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)
