# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_plots."""

from django.apps import AppConfig


class PlotsConfig(AppConfig):
    """AppConfig for the evennia_plots contrib."""

    name = "evennia_plots"
    label = "evennia_plots"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Evennia Plots"

    def ready(self):
        from django.apps import apps
        from django.conf import settings

        from evennia_links import connect_on_ready, connect_soft_ref_cleanup
        from evennia_plots import signals
        from evennia_plots.models import PlotBoardLink, PlotCalendarLink, ScenePlotLink

        def _app_present(label):
            return apps.is_installed(label) or any(
                cfg.label == label for cfg in apps.get_app_configs()
            )

        # --- scenes: cleanup ScenePlotLink.scene_id on Scene hard-delete
        #             + auto-create PlotParticipants when a scene is linked ---
        scenes_label = getattr(settings, "PLOTS_SCENES_APP_LABEL", "evennia_scenes")
        if _app_present(scenes_label):
            try:
                from evennia_plots.listeners import on_scene_linked_to_thread

                Scene = apps.get_model(scenes_label, "Scene")
                connect_soft_ref_cleanup(Scene, ScenePlotLink, "scene_id")
                connect_on_ready(signals.scene_linked_to_thread, on_scene_linked_to_thread)
            except Exception:
                pass

        # --- boards: cleanup PlotBoardLink.post_id on Post hard-delete ---
        boards_label = getattr(settings, "PLOTS_BOARDS_APP_LABEL", "evennia_boards")
        if _app_present(boards_label):
            try:
                Post = apps.get_model(boards_label, "Post")
                connect_soft_ref_cleanup(Post, PlotBoardLink, "post_id")
            except Exception:
                pass

        # --- calendar: cleanup PlotCalendarLink.event_id on CalendarEvent hard-delete ---
        calendar_label = getattr(settings, "PLOTS_CALENDAR_APP_LABEL", "evennia_calendar")
        if _app_present(calendar_label):
            try:
                CalendarEvent = apps.get_model(calendar_label, "CalendarEvent")
                connect_soft_ref_cleanup(CalendarEvent, PlotCalendarLink, "event_id")
            except Exception:
                pass

        # --- maps: the room panel's "Plots here" section ---
        maps_label = getattr(settings, "PLOTS_MAPS_APP_LABEL", "evennia_maps")
        if _app_present(maps_label):
            from evennia_maps import signals as maps_signals

            # The seam arrived in evennia-maps 0.9; an older map has no panel.
            collect_tile_detail = getattr(maps_signals, "collect_tile_detail", None)
            if collect_tile_detail is not None:
                from evennia_plots.integrations import maps as maps_detail

                collect_tile_detail.connect(
                    maps_detail.provide_detail, dispatch_uid="evennia_plots.tile_detail"
                )
