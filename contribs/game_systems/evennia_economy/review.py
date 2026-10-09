# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Amount/time/account-based review flags. No automatic penalties."""

import logging
from datetime import timedelta

from django.db import transaction

from . import conf
from .models import LedgerEntry, ReviewFlag

logger = logging.getLogger("evennia")


def _notify(title, description):
    try:
        hook = conf.hook("RP_ECONOMY_FLAG_REVIEW_HOOK")
        if hook:
            hook(title, description)
    except Exception:
        logger.exception("Economy staff review hook failed; flag retained in +economy/flags")


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
