# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_links — shared abstract infrastructure for Evennia contrib bridge models.

Public API:

    AbstractLink            — minimal link base (created_at + create_link)
    AbstractAuthoredLink    — link with creator audit block
    AbstractVersion         — append-only version history for any text field
    AbstractArchived        — soft-archive mixin with default manager
    ArchivedManager         — manager that filters out archived records
    ArchivedQuerySet        — queryset with include_archived() helper
    connect_on_ready        — import-order-safe signal-registration helper

See each module's docstring for usage examples.
"""

from evennia_links.archiving import AbstractArchived, ArchivedManager, ArchivedQuerySet
from evennia_links.links import AbstractAuthoredLink, AbstractLink
from evennia_links.listeners import connect_on_ready
from evennia_links.versioning import AbstractVersion

__all__ = [
    "AbstractArchived",
    "AbstractAuthoredLink",
    "AbstractLink",
    "AbstractVersion",
    "ArchivedManager",
    "ArchivedQuerySet",
    "connect_on_ready",
]
