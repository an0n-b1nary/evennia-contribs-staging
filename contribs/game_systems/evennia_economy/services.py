# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""All currency writes use conditional updates and the caller's transaction."""

from django.db import transaction
from django.db.models import F
from evennia.objects.models import ObjectDB

from evennia_links.characters import account_ids, playable_accounts, same_account  # noqa: F401
from evennia_links.runtime import get

from . import conf
from .models import LedgerEntry, Purse


class EconomyError(ValueError):
    pass


def require_open():
    if get("RP_ECONOMY_FROZEN"):
        raise EconomyError("The market is closed for the moment.")


def quantity(amount):
    if type(amount) is not int or amount <= 0 or amount > 2**63 - 1:
        raise EconomyError("Amount must be a positive whole number within the supported range.")
    return amount


def lock_characters(*characters):
    # Matches resources' character-before-holding order, for both directions.
    return list(
        ObjectDB.objects.select_for_update()
        .filter(pk__in=sorted({c.pk for c in characters}))
        .order_by("pk")
    )


def balance(character):
    return Purse.objects.filter(character=character).values_list("balance", flat=True).first() or 0


def _adjust(character, delta):
    purse, _ = Purse.objects.get_or_create(character=character)
    query = Purse.objects.filter(pk=purse.pk)
    if delta < 0:
        query = query.filter(balance__gte=-delta)
    else:
        query = query.filter(balance__lte=2**63 - 1 - delta)
    if not query.update(balance=F("balance") + delta):
        raise EconomyError("Insufficient funds or balance exceeds the supported range.")


def journal(kind, *, giver=None, recipient=None, amount=0, **metadata):
    actor = metadata.pop("by", None)
    return LedgerEntry.objects.create(
        kind=kind,
        from_id=getattr(giver, "pk", None),
        to_id=getattr(recipient, "pk", None),
        from_name=giver.key if giver else "",
        to_name=recipient.key if recipient else "",
        from_accounts=account_ids(giver),
        to_accounts=account_ids(recipient),
        amount=amount,
        by_id=getattr(actor, "pk", actor),
        **metadata,
    )


def credit(character, amount, *, kind="staff", by=None, note=""):
    quantity(amount)
    with transaction.atomic():
        require_open()
        lock_characters(character)
        _adjust(character, amount)
        return journal(kind, recipient=character, amount=amount, by=by, note=note)


def debit(character, amount, *, kind="staff", by=None, note=""):
    quantity(amount)
    with transaction.atomic():
        require_open()
        lock_characters(character)
        _adjust(character, -amount)
        return journal(kind, giver=character, amount=amount, by=by, note=note)


def fee(kind, actor, context=None):
    if kind not in conf.FEE_KINDS:
        raise EconomyError("Unknown fee kind.")
    policy = conf.hook("RP_ECONOMY_FEE_POLICY")
    amount = policy(kind, actor, context or {}) if policy else get(f"RP_ECONOMY_FEE_{kind.upper()}")
    if type(amount) is not int or not 0 <= amount <= 2**63 - 1:
        raise EconomyError("Fee policy must return a nonnegative whole number.")
    return amount


def charge_fee(kind, actor, context=None, *, exchange_id=None):
    """Call inside the feature's transaction; failure rolls that feature back."""
    with transaction.atomic():
        require_open()
        lock_characters(actor)
        amount = fee(kind, actor, context)
        if amount:
            _adjust(actor, -amount)
            journal(
                "fee",
                giver=actor,
                amount=amount,
                fee=amount,
                fee_kind=kind,
                exchange_id=exchange_id,
            )
        return amount


def on_purse_deleted(sender, instance, **kwargs):
    """Burn a deleted character's balance in the journal, so reconciliation still balances.

    Purses only go away with their character (the foreign key cascades). The
    row records the character's name and accounts while they can still be read.
    """
    if instance.balance:
        journal(
            "deleted",
            giver=instance.character,
            amount=instance.balance,
            note="Balance removed with its character.",
        )
