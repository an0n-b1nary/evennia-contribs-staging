# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_rp_chargen."""

from django.apps import AppConfig


def boolean(value):
    return type(value) is bool


class RPChargenConfig(AppConfig):
    """AppConfig for the evennia_rp_chargen contrib."""

    name = "evennia_rp_chargen"
    label = "evennia_rp_chargen"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Evennia RP Chargen"

    def ready(self):
        from evennia_links.runtime import register

        register(
            "RP_CHARGEN_MOVES_REVEALED",
            False,
            validator=boolean,
            description="Expose free Signature libraries and equipped moves.",
        )
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
        from django.db.models.signals import pre_delete

        from evennia_rp_chargen.services import discard_guest_audit

        pre_delete.connect(discard_guest_audit, dispatch_uid="evennia_rp_chargen.guest_cleanup")

        label = conf.get("RP_CHARGEN_RPTRACKER_APP_LABEL")
        tracker = next((cfg for cfg in apps.get_app_configs() if cfg.label == label), None)
        if tracker is not None:
            from evennia_rp_chargen.integrations import rptracker

            rptracker.connect(tracker)
