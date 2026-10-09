# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from evennia_links.runtime import get

from . import conf
from .models import StipendPayment, UBIPayment


def notify_economy_summary(character):
    """One quiet login message; dark accrual never notifies, including staff."""
    if not get("RP_ECONOMY_REVEALED"):
        return False
    payment = UBIPayment.objects.filter(character=character).order_by("-pk").first()
    stipends = list(StipendPayment.objects.filter(character=character).order_by("pk"))
    marker = [payment.pk if payment else None, [row.pk for row in stipends]]
    previous = character.attributes.get("last_economy_summary")
    if (not payment and not stipends) or previous == marker:
        return False
    new_stipends = previous is None or list(previous[1]) != marker[1]
    full = bool(payment and payment.amount == 0 and payment.details.get("tapered"))
    told_full = character.attributes.get("economy_full_notified", default=False)
    character.attributes.add("last_economy_summary", marker)
    character.attributes.add("economy_full_notified", full)
    if full and told_full and not new_stipends:
        return False  # still at the cap and already told; never nag weekly
    message = (
        f"Your latest income: {conf.currency(payment.amount)}."
        if payment
        else "Your purse is ready."
    )
    if stipends:
        message += f" Stipends received: {conf.currency(sum(row.amount for row in stipends))}."
    if full and not told_full:
        message += " Your purse is at its income cap."
    elif payment and payment.details.get("tapered") and not full:
        message += " Your purse is near its income cap."
    character.msg(message + " See +balance.")
    return True
