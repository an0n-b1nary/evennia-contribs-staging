# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_regions."""

from django.apps import AppConfig


class RegionsConfig(AppConfig):
    """AppConfig for the evennia_regions contrib.

    Regions is almost entirely an "answering" domain — partner contribs
    (e.g. evennia-lore's connect_soft_ref_cleanup gate) reach into regions,
    not the other way around. The one exception is the map tile overlay: a
    map cannot know which region a room belongs to without being told, so
    regions offers itself as a provider when evennia_maps is installed.
    """

    name = "evennia_regions"
    label = "evennia_regions"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Evennia Regions"

    def ready(self):
        from django.apps import apps
        from django.conf import settings

        maps_label = getattr(settings, "REGIONS_MAPS_APP_LABEL", "evennia_maps")
        if apps.is_installed(maps_label) or any(
            cfg.label == maps_label for cfg in apps.get_app_configs()
        ):
            # Imported inside the branch so a game without the map never
            # imports evennia_maps. dispatch_uid rather than the plain
            # connect_on_ready() helper: this is the wiring evennia_maps'
            # own README documents for providers, and it keeps a reloaded
            # module from registering the receiver twice.
            from evennia_maps.signals import collect_tile_overlays
            from evennia_regions.integrations import maps as maps_overlays

            collect_tile_overlays.connect(
                maps_overlays.provide, dispatch_uid="evennia_regions.tile_overlays"
            )
