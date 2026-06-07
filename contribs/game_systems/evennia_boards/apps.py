# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_boards."""

import logging

from django.apps import AppConfig

logger = logging.getLogger("evennia")


class BoardsConfig(AppConfig):
    """AppConfig for the evennia_boards contrib."""

    name = "evennia_boards"
    label = "evennia_boards"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Evennia Boards"

    def ready(self):
        import evennia_boards.listeners as _listeners
        import evennia_boards.signals  # noqa: F401

        _listeners.connect()
        self._register_calendar_cleanup()

    def _register_calendar_cleanup(self):
        """Register soft-ref cascade cleanup for PostCalendarLink.event_id.

        Opt-in: dormant unless BOARDS_CALENDAR_APP_LABEL names an app whose
        label is present in INSTALLED_APPS (and which exposes a CalendarEvent
        model). When dormant, PostCalendarLink rows orphan harmlessly on
        CalendarEvent deletion. Default is None — no auto-wiring.
        """
        from django.apps import apps
        from django.conf import settings

        calendar_label = getattr(settings, "BOARDS_CALENDAR_APP_LABEL", None)
        if not calendar_label:
            return
        if not apps.is_installed(calendar_label) and not any(
            app_config.label == calendar_label for app_config in apps.get_app_configs()
        ):
            return

        try:
            from evennia_links import connect_soft_ref_cleanup

            CalendarEvent = apps.get_model(calendar_label, "CalendarEvent")
            from evennia_boards.models import PostCalendarLink

            connect_soft_ref_cleanup(
                CalendarEvent,
                PostCalendarLink,
                "event_id",
            )
        except Exception:
            logger.exception("evennia_boards: failed to register PostCalendarLink cleanup hook")
