# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
API URL routing for evennia_calendar. Requires [web] extra.

Wire into your game's API URL conf::

    from django.urls import include, path

    urlpatterns = [
        ...
        path("api/v1/events/", include("evennia_calendar.api.urls")),
        ...
    ]

Or with a DRF router for the standard list/detail pattern::

    from rest_framework.routers import DefaultRouter
    from evennia_calendar.api.views import CalendarEventViewSet

    router = DefaultRouter()
    router.register("events", CalendarEventViewSet, basename="event")
    urlpatterns = router.urls
"""

from rest_framework.routers import DefaultRouter

from evennia_calendar.api.views import CalendarEventViewSet

router = DefaultRouter()
router.register("events", CalendarEventViewSet, basename="event")

urlpatterns = router.urls
