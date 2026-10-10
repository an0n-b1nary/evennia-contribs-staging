# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from django.apps import AppConfig


class EconomyConfig(AppConfig):
    name = "evennia_economy"
    verbose_name = "Economy"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.db.models.signals import post_save, pre_delete, pre_save

        from evennia_links.runtime import cap_contributions, runtime_setting_changed

        from .batch import on_runtime_change
        from .conf import register_controls
        from .exchange import on_location_saved
        from .models import Purse
        from .movement import after_location_save, before_location_save, guard_stock_deletion
        from .services import on_purse_deleted
        from .signals import economy_figures
        from .stalls import cap_contribution, figures

        register_controls()
        post_save.connect(on_location_saved, dispatch_uid="economy_offer_departure")
        runtime_setting_changed.connect(on_runtime_change, dispatch_uid="economy_reveal")
        pre_delete.connect(on_purse_deleted, sender=Purse, dispatch_uid="economy_purse_deleted")
        pre_save.connect(before_location_save, dispatch_uid="economy_stock_guard")
        post_save.connect(after_location_save, dispatch_uid="economy_floor_transfer")
        pre_delete.connect(guard_stock_deletion, dispatch_uid="economy_stock_delete")
        cap_contributions.connect(cap_contribution, dispatch_uid="economy_stall_caps")
        economy_figures.connect(figures, dispatch_uid="economy_stall_figures")
