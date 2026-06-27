# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
API URL router for the evennia_plots contrib.

Include at a prefix of your choice::

    from django.urls import include, path
    urlpatterns += [path("api/v1/", include("evennia_plots.api.urls"))]

Generates:
    GET /api/v1/plots/       PlotThreadViewSet list
    GET /api/v1/plots/<pk>/  PlotThreadViewSet detail
"""

from rest_framework.routers import DefaultRouter

from evennia_plots.api.views import PlotThreadViewSet

router = DefaultRouter()
router.register("plots", PlotThreadViewSet, basename="api-plot")

urlpatterns = router.urls
