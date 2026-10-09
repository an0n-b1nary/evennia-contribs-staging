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
        if self.apps.is_installed("evennia_economy"):
            from evennia_economy.signals import asset_providers, economy_figures

            from .economy import provide_assets, provide_figures

            asset_providers.connect(provide_assets, dispatch_uid="resources_economy_assets")
            economy_figures.connect(provide_figures, dispatch_uid="resources_economy_figures")
