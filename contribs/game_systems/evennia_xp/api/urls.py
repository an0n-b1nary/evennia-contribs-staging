# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""API URL router for evennia_xp.

Include at a prefix of your choice::

    from django.urls import include, path
    urlpatterns += [path("api/v1/", include("evennia_xp.api.urls"))]

Generates: GET /api/v1/xp-log/ and GET /api/v1/xp-log/<id>/
"""

from rest_framework.routers import DefaultRouter

from evennia_xp.api.views import XPLogViewSet

router = DefaultRouter()
router.register("xp-log", XPLogViewSet, basename="api-xp-log")

urlpatterns = router.urls
