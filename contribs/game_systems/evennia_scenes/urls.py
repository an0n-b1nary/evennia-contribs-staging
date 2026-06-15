# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
URL patterns for evennia_scenes website views.

Include in your game's URLconf with an app_namespace::

    from django.urls import include, path
    urlpatterns += [
        path("", include(("evennia_scenes.urls", "evennia_scenes"))),
    ]

Generates:
    /scenes/                                          evennia_scenes:scene-list
    /scenes/<pk>/                                     evennia_scenes:scene-detail
    /scenes/<pk>/log/<entry_id>/edit/                 evennia_scenes:log-edit
    /scenes/<pk>/log/<entry_id>/history/              evennia_scenes:log-history
    /scenes/<pk>/log/<entry_id>/diff/<version_number>/  evennia_scenes:log-diff
"""

from django.urls import path

from evennia_scenes.views import (
    LogEntryDiffView,
    LogEntryEditView,
    LogEntryHistoryView,
    SceneDetailView,
    SceneListView,
)

urlpatterns = [
    path("scenes/", SceneListView.as_view(), name="scene-list"),
    path("scenes/<int:pk>/", SceneDetailView.as_view(), name="scene-detail"),
    path(
        "scenes/<int:pk>/log/<int:entry_id>/edit/",
        LogEntryEditView.as_view(),
        name="log-edit",
    ),
    path(
        "scenes/<int:pk>/log/<int:entry_id>/history/",
        LogEntryHistoryView.as_view(),
        name="log-history",
    ),
    path(
        "scenes/<int:pk>/log/<int:entry_id>/diff/<int:version_number>/",
        LogEntryDiffView.as_view(),
        name="log-diff",
    ),
]
