# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""API URL router for evennia_maps.

Include at a prefix of your choice::

    from django.urls import include, path
    urlpatterns += [path("api/v1/", include("evennia_maps.api.urls"))]

Generates::

    GET /api/v1/planes/                 api-plane-list
    GET /api/v1/planes/<id>/            api-plane-detail
    GET /api/v1/planes/<id>/tiles/      api-plane-tiles

Include it **without** a namespace unless you also set
``MAPS_TILES_URL_NAME`` to match: the live map page reverses
``api-plane-tiles`` to find the tile feed, and without that route it
renders an explanatory notice instead of an empty canvas.
"""

from rest_framework.routers import DefaultRouter

from evennia_maps.api.views import PlaneViewSet

router = DefaultRouter()
router.register("planes", PlaneViewSet, basename="api-plane")

urlpatterns = router.urls
