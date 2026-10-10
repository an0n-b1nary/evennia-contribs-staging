# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Shared fixtures: the sample site under tests/fixtures, mounted at /guide/."""

from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from django.test import override_settings
from django.urls import include, path
from evennia.web.urls import urlpatterns as evennia_default_urlpatterns

from evennia_guides import pages

FIXTURES = Path(__file__).parent / "fixtures"
SITE = FIXTURES / "site"
OVERRIDE = FIXTURES / "override"

# website/base.html reverses Evennia's own routes, so they come along.
urlpatterns = [
    path("guide/", include("evennia_guides.urls")),
    *evennia_default_urlpatterns,
]


_installed_guide_dirs = pages.guide_dirs


def _own_guide_dirs():
    """This contrib's guides/ and GUIDES_DIRS; other installed apps' pages stay out."""
    return [
        (origin, path)
        for origin, path in _installed_guide_dirs()
        if origin in ("evennia_guides", "host")
    ]


@contextmanager
def site_settings(*, trade=False, dirs=(SITE,), **extra):
    """
    Settings for the sample site; ``trade`` is the trading page's check.

    Other installed contribs ship guide pages too, so only this contrib's own
    pages and ``dirs`` are loaded: the suite sees the same site in any game.
    """
    with (
        mock.patch.object(pages, "guide_dirs", _own_guide_dirs),
        override_settings(
            ROOT_URLCONF=__name__,
            GUIDES_DIRS=[str(d) for d in dirs],
            GUIDES_CHECKS={"GUIDES_TEST_TRADE": trade},
            **extra,
        ),
    ):
        yield


class FreshPagesMixin:
    """Forget loaded pages around each test, whatever the settings did."""

    def setUp(self):
        pages.reset()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        pages.reset()
