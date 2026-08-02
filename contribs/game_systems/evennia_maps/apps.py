# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_maps."""

from django.apps import AppConfig


class MapsConfig(AppConfig):
    name = "evennia_maps"
    label = "evennia_maps"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Evennia Maps"

    def ready(self):
        import evennia_maps.listeners  # noqa: F401 — connects on_object_post_create via @receiver
        from evennia_links import connect_on_ready
        from evennia_maps.listeners import on_terrain_changed
        from evennia_maps.signals import terrain_changed

        connect_on_ready(terrain_changed, on_terrain_changed)
