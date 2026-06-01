# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""DRF viewset for evennia_jobs API.

Authentication: SessionAuthentication (set explicitly — does not rely on global
REST_FRAMEWORK defaults). Requires ``IsAuthenticated``.

Privacy rules:
- Staff (JOBS_STAFF_LOCK permission) see all non-closed tickets.
- Non-staff see only their own + assigned tickets; +discuss excluded.
- ISSUE reporter names are masked for non-staff.
- Staff-only comments are hidden for non-staff.
"""

from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from evennia_jobs.api.filters import JobFilter
from evennia_jobs.api.pagination import JobsCursorPagination
from evennia_jobs.api.serializers import JobSerializer
from evennia_jobs.models import Job
from evennia_jobs.permissions import get_character_id, is_staff_user


class JobViewSet(ReadOnlyModelViewSet):
    """
    Staff ticket queue.

    Staff see all non-closed tickets. Players see only tickets they submitted
    or are assigned to; +discuss tickets are always staff-only.
    ISSUE ticket reporter names are masked for non-staff.

    Filtering: ``?job_type=request|bug|issue|discuss``,
    ``?status=open|in_review|answered|closed``,
    ``?priority=normal|high|urgent``
    """

    serializer_class = JobSerializer
    filterset_class = JobFilter
    ordering_fields = ["created_at", "updated_at", "priority"]  # noqa: RUF012
    ordering = ["-priority", "created_at"]  # noqa: RUF012

    # Explicit to avoid depending on the consumer's global REST_FRAMEWORK config.
    authentication_classes = [SessionAuthentication]  # noqa: RUF012
    permission_classes = [IsAuthenticated]  # noqa: RUF012
    pagination_class = JobsCursorPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]  # noqa: RUF012

    def get_queryset(self):
        request = self.request
        staff = is_staff_user(request)

        if staff:
            return Job.objects.order_by("-priority", "created_at")

        char_id = get_character_id(request.user)
        if not char_id:
            return Job.objects.none()
        return (
            Job.objects.filter(Q(author_id=char_id) | Q(assignee_id=char_id))
            .exclude(job_type="discuss")
            .order_by("-priority", "created_at")
        )

    def retrieve(self, request, *args, **kwargs):
        job = self.get_object()
        staff = is_staff_user(request)

        if not staff:
            char_id = get_character_id(request.user)
            if job.job_type == "discuss":
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
            if not char_id or (job.author_id != char_id and job.assignee_id != char_id):
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = self.get_serializer(job)
        return Response(serializer.data)
