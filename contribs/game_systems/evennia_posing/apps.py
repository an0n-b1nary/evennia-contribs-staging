# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_posing.

Registers the contrib as a Django app for consistency with the other
contribs in this repo. No models, so no migrations; no `ready()` method —
this contrib has no soft-dependency wiring to perform at app-load time
(the accessibility soft-import happens lazily in commands.py instead).
"""

from django.apps import AppConfig


class EvenniaPosingConfig(AppConfig):
    """AppConfig for the evennia_posing contrib."""

    name = "evennia_posing"
    default_auto_field = "django.db.models.BigAutoField"
