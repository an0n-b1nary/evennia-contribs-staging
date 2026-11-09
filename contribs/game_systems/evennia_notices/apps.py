# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Inbox app; source modules are resolved lazily, never at startup."""

from django.apps import AppConfig


class EvenniaNoticesConfig(AppConfig):
    """Register only model-free signal listeners at readiness."""

    name = "evennia_notices"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from .listeners import register

        register()
