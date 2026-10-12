# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""URL configuration for the evennia_plots contrib.

Include in your game's URLconf under the ``evennia_plots`` namespace::

    from django.urls import include, path

    urlpatterns = [
        ...
        path("plots/", include("evennia_plots.urls", namespace="evennia_plots")),
    ]

The paths below are relative to whatever prefix you mount them at.
"""

from django.urls import path

from evennia_plots.views import (
    PlotArcClearCurrentView,
    PlotArcCreateView,
    PlotArcDetailView,
    PlotArcEditView,
    PlotArcListView,
    PlotArcSetCurrentView,
    PlotCreateView,
    PlotDetailView,
    PlotEditView,
    PlotInviteView,
    PlotListView,
    PlotOwnersView,
    PlotTagCreateView,
    PlotTagListView,
    PlotUpdateCreateView,
    PlotUpdateDiffView,
    PlotUpdateEditView,
    PlotUpdateHistoryView,
    StoryThreadActionView,
    StoryThreadAnswerView,
    StoryThreadCarryView,
    StoryThreadCreateView,
    StoryThreadResolveView,
)

app_name = "evennia_plots"

urlpatterns = [
    path("", PlotListView.as_view(), name="plot-list"),
    path("new/", PlotCreateView.as_view(), name="plot-create"),
    path("tags/", PlotTagListView.as_view(), name="plot-tags"),
    path("tags/new/", PlotTagCreateView.as_view(), name="plot-tag-create"),
    path("<int:pk>/", PlotDetailView.as_view(), name="plot-detail"),
    path("<int:pk>/edit/", PlotEditView.as_view(), name="plot-edit"),
    path("<int:pk>/invite/", PlotInviteView.as_view(), name="plot-invite"),
    path("<int:pk>/owners/", PlotOwnersView.as_view(), name="plot-owners"),
    path("<int:pk>/threads/new/", StoryThreadCreateView.as_view(), name="plot-thread-create"),
    path(
        "<int:pk>/threads/<int:number>/resolve/",
        StoryThreadResolveView.as_view(),
        name="plot-thread-resolve",
    ),
    path(
        "<int:pk>/threads/<int:number>/answer/",
        StoryThreadAnswerView.as_view(),
        name="plot-thread-answer",
    ),
    path(
        "<int:pk>/threads/<int:number>/carry/",
        StoryThreadCarryView.as_view(),
        name="plot-thread-carry",
    ),
    # One-step POST actions (accept, decline, hold, lead, ...). Keep it after
    # the named thread pages above, which it would otherwise shadow.
    path(
        "<int:pk>/threads/<int:number>/<slug:action>/",
        StoryThreadActionView.as_view(),
        name="plot-thread-action",
    ),
    path("<int:pk>/updates/new/", PlotUpdateCreateView.as_view(), name="plot-update-create"),
    path(
        "<int:pk>/updates/<int:update_id>/edit/",
        PlotUpdateEditView.as_view(),
        name="plot-update-edit",
    ),
    path(
        "<int:pk>/updates/<int:update_id>/history/",
        PlotUpdateHistoryView.as_view(),
        name="plot-update-history",
    ),
    path(
        "<int:pk>/updates/<int:update_id>/diff/<int:version_number>/",
        PlotUpdateDiffView.as_view(),
        name="plot-update-diff",
    ),
    path("arcs/", PlotArcListView.as_view(), name="plot-arc-list"),
    path("arc/new/", PlotArcCreateView.as_view(), name="plot-arc-create"),
    path("arc/<int:pk>/", PlotArcDetailView.as_view(), name="plot-arc-detail"),
    path("arc/<int:pk>/edit/", PlotArcEditView.as_view(), name="plot-arc-edit"),
    path("arc/<int:pk>/set-current/", PlotArcSetCurrentView.as_view(), name="plot-arc-set-current"),
    path(
        "arc/<int:pk>/clear-current/",
        PlotArcClearCurrentView.as_view(),
        name="plot-arc-clear-current",
    ),
]
