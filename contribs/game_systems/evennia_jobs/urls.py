# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Website URL patterns for evennia_jobs.

Include in your URL configuration (without a namespace)::

    from django.urls import include, path
    urlpatterns += [path("jobs/", include("evennia_jobs.urls"))]

URL names: job-list, job-all, job-create, job-detail, job-comment.
"""

from django.urls import path

from evennia_jobs.views import (
    JobAllView,
    JobCommentCreateView,
    JobCreateView,
    JobDetailView,
    JobListView,
)

urlpatterns = [
    path("", JobListView.as_view(), name="job-list"),
    path("all/", JobAllView.as_view(), name="job-all"),
    path("new/<str:job_type>/", JobCreateView.as_view(), name="job-create"),
    path("<int:pk>/", JobDetailView.as_view(), name="job-detail"),
    path("<int:pk>/comment/", JobCommentCreateView.as_view(), name="job-comment"),
]
