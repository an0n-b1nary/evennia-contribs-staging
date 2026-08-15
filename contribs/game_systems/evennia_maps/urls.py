# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
URL configuration for evennia_maps website views. Requires [web] extra.

Wire into your game's URL conf with::

    from django.urls import include, path

    urlpatterns = [
        ...
        path("map/", include(("evennia_maps.urls", "evennia_maps"))),
        ...
    ]

Named routes (prefix with ``evennia_maps:`` when reversing)::

    plane-list      /map/
    plane-detail    /map/<pk>/
    plane-live-map  /map/<pk>/live/

The templates reverse their own routes through the ``evennia_maps``
namespace, so include them namespaced as above.
"""

from django.urls import path

from evennia_maps.views import PlaneListView, PlaneLiveMapView, PlaneMapView

app_name = "evennia_maps"

urlpatterns = [
    path("", PlaneListView.as_view(), name="plane-list"),
    path("<int:pk>/", PlaneMapView.as_view(), name="plane-detail"),
    path("<int:pk>/live/", PlaneLiveMapView.as_view(), name="plane-live-map"),
]
