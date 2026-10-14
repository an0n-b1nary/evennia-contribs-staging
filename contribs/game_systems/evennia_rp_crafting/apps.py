# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from django.apps import AppConfig


class CraftingConfig(AppConfig):
    name = "evennia_rp_crafting"
    verbose_name = "RP Crafting"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from evennia_links.runtime import cap_contributions

        from .conf import register_controls
        from .contributions import caps, figures

        register_controls()
        cap_contributions.connect(caps, dispatch_uid="crafting_workshop_caps")
        from .fixtures import furnishing_caps, scene_closed

        cap_contributions.connect(furnishing_caps, dispatch_uid="crafting_furnishing_caps")
        if self.apps.is_installed("evennia_scenes"):
            from evennia_scenes.signals import scene_closed as closed

            closed.connect(scene_closed, dispatch_uid="crafting_temporary_scene_close")
        if self.apps.is_installed("evennia_economy"):
            from evennia_economy.signals import economy_figures

            economy_figures.connect(figures, dispatch_uid="crafting_economy_figures")
