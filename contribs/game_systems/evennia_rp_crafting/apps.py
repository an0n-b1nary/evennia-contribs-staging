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
        from . import item_details, letters, signals
        from .states import provide as state_facets

        signals.collect_facets.connect(state_facets, dispatch_uid="crafting_state_facets")
        if self.apps.is_installed("evennia_rp_equipment"):
            from evennia_rp_equipment.item_display import register

            from .item_display import layers, state

            register("crafting_states", state, phase="base")
            register("crafting_modifiers", layers)

        signals.collect_facets.connect(item_details.provide, dispatch_uid="crafting_item_details")
        signals.collect_facets.connect(letters.provide, dispatch_uid="crafting_letter_facets")
        from .fixtures import furnishing_caps, scene_closed

        cap_contributions.connect(furnishing_caps, dispatch_uid="crafting_furnishing_caps")
        if self.apps.is_installed("evennia_scenes"):
            from evennia_scenes.signals import scene_closed as closed

            closed.connect(scene_closed, dispatch_uid="crafting_temporary_scene_close")
        if self.apps.is_installed("evennia_economy"):
            from evennia_economy.signals import asset_providers, economy_figures

            from .modifiers import service_assets

            economy_figures.connect(figures, dispatch_uid="crafting_economy_figures")
            asset_providers.connect(service_assets, dispatch_uid="crafting_modifier_services")
