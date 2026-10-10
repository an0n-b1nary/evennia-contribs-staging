# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_guides."""

from django.apps import AppConfig


class GuidesConfig(AppConfig):
    """AppConfig for the evennia_guides contrib.

    Pages load lazily, on first use, so app order doesn't matter here: every
    installed app's ``guides/`` directory is found whenever the first page is
    read.
    """

    name = "evennia_guides"
    label = "evennia_guides"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Evennia Guides"
