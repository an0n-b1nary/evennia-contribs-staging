# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_rp_rules."""

from django.apps import AppConfig


class RPRulesConfig(AppConfig):
    """AppConfig for the evennia_rp_rules contrib. Ships no models."""

    name = "evennia_rp_rules"
    label = "evennia_rp_rules"
    verbose_name = "Evennia RP Rules"

    def ready(self):
        from django.core import checks
        from django.core.signals import setting_changed

        from evennia_rp_rules.ruleset import reset_ruleset_cache
        from evennia_rp_rules.system_checks import check_dotted_paths, check_ruleset

        # Rebuild the cached ruleset whenever an RP_RULES_* setting changes
        # (override_settings in tests; the receiver ignores other settings).
        setting_changed.connect(
            reset_ruleset_cache, dispatch_uid="evennia_rp_rules.reset_ruleset_cache"
        )
        checks.register(check_ruleset)
        checks.register(check_dotted_paths)
