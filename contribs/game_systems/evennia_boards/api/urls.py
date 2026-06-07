# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
API URL router for evennia_boards.

Include at a prefix of your choice::

    from django.urls import include, path
    urlpatterns += [path("api/v1/", include("evennia_boards.api.urls"))]

Generates:
    GET /api/v1/boards/         BoardViewSet list
    GET /api/v1/boards/<id>/    BoardViewSet detail
    GET /api/v1/posts/          PostViewSet list  (?board=<id> to filter)
    GET /api/v1/posts/<id>/     PostViewSet detail
"""

from rest_framework.routers import DefaultRouter

from evennia_boards.api.views import BoardViewSet, PostViewSet

router = DefaultRouter()
router.register("boards", BoardViewSet, basename="api-board")
router.register("posts", PostViewSet, basename="api-post")

urlpatterns = router.urls
