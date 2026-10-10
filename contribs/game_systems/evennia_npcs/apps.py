# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Registry-safe partner wiring."""

from django.apps import AppConfig


class NPCsConfig(AppConfig):
    name = "evennia_npcs"
    verbose_name = "Evennia NPCs"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.apps import apps
        from django.db.models.signals import pre_delete

        from . import conf, integrations

        conf.register_runtime()
        pre_delete.connect(integrations.object_deleting, dispatch_uid="npcs.object_deleting")
        for cfg in apps.get_app_configs():
            if cfg.label == conf.get("NPCS_SCENES_APP_LABEL"):
                integrations.connect_scenes(cfg)
            if cfg.label == conf.get("NPCS_PLOTS_APP_LABEL"):
                integrations.connect_plots(cfg)
