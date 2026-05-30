# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_links.

Registers the contrib as a Django app. This contrib ships only abstract
models (no tables), so there are no migrations and no ready() wiring needed
— that wiring lives in the downstream game's glue app instead.
"""

from django.apps import AppConfig


class EvenniaLinksConfig(AppConfig):
    """AppConfig for the evennia_links contrib."""

    name = "evennia_links"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Evennia Links"
