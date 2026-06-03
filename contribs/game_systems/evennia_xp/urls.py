# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Website URL patterns for evennia_xp.

Include at a path of your choice::

    from django.urls import include, path
    urlpatterns += [path("xp/", include("evennia_xp.urls"))]

URL names: xp-summary
"""

from django.urls import path

from evennia_xp.views import XPSummaryView

urlpatterns = [
    path("", XPSummaryView.as_view(), name="xp-summary"),
]
