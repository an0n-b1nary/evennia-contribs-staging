# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from django.db.models import Sum
from evennia.accounts.models import AccountDB

from evennia_links.collect import collect_dicts

from .models import LedgerEntry, Purse, StipendPayment, UBIPayment
from .services import playable_accounts
from .signals import economy_figures


def account_accrual():
    """Lifetime UBI and stipends, and current balances, over each playable list."""
    result = []
    for account_id, characters in playable_accounts():
        account = AccountDB.objects.get(pk=account_id)
        ids = list({c.pk for c in characters})
        if not ids:
            continue

        def total(model, field, character_ids=ids):
            return (
                model.objects.filter(character_id__in=character_ids).aggregate(total=Sum(field))[
                    "total"
                ]
                or 0
            )

        result.append(
            {
                "id": account.pk,
                "name": account.key,
                "characters": len(ids),
                "balance": total(Purse, "balance"),
                "ubi": total(UBIPayment, "amount"),
                "stipends": total(StipendPayment, "amount"),
            }
        )
    return result


def reconciliation():
    minted = (
        LedgerEntry.objects.filter(from_id__isnull=True).aggregate(total=Sum("amount"))["total"]
        or 0
    )
    burned = (
        LedgerEntry.objects.filter(to_id__isnull=True).aggregate(total=Sum("amount"))["total"] or 0
    )
    held = Purse.objects.aggregate(total=Sum("balance"))["total"] or 0
    return {
        "money": {"minted": minted, "burned": burned, "held": held},
        **collect_dicts(economy_figures, sender=Purse),
    }
