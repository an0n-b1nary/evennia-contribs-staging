# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_accessibility.

Registers the contrib as a Django app so its templates and static files are
picked up by Django's finders. No `ready()` method — this is a pure utility
contrib with no soft-dependency wiring.
"""

from django.apps import AppConfig


class EvenniaAccessibilityConfig(AppConfig):
    """AppConfig for the evennia_accessibility contrib."""

    name = "evennia_accessibility"
    default_auto_field = "django.db.models.BigAutoField"
