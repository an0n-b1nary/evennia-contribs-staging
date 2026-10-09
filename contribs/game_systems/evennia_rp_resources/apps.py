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
