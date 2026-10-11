# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""DRF serializers for evennia_jobs API."""

from rest_framework import serializers

from evennia_jobs.models import Job, JobComment, RequestSubmission
from evennia_jobs.permissions import is_staff_user


def _is_staff(request):
    return is_staff_user(request) if request else False


class JobCommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobComment
        fields = [  # noqa: RUF012
            "id",
            "author_name",
            "content",
            "is_staff_only",
            "created_at",
        ]


class JobSerializer(serializers.ModelSerializer):
    job_type_display = serializers.CharField(source="get_job_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    comments = serializers.SerializerMethodField()
    author_name = serializers.SerializerMethodField()
    submissions = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = [  # noqa: RUF012
            "id",
            "job_number",
            "job_type",
            "job_type_display",
            "status",
            "status_display",
            "priority",
            "priority_display",
            "title",
            "description",
            "author_name",
            "assignee_name",
            "created_at",
            "updated_at",
            "comments",
            "submissions",
        ]

    def get_author_name(self, obj):
        request = self.context.get("request")
        if obj.job_type == "issue" and not _is_staff(request):
            return None
        return obj.author_name or None

    def get_submissions(self, obj):
        """Expose proposal history under the existing ticket privacy rules."""
        return RequestSubmissionSerializer(
            obj.submissions.select_related("decision"), many=True
        ).data

    def get_comments(self, obj):
        request = self.context.get("request")
        qs = obj.comments.all()
        if not _is_staff(request):
            qs = qs.filter(is_staff_only=False)
        return JobCommentSerializer(qs, many=True).data


class RequestSubmissionSerializer(serializers.ModelSerializer):
    """Read-only proposal history; the API has no approval or submission writes."""

    decision = serializers.SerializerMethodField()

    class Meta:
        model = RequestSubmission
        fields = ["id", "revision", "form_key", "schema", "answers", "created_at", "decision"]  # noqa: RUF012

    def get_decision(self, obj):
        """Review attribution survives reviewer character deletion."""
        if not hasattr(obj, "decision"):
            return None
        decision = obj.decision
        return {
            "outcome": decision.outcome,
            "reviewer_name": decision.reviewer_name,
            "reason": decision.reason,
            "created_at": decision.created_at.isoformat(),
        }
