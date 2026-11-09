# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Explicit schema-ready cap configuration validation."""

from django.conf import settings
from django.db.models import Count

from evennia_links.notices import source_registry


def validate_configuration():
    """Reject caps that cannot preserve one envelope per retained source group."""
    source_registry()
    from .models import Notice

    limit = getattr(settings, "NOTICES_ROUTINE_LIMIT", 500)
    if (
        type(limit) is not int
        or limit < 1
        or limit < len(getattr(settings, "LINKS_NOTICE_SOURCES", {}))
    ):
        raise ValueError("NOTICES_ROUTINE_LIMIT must cover registered notice sources")
    counts = (
        Notice.objects.filter(
            retired_at__isnull=True,
            events__inactive_at__isnull=True,
            events__cleared_at__isnull=True,
            events__read_at__isnull=True,
            events__action_kind__isnull=True,
        )
        .values("recipient")
        .annotate(total=Count("source", distinct=True))
    )
    if counts.filter(total__gt=limit).exists():
        raise ValueError("NOTICES_ROUTINE_LIMIT is below a recipient's retained source count")
    days = getattr(settings, "NOTICES_RETENTION_DAYS", 30)
    if type(days) is not int or days < 1:
        raise ValueError("NOTICES_RETENTION_DAYS must be a positive integer")
