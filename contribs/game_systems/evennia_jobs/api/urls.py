# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""API URL router for evennia_jobs.

Include at a prefix of your choice::

    from django.urls import include, path
    urlpatterns += [path("api/v1/", include("evennia_jobs.api.urls"))]

Generates: GET /api/v1/jobs/ and GET /api/v1/jobs/<id>/
"""

from rest_framework.routers import DefaultRouter

from evennia_jobs.api.views import JobViewSet

router = DefaultRouter()
router.register("jobs", JobViewSet, basename="api-job")

urlpatterns = router.urls
