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
    if (not payment and not stipends) or character.attributes.get("last_economy_summary") == marker:
        return False
    message = (
        f"Your latest income: {conf.currency(payment.amount)}."
        if payment
        else "Your purse is ready."
    )
    if stipends:
        message += f" Stipends received: {conf.currency(sum(row.amount for row in stipends))}."
    if payment and payment.details.get("tapered"):
        message += " Your purse is at or near its income cap."
    character.msg(message + " See +balance.")
    character.attributes.add("last_economy_summary", marker)
    return True
