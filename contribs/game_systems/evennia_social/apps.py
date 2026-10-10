# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_social.

No models, so no migrations. ``ready()`` wires one optional partner: when
evennia_maps is installed, the live map's who's-here overlay
(``integrations/maps.py``). The accessibility soft-import happens lazily in
commands/*.py instead.
"""

from django.apps import AppConfig


class EvenniaSocialConfig(AppConfig):
    """AppConfig for the evennia_social contrib."""

    name = "evennia_social"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.apps import apps
        from django.conf import settings

        # --- maps: offer the who's-here tile overlay ---
        maps_label = getattr(settings, "SOCIAL_MAPS_APP_LABEL", "evennia_maps")
        if apps.is_installed(maps_label) or any(
            cfg.label == maps_label for cfg in apps.get_app_configs()
        ):
            # Imported inside the branch so a game without the map never
            # imports evennia_maps; dispatch_uid keeps a reloaded module from
            # registering the receiver twice.
            from evennia_maps.signals import collect_tile_overlays
            from evennia_social.integrations import maps as maps_overlays

            collect_tile_overlays.connect(
                maps_overlays.provide, dispatch_uid="evennia_social.tile_overlays"
            )
