# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from django.apps import AppConfig


class ResourcesConfig(AppConfig):
    name = "evennia_rp_resources"
    verbose_name = "RP Resources"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from .conf import register_controls

        register_controls()
        if self.apps.is_installed("evennia_plots"):
            from evennia_plots.signals import plot_thread_concluded

            from .payouts import on_concluded

            plot_thread_concluded.connect(
                on_concluded, dispatch_uid="resources_plot_payout", weak=False
            )
        if self.apps.is_installed("evennia_economy"):
            from evennia_economy.signals import asset_providers, economy_figures

            from .economy import provide_assets, provide_figures

            asset_providers.connect(provide_assets, dispatch_uid="resources_economy_assets")
            economy_figures.connect(provide_figures, dispatch_uid="resources_economy_figures")
        if self.apps.is_installed("evennia_maps"):
            from evennia_maps import signals as maps_signals

            # The room panel's seam arrived in evennia-maps 0.9.
            collect_tile_detail = getattr(maps_signals, "collect_tile_detail", None)
            if collect_tile_detail is not None:
                from .map_panel import provide_detail

                collect_tile_detail.connect(provide_detail, dispatch_uid="resources_map_panel")
