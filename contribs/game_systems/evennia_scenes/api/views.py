# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
DRF viewsets for evennia_scenes API.

Authentication: SessionAuthentication (explicit — does not rely on global
REST_FRAMEWORK defaults). Requires IsAuthenticated.

SceneViewSet is read-only. Scenes can be filtered by status with
?status=<value> and by creation time with ?created_after= / ?created_before=
(ISO 8601 date or datetime, inclusive). Log entries for a scene are accessible
at /api/v1/scenes/<pk>/log/.
"""

from datetime import datetime, time

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ReadOnlyModelViewSet

from evennia_scenes.api.pagination import ScenesCursorPagination
from evennia_scenes.api.serializers import LogEntrySerializer, SceneSerializer
from evennia_scenes.models import LogEntry, Scene


class SceneViewSet(ReadOnlyModelViewSet):
    """Public scenes: the default list is the archive; details may be live.

    Only web-readable tiers (Scene.WEB_READABLE_PRIVACY — PUBLIC and
    POSE_PRIVATE) are exposed in the API. Every other tier is excluded to
    avoid leaking sensitive content to unauthenticated or uninvited
    observers.

    Usage::

        /api/v1/scenes/
        /api/v1/scenes/<pk>/
        /api/v1/scenes/<pk>/log/
        /api/v1/scenes/?status=closed
        /api/v1/scenes/?status=active
        /api/v1/scenes/?created_after=2026-05-01&created_before=2026-05-31T23:59:59
    """

    serializer_class = SceneSerializer
    authentication_classes = [SessionAuthentication]  # noqa: RUF012
    permission_classes = [IsAuthenticated]  # noqa: RUF012
    pagination_class = ScenesCursorPagination
    filter_backends = [OrderingFilter]  # noqa: RUF012
    ordering_fields = ["created_at", "ended_at"]  # noqa: RUF012
    ordering = ["-created_at"]  # noqa: RUF012

    def get_queryset(self):
        qs = Scene.objects.filter(privacy__in=Scene.WEB_READABLE_PRIVACY)
        status = self.request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)
        elif getattr(self, "action", "list") == "list":
            qs = qs.filter(status=Scene.Status.CLOSED)
        created_after = self._time_bound("created_after")
        if created_after is not None:
            qs = qs.filter(created_at__gte=created_after)
        created_before = self._time_bound("created_before")
        if created_before is not None:
            qs = qs.filter(created_at__lte=created_before)
        return qs

    def _time_bound(self, name):
        """Parse an inclusive ``created_at`` bound from the query string.

        Accepts an ISO 8601 datetime or a bare date (midnight, as a datetime
        filter reads one). A naive value is taken in the server's timezone.
        Anything unparseable is a 400 rather than a silently ignored filter,
        which would return a wider result than the caller asked for.
        """
        raw = self.request.query_params.get(name)
        if not raw:
            return None
        try:
            value = parse_datetime(raw)
            if value is None:
                day = parse_date(raw)
                value = datetime.combine(day, time.min) if day else None
        except ValueError:
            value = None
        if value is None:
            raise ValidationError({name: "Enter an ISO 8601 date or datetime."})
        if timezone.is_naive(value):
            value = timezone.make_aware(value)
        return value

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
