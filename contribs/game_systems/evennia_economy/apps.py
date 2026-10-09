# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from django.apps import AppConfig


class EconomyConfig(AppConfig):
    name = "evennia_economy"
    verbose_name = "Economy"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.db.models.signals import post_save

        from evennia_links.runtime import runtime_setting_changed

        from .batch import on_runtime_change
        from .conf import register_controls
        from .exchange import on_location_saved

        register_controls()
        post_save.connect(on_location_saved, dispatch_uid="economy_offer_departure")
        runtime_setting_changed.connect(on_runtime_change, dispatch_uid="economy_reveal")
