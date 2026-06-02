# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_lore."""

from django.apps import AppConfig


class LoreConfig(AppConfig):
    """AppConfig for the evennia_lore contrib."""

    name = "evennia_lore"
    label = "evennia_lore"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Evennia Lore"

    def ready(self):
        from django.conf import settings

        from evennia_links import connect_soft_ref_cleanup
        from evennia_lore import signals  # noqa: F401 — registers signal objects
        from evennia_lore.models import (
            LoreRegionLink,
            LoreSceneLink,
            PlotLoreLink,
        )

        installed = {a.split(".")[-1] for a in settings.INSTALLED_APPS}

        # --- rptracker: register the passive-trickle listener ---
        rptracker_label = getattr(settings, "LORE_RPTRACKER_APP_LABEL", "evennia_rptracker")
        if rptracker_label in installed:
            from evennia_rptracker.signals import rp_session_ended

            from evennia_links import connect_on_ready
            from evennia_lore.listeners import _on_rp_session_ended

            connect_on_ready(rp_session_ended, _on_rp_session_ended)

        # --- scenes: cleanup LoreSceneLink.scene_id on Scene hard-delete ---
        scenes_label = getattr(settings, "LORE_SCENES_APP_LABEL", "scenes")
        if scenes_label in installed:
            try:
                from django.apps import apps as django_apps

                Scene = django_apps.get_model(scenes_label, "Scene")
                connect_soft_ref_cleanup(Scene, LoreSceneLink, "scene_id")
            except Exception:
                pass

        # --- plots: cleanup PlotLoreLink.thread_id on PlotThread hard-delete ---
        plots_label = getattr(settings, "LORE_PLOTS_APP_LABEL", "plots")
        if plots_label in installed:
            try:
                from django.apps import apps as django_apps

                PlotThread = django_apps.get_model(plots_label, "PlotThread")
                connect_soft_ref_cleanup(PlotThread, PlotLoreLink, "thread_id")
            except Exception:
                pass

        # --- regions: cleanup LoreRegionLink.region_id on Region hard-delete ---
        regions_label = getattr(settings, "LORE_REGIONS_APP_LABEL", "regions")
        if regions_label in installed:
            try:
                from django.apps import apps as django_apps

                Region = django_apps.get_model(regions_label, "Region")
                connect_soft_ref_cleanup(Region, LoreRegionLink, "region_id")
            except Exception:
                pass
