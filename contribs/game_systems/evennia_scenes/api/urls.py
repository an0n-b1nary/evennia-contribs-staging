# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
API URL router for evennia_scenes.

Include at a prefix of your choice::

    from django.urls import include, path
    urlpatterns += [path("api/v1/", include("evennia_scenes.api.urls"))]

Generates:
    GET /api/v1/scenes/           SceneViewSet list
    GET /api/v1/scenes/<pk>/      SceneViewSet detail
    GET /api/v1/scenes/<pk>/log/  scene log entries
"""

from rest_framework.routers import DefaultRouter

from evennia_scenes.api.views import SceneViewSet

router = DefaultRouter()
router.register("scenes", SceneViewSet, basename="api-scene")

urlpatterns = router.urls
