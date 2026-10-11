# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Lazy, registry-gated partner integration."""

from django.apps import AppConfig


class RPCombatConfig(AppConfig):
    name = "evennia_rp_combat"
    verbose_name = "Evennia RP Combat"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.apps import apps
        from django.core.checks import register

        from . import conf
        from .checks import check_configuration

        conf.register_runtime()
        register(check_configuration)
        if apps.is_installed(conf.get("RP_COMBAT_CHARGEN_APP_LABEL")):
            from .integrations import connect_chargen

            connect_chargen()
        from django.db.models.signals import post_delete

        from .maintenance import note_pose, object_deleted

        post_delete.connect(object_deleted, weak=False, dispatch_uid="rp_combat.object_deleted")
        if apps.is_installed("evennia_posing"):
            from evennia_posing.signals import pose_recorded

            pose_recorded.connect(note_pose, weak=False, dispatch_uid="rp_combat.pose")
        if apps.is_installed("evennia_npcs"):
            from evennia_npcs.signals import npc_pose_recorded

            npc_pose_recorded.connect(note_pose, weak=False, dispatch_uid="rp_combat.npc_pose")
