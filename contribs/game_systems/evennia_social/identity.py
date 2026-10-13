# SPDX-License-Identifier: BSD-3-Clause
"""Public staff-run identity without revealing account ownership or other alts."""

from django.conf import settings
from evennia.accounts.models import AccountDB

from evennia_links.characters import account_ids


def staff_run_marker(character):
    """Opt-in, current status; works offline and is unaffected by quelling."""
    if character is None or not getattr(settings, "SOCIAL_STAFF_RUN_MARKER", False):
        return ""
    if isinstance(character, AccountDB):
        accounts = [character]
    else:
        from django.apps import apps

        ids = set(account_ids(character))
        if apps.is_installed("evennia_npcs") and character.tags.has("npc", category="npc_system"):
            from evennia_npcs.services import record_for

            record = record_for(character)
            if record and record.controller:
                ids.update(account_ids(record.controller))
        accounts = AccountDB.objects.filter(pk__in=ids)
    permission = getattr(settings, "SOCIAL_STAFF_PERMISSION", "Builder")
    return (
        " (staff-run)"
        if any(
            account.is_superuser or account.permissions.check(permission) for account in accounts
        )
        else ""
    )
