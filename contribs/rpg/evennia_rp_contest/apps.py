# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Connect only partners actually in the app registry."""

from django.apps import AppConfig


class RPContestConfig(AppConfig):
    name = "evennia_rp_contest"
    label = "evennia_rp_contest"
    verbose_name = "Evennia RP Contest"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.apps import apps

        from evennia_rp_contest import conf

        for setting, module in (
            ("RP_CONTEST_SCENES_APP_LABEL", "scenes"),
            ("RP_CONTEST_RPTRACKER_APP_LABEL", "rptracker"),
        ):
            partner = next(
                (cfg for cfg in apps.get_app_configs() if cfg.label == conf.get(setting)), None
            )
            if partner:
                from importlib import import_module

                import_module(f"evennia_rp_contest.integrations.{module}").connect(partner)
