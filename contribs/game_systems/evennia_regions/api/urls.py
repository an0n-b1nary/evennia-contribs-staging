# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""API URL router for evennia_regions.

Include at a prefix of your choice::

    from django.urls import include, path
    urlpatterns += [path("api/v1/", include("evennia_regions.api.urls"))]

Generates: GET /api/v1/regions/ and GET /api/v1/regions/<id>/
"""

from rest_framework.routers import DefaultRouter

from evennia_regions.api.views import RegionViewSet

router = DefaultRouter()
router.register("regions", RegionViewSet, basename="api-region")

urlpatterns = router.urls
