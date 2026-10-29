# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_links.

Registers the contrib and its deferred communication identity system check.
This contrib ships only abstract models (no tables), so there are no migrations.
"""

from django.apps import AppConfig


class EvenniaLinksConfig(AppConfig):
    """AppConfig for the evennia_links contrib."""

    name = "evennia_links"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Evennia Links"

    def ready(self):
        from django.core.checks import Tags, register

        from .identity import comms_identity_system_check

        register(Tags.compatibility)(comms_identity_system_check)
