# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_rptracker."""

from django.apps import AppConfig


class EvenniaRptrackerConfig(AppConfig):
    """AppConfig for the evennia_rptracker contrib."""

    name = "evennia_rptracker"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Evennia RP Tracker"

    def ready(self):
        from django.apps import apps
        from django.conf import settings

        from evennia_rptracker import signals  # noqa: F401 — registers signal objects

        label = getattr(settings, "RPTRACKER_SCENES_APP_LABEL", "evennia_scenes")
        if apps.is_installed(label) or any(cfg.label == label for cfg in apps.get_app_configs()):
            from evennia_links import connect_soft_ref_cleanup
            from evennia_rptracker import bridges_scenes  # noqa: F401 — registers @receiver
            from evennia_rptracker.models import RPSessionSceneLink

            try:
                scene_model = apps.get_model(label, "Scene")
                connect_soft_ref_cleanup(scene_model, RPSessionSceneLink, "scene_id")
            except LookupError:
                import logging

                logging.getLogger("evennia").warning(
                    "evennia_rptracker: RPTRACKER_SCENES_APP_LABEL=%r is in "
                    "INSTALLED_APPS but has no 'Scene' model — scene bridge skipped.",
                    label,
                )
