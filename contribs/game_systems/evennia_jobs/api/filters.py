# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""django-filter FilterSet for evennia_jobs API."""

import django_filters

from evennia_jobs.models import Job


class JobFilter(django_filters.FilterSet):
    job_type = django_filters.CharFilter(field_name="job_type", lookup_expr="exact")
    status = django_filters.CharFilter(field_name="status", lookup_expr="exact")
    priority = django_filters.CharFilter(field_name="priority", lookup_expr="exact")

    class Meta:
        model = Job
        fields = ["job_type", "status", "priority"]  # noqa: RUF012
