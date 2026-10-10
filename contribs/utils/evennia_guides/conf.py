# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Settings for evennia_guides, with their defaults."""

from django.conf import settings

DEFAULTS = {
    # Host directories of guide pages, read after every app's guides/ directory,
    # so a host page replaces a contrib page with the same key.
    "GUIDES_DIRS": (),
    # Overrides for named checks: {name: bool | callable | "dotted.path"}.
    "GUIDES_CHECKS": {},
    # Who counts as staff: sees staff pages and hidden pages (marked).
    "GUIDES_STAFF_LOCK": "perm(Admin)",
    # "Ask about this page": a route name (reversed with the kwargs below) or a
    # literal URL. Falsy, or a route that doesn't reverse, hides the link.
    "GUIDES_ASK_URL": "job-create",
    "GUIDES_ASK_URL_KWARGS": {"job_type": "request"},
}


def get(name):
    """The host's setting, or this contrib's default."""
    return getattr(settings, name, DEFAULTS[name])
