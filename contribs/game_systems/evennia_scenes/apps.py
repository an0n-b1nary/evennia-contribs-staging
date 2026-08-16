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
        from django.apps import apps
        from django.conf import settings

        import evennia_scenes.signals  # noqa: F401

        # --- maps: offer the scene tile overlays ---
        maps_label = getattr(settings, "SCENES_MAPS_APP_LABEL", "evennia_maps")
        if apps.is_installed(maps_label) or any(
            cfg.label == maps_label for cfg in apps.get_app_configs()
        ):
            # Imported inside the branch so a game without the map never
            # imports evennia_maps. dispatch_uid rather than the plain
            # connect_on_ready() helper: this is the wiring evennia_maps'
            # own README documents for providers, and it keeps a reloaded
            # module from registering the receiver twice.
            from evennia_maps.signals import collect_tile_overlays
            from evennia_scenes.integrations import maps as maps_overlays

            collect_tile_overlays.connect(
                maps_overlays.provide, dispatch_uid="evennia_scenes.tile_overlays"
            )
