# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Amount/time/account-based review flags. No automatic penalties."""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from evennia_links.runtime import get

from . import conf
from .models import LedgerEntry, ReviewFlag, Storefront

logger = logging.getLogger("evennia")


def _notify(title, description):
    try:
        hook = conf.hook("RP_ECONOMY_FLAG_REVIEW_HOOK")
        if hook:
            hook(title, description)
    except Exception:
        logger.exception("Economy staff review hook failed; flag retained in +economy/flags")


def flag_event(kind, event_key, title, description, *, entry=None):
    flag, created = ReviewFlag.objects.get_or_create(
        event_key=event_key,
        defaults={"kind": kind, "title": title, "description": description, "first_entry": entry},
    )
    if created:
        transaction.on_commit(lambda: _notify(flag.title, flag.description))
    return flag


def flag_quiet_stalls(now=None):
    now = now or timezone.now()
    cutoff = now - timedelta(weeks=get("RP_ECONOMY_QUIET_STALL_WEEKS"))
    flagged = []
    for initial in Storefront.objects.filter(status="open", last_active__lte=cutoff):
        with transaction.atomic():
            store = Storefront.objects.select_for_update().get(pk=initial.pk)
            if store.status != "open" or store.last_active > cutoff:
                continue
            flagged.append(
                flag_event(
                    "quiet_stall",
                    f"quiet:{store.pk}:{store.last_active.isoformat()}",
                    "Economy: quiet stall",
                    f"Stall #{store.pk} ({store.name}), owner #{store.owner_id}, room #{store.room_id}, has had no owner login, listing, unlisting or sale since {store.last_active.isoformat()}. Review only; stock is retained. Staff may use +stall/close {store.pk} to return it.",
                )
            )
    return flagged


def flag_round_trips(entry):
    if not entry.from_accounts or not entry.to_accounts or not entry.assets:
        return
    prior = LedgerEntry.objects.filter(
        kind="exchange",
        created__gte=entry.created - timedelta(days=7),
        pk__lt=entry.pk,
    ).exclude(from_id=entry.to_id)
    for first in prior:
        if (
            first.assets
            and set(first.from_accounts) & set(entry.to_accounts)
            and set(first.to_accounts) & set(entry.from_accounts)
        ):
            title = "Economy: possible asset round trip"
            description = f"Ledger #{first.pk}: {first.from_name} (#{first.from_id}) to {first.to_name} (#{first.to_id}); ledger #{entry.pk}: {entry.from_name} (#{entry.from_id}) to {entry.to_name} (#{entry.to_id}) within seven days. Asset kinds may differ. Review only; no penalty applied."
            flag, created = ReviewFlag.objects.get_or_create(
                first_entry=first,
                second_entry=entry,
                defaults={"title": title, "description": description},
            )
            if created:
                transaction.on_commit(lambda row=flag: _notify(row.title, row.description))
