# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
URL configuration for the web guide.

Wire into your game's URL conf with a bare include (the namespace comes from
``app_name``)::

    from django.urls import include, path

    urlpatterns = [
        ...
        path("guide/", include("evennia_guides.urls")),
        ...
    ]

Named routes (prefix with ``evennia_guides:`` when reversing)::

    guide-index       /guide/
    guide-principles  /guide/principles/
    guide-glossary    /guide/glossary/
    guide-page        /guide/<key>/
"""

from django.urls import path

from evennia_guides.views import (
    GuideGlossaryView,
    GuideIndexView,
    GuidePageView,
    GuidePrinciplesView,
)

app_name = "evennia_guides"

urlpatterns = [
    path("", GuideIndexView.as_view(), name="guide-index"),
    path("principles/", GuidePrinciplesView.as_view(), name="guide-principles"),
    path("glossary/", GuideGlossaryView.as_view(), name="guide-glossary"),
    path("<slug:key>/", GuidePageView.as_view(), name="guide-page"),
]
