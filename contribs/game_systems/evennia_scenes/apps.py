# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_scenes."""

from django.apps import AppConfig


class ScenesConfig(AppConfig):
    """AppConfig for the evennia_scenes contrib."""

    name = "evennia_scenes"
    label = "evennia_scenes"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Evennia Scenes"

    def ready(self):
        import evennia_scenes.signals  # noqa: F401
