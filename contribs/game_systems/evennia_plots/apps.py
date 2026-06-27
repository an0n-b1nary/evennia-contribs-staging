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
        from django.conf import settings

        from evennia_links import connect_on_ready, connect_soft_ref_cleanup
        from evennia_plots import signals
        from evennia_plots.models import PlotBoardLink, PlotCalendarLink, ScenePlotLink

        installed = {a.split(".")[-1] for a in settings.INSTALLED_APPS}

        # --- scenes: cleanup ScenePlotLink.scene_id on Scene hard-delete
        #             + auto-create PlotParticipants when a scene is linked ---
        scenes_label = getattr(settings, "PLOTS_SCENES_APP_LABEL", "scenes")
        if scenes_label in installed:
            try:
                from django.apps import apps as django_apps

                from evennia_plots.listeners import on_scene_linked_to_thread

                Scene = django_apps.get_model(scenes_label, "Scene")
                connect_soft_ref_cleanup(Scene, ScenePlotLink, "scene_id")
                connect_on_ready(signals.scene_linked_to_thread, on_scene_linked_to_thread)
            except Exception:
                pass

        # --- boards: cleanup PlotBoardLink.post_id on Post hard-delete ---
        boards_label = getattr(settings, "PLOTS_BOARDS_APP_LABEL", "boards")
        if boards_label in installed:
            try:
                from django.apps import apps as django_apps

                Post = django_apps.get_model(boards_label, "Post")
                connect_soft_ref_cleanup(Post, PlotBoardLink, "post_id")
            except Exception:
                pass

        # --- calendar: cleanup PlotCalendarLink.event_id on CalendarEvent hard-delete ---
        calendar_label = getattr(settings, "PLOTS_CALENDAR_APP_LABEL", "calendar")
        if calendar_label in installed:
            try:
                from django.apps import apps as django_apps

                CalendarEvent = django_apps.get_model(calendar_label, "CalendarEvent")
                connect_soft_ref_cleanup(CalendarEvent, PlotCalendarLink, "event_id")
            except Exception:
                pass
