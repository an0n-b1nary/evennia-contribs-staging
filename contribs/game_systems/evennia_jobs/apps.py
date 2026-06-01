# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_jobs."""

from django.apps import AppConfig


class JobsConfig(AppConfig):
    """AppConfig for the evennia_jobs contrib."""

    name = "evennia_jobs"
    label = "evennia_jobs"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Evennia Jobs"
