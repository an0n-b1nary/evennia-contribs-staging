# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""API URL router for evennia_lore.

Include at a prefix of your choice::

    from django.urls import include, path
    urlpatterns += [path("api/v1/", include("evennia_lore.api.urls"))]

Generates: GET /api/v1/lore/ and GET /api/v1/lore/<id>/
           GET /api/v1/lore-tags/ and GET /api/v1/lore-tags/<id>/
"""

from rest_framework.routers import DefaultRouter

from evennia_lore.api.views import LoreEntryViewSet, LoreTagViewSet

router = DefaultRouter()
router.register("lore", LoreEntryViewSet, basename="api-lore")
router.register("lore-tags", LoreTagViewSet, basename="api-lore-tag")

urlpatterns = router.urls
