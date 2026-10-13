# SPDX-License-Identifier: BSD-3-Clause
from evennia.scripts.scripts import DefaultScript


class RetentionSweep(DefaultScript):
    def at_script_creation(self):
        self.key = "moderation-retention"
        self.interval = 86400
        self.persistent = True

    def at_repeat(self):
        from evennia_moderation.services import purge

        purge()


def ensure_retention_sweep():
    from evennia.scripts.models import ScriptDB
    from evennia.utils.create import create_script

    if not ScriptDB.objects.filter(db_key="moderation-retention").exists():
        create_script(RetentionSweep)
