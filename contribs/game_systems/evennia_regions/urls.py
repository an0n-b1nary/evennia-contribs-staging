# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
URL configuration for evennia_regions web views. Requires [web] extra.

Wire into your game's URL conf with::

    from django.urls import include, path

    urlpatterns = [
        ...
        path("regions/", include(("evennia_regions.urls", "evennia_regions"))),
        ...
    ]

Named routes (prefix with ``evennia_regions:`` when reversing)::

    region-list      /regions/
    region-detail    /regions/<pk>/
"""

from django.urls import path

from evennia_regions.views import RegionDetailView, RegionListView

app_name = "evennia_regions"

urlpatterns = [
    path("", RegionListView.as_view(), name="region-list"),
    path("<int:pk>/", RegionDetailView.as_view(), name="region-detail"),
]
