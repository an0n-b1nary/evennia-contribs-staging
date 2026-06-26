# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_calendar."""

from django.apps import AppConfig


class CalendarConfig(AppConfig):
    """AppConfig for the evennia_calendar contrib."""

    name = "evennia_calendar"
    label = "evennia_calendar"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Evennia Calendar"

    def ready(self):
        import evennia_calendar.signals  # noqa: F401
