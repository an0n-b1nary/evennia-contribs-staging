# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_xp."""

from django.apps import AppConfig


class XPConfig(AppConfig):
    """AppConfig for the evennia_xp contrib."""

    name = "evennia_xp"
    label = "evennia_xp"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Evennia XP"

    def ready(self):
        from evennia_xp import signals  # noqa: F401 — registers signal objects
