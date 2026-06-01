# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from django.contrib import admin

from evennia_jobs.models import Job, JobComment


class JobCommentInline(admin.TabularInline):
    model = JobComment
    extra = 0
    readonly_fields = ["author", "author_name", "is_staff_only", "created_at"]  # noqa: RUF012
    fields = ["author_name", "content", "is_staff_only", "created_at"]  # noqa: RUF012


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = [  # noqa: RUF012
        "job_number",
        "job_type",
        "status",
        "priority",
        "title",
        "author_name",
        "assignee_name",
        "created_at",
    ]
    list_filter = ["job_type", "status", "priority"]  # noqa: RUF012
    search_fields = ["title", "description", "author_name", "assignee_name"]  # noqa: RUF012
    readonly_fields = ["job_number", "created_at", "updated_at", "closed_at"]  # noqa: RUF012
    raw_id_fields = ["author", "assignee"]  # noqa: RUF012
    ordering = ["-priority", "created_at"]  # noqa: RUF012
    inlines = [JobCommentInline]  # noqa: RUF012


@admin.register(JobComment)
class JobCommentAdmin(admin.ModelAdmin):
    list_display = ["pk", "job", "author_name", "is_staff_only", "created_at"]  # noqa: RUF012
    list_filter = ["is_staff_only"]  # noqa: RUF012
    search_fields = ["author_name", "content"]  # noqa: RUF012
    readonly_fields = ["created_at"]  # noqa: RUF012
    raw_id_fields = ["job", "author"]  # noqa: RUF012
