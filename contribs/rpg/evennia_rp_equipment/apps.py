# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django AppConfig for evennia_rp_equipment."""

from django.apps import AppConfig


class RPEquipmentConfig(AppConfig):
    """AppConfig for the evennia_rp_equipment contrib."""

    name = "evennia_rp_equipment"
    label = "evennia_rp_equipment"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Evennia RP Equipment"

    def ready(self):
        from evennia_rp_chargen.guards import build_change_requested

        from evennia_rp_equipment.guard import DISPATCH_UID, on_build_change

        # evennia_rp_chargen is a hard dependency, so the guard is always
        # connected: worn gear's requirements hold through every build change.
        build_change_requested.connect(on_build_change, dispatch_uid=DISPATCH_UID)
