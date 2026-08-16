# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_calendar."""

from django.apps import AppConfig


class CalendarConfig(AppConfig):
    """AppConfig for the evennia_calendar contrib."""

    name = "evennia_calendar"
    label = "evennia_calendar"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Evennia Calendar"

    def ready(self):
        from django.apps import apps
        from django.conf import settings

        import evennia_calendar.signals  # noqa: F401
        from evennia_calendar.models import SceneCalendarLink
        from evennia_links import connect_soft_ref_cleanup

        # --- scenes: cleanup SceneCalendarLink.scene_id on Scene hard-delete ---
        scenes_label = getattr(settings, "CALENDAR_SCENES_APP_LABEL", "evennia_scenes")
        if apps.is_installed(scenes_label) or any(
            cfg.label == scenes_label for cfg in apps.get_app_configs()
        ):
            try:
                Scene = apps.get_model(scenes_label, "Scene")
                connect_soft_ref_cleanup(Scene, SceneCalendarLink, "scene_id")
            except Exception:
                pass

        # --- maps: offer the upcoming_events tile overlay ---
        maps_label = getattr(settings, "CALENDAR_MAPS_APP_LABEL", "evennia_maps")
        if apps.is_installed(maps_label) or any(
            cfg.label == maps_label for cfg in apps.get_app_configs()
        ):
            # Imported inside the branch so a game without the map never
            # imports evennia_maps. dispatch_uid rather than the plain
            # connect_on_ready() helper: this is the wiring evennia_maps'
            # own README documents for providers, and it keeps a reloaded
            # module from registering the receiver twice.
            from evennia_calendar.integrations import maps as maps_overlays
            from evennia_maps.signals import collect_tile_overlays

            collect_tile_overlays.connect(
                maps_overlays.provide, dispatch_uid="evennia_calendar.tile_overlays"
            )
