# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_rp_chargen."""

from django.apps import AppConfig


class RPChargenConfig(AppConfig):
    """AppConfig for the evennia_rp_chargen contrib."""

    name = "evennia_rp_chargen"
    label = "evennia_rp_chargen"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Evennia RP Chargen"

    def ready(self):
        from django.apps import apps
        from django.core import checks

        from evennia_rp_chargen import conf
        from evennia_rp_chargen.locks import on_check_resolved
        from evennia_rp_chargen.system_checks import check_allocation, check_pip_settings
        from evennia_rp_rules.signals import check_resolved

        checks.register(check_allocation)
        checks.register(check_pip_settings)
        # A resolved check is IC action for its actor (evennia_rp_rules is a
        # hard dependency, so this is always connected).
        check_resolved.connect(on_check_resolved, dispatch_uid="evennia_rp_chargen.check_lock")

        label = conf.get("RP_CHARGEN_RPTRACKER_APP_LABEL")
        tracker = next((cfg for cfg in apps.get_app_configs() if cfg.label == label), None)
        if tracker is not None:
            from evennia_rp_chargen.integrations import rptracker

            rptracker.connect(tracker)
