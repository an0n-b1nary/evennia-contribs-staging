# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Explicit, disabled-aware startup maintenance with own-instance safeguards."""

from django.conf import settings
from django.db import transaction
from django.db.models import F
from evennia.scripts.scripts import DefaultScript


class NoticeMaintenance(DefaultScript):
    """Daily idempotent source recheck, compaction and retention."""

    def at_script_creation(self):
        self.key = "notices-maintenance"
        self.interval = 86400
        self.persistent = True

    def at_repeat(self):
        if getattr(settings, "NOTICES_ENABLED", True):
            from .services import maintain

            maintain()


def ensure_notice_maintenance():
    """Create/restart one own script; never adopt a foreign same-key instance."""
    if not getattr(settings, "NOTICES_ENABLED", True):
        return None
    from evennia.scripts.models import ScriptDB
    from evennia.server.models import ServerConfig
    from evennia.utils.create import create_script

    with transaction.atomic():
        # Stable unique lock works for empty first creation as well as restarts.
        if not ServerConfig.objects.filter(db_key="notices-maintenance-lock").update(
            db_value=F("db_value")
        ):
            ServerConfig.objects.get_or_create(
                db_key="notices-maintenance-lock", defaults={"db_value": ""}
            )
            ServerConfig.objects.filter(db_key="notices-maintenance-lock").update(
                db_value=F("db_value")
            )
        ServerConfig.objects.select_for_update().get(db_key="notices-maintenance-lock")
        scripts = list(ScriptDB.objects.filter(db_key="notices-maintenance").order_by("pk"))
        path = f"{NoticeMaintenance.__module__}.{NoticeMaintenance.__name__}"
        if any(script.db_typeclass_path != path for script in scripts):
            raise ValueError("A foreign script already uses the notices maintenance key")
        if not scripts:
            return create_script(NoticeMaintenance)
        script = scripts[0]
        for duplicate in scripts[1:]:
            duplicate.delete()
        if not script.is_active:
            script.start()
        return script
