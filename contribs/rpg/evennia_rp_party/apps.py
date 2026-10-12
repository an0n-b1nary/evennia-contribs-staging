# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from django.apps import AppConfig


class RPPartyConfig(AppConfig):
    name = "evennia_rp_party"
    verbose_name = "Evennia RP Party"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.core.checks import register

        from . import conf
        from .checks import check_configuration

        conf.register_runtime()
        register(check_configuration)
