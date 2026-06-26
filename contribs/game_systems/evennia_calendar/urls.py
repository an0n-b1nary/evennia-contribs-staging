# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
URL configuration for evennia_calendar web views.

Wire into your game's URL conf with::

    from django.urls import include, path

    urlpatterns = [
        ...
        path("calendar/", include(("evennia_calendar.urls", "evennia_calendar"))),
        ...
    ]

Named routes (prefix with ``evennia_calendar:`` when reversing)::

    calendar-month              /calendar/
    calendar-list               /calendar/list/
    calendar-event-detail       /calendar/<pk>/
    calendar-cluster-detail     /calendar/cluster/<pk>/
    calendar-event-create       /calendar/new/
    calendar-event-edit         /calendar/<pk>/edit/
    calendar-event-cancel       /calendar/<pk>/cancel/
    calendar-event-invite       /calendar/<pk>/invite/
    calendar-event-tags         /calendar/<pk>/tags/
    calendar-event-exclusions   /calendar/<pk>/exclusions/
    calendar-cluster-create     /calendar/cluster/new/
    calendar-cluster-edit       /calendar/cluster/<pk>/edit/
    calendar-cluster-members    /calendar/cluster/<pk>/members/
    calendar-tag-create         /calendar/tags/new/
"""

from django.urls import path

from evennia_calendar.views import (
    CalendarEventDetailView,
    CalendarListView,
    CalendarMonthView,
    ClusterCreateView,
    ClusterDetailView,
    ClusterEditView,
    ClusterMembershipView,
    EventCancelView,
    EventCreateView,
    EventEditView,
    EventInviteView,
    EventTagCreateView,
    EventTagView,
    ExclusionManageView,
)

app_name = "evennia_calendar"

urlpatterns = [
    # Read-only public views.
    path("", CalendarMonthView.as_view(), name="calendar-month"),
    path("list/", CalendarListView.as_view(), name="calendar-list"),
    path("<int:pk>/", CalendarEventDetailView.as_view(), name="calendar-event-detail"),
    path(
        "cluster/<int:pk>/",
        ClusterDetailView.as_view(),
        name="calendar-cluster-detail",
    ),
    # Authoring views (require login + puppet).
    path("new/", EventCreateView.as_view(), name="calendar-event-create"),
    path("<int:pk>/edit/", EventEditView.as_view(), name="calendar-event-edit"),
    path("<int:pk>/cancel/", EventCancelView.as_view(), name="calendar-event-cancel"),
    path("<int:pk>/invite/", EventInviteView.as_view(), name="calendar-event-invite"),
    path("<int:pk>/tags/", EventTagView.as_view(), name="calendar-event-tags"),
    path(
        "<int:pk>/exclusions/",
        ExclusionManageView.as_view(),
        name="calendar-event-exclusions",
    ),
    path("cluster/new/", ClusterCreateView.as_view(), name="calendar-cluster-create"),
    path(
        "cluster/<int:pk>/edit/",
        ClusterEditView.as_view(),
        name="calendar-cluster-edit",
    ),
    path(
        "cluster/<int:pk>/members/",
        ClusterMembershipView.as_view(),
        name="calendar-cluster-members",
    ),
    path("tags/new/", EventTagCreateView.as_view(), name="calendar-tag-create"),
]
