# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Atomic, idempotent XP debits and refunds, separate from the earn ledger."""

from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from evennia_xp.models import CharacterXP, XPSpend
from evennia_xp.signals import xp_refunded, xp_spent


class InsufficientXP(Exception):
    """No balance row exists, or it cannot cover the requested debit."""


def _amount(value):
    try:
        amount = Decimal(str(value))
        valid = (
            amount.is_finite()
            and 0 < amount <= Decimal("99999999.99")
            and amount == amount.quantize(Decimal("0.01"))
        )
    except (InvalidOperation, ValueError):
        valid = False
    if not valid:
        raise ValueError("XP spends must be positive amounts with at most two decimal places.")
    return amount


def spend_xp(character_id, amount, *, ref_key, category="ability", reason=""):
    """Debit once per globally unique reference; a matching retry returns its row.

    Reusing a reference for another character, amount or category is an error.
    Retrying a refunded spend never debits it again. Signals run after commit,
    including when a caller wraps this service in a larger atomic purchase.
    """
    amount = _amount(amount)
    if not isinstance(ref_key, str) or not ref_key.strip() or len(ref_key) > 128:
        raise ValueError("ref_key must be a nonempty string of at most 128 characters.")
    if not isinstance(category, str) or not category.strip() or len(category) > 64:
        raise ValueError("category must be a nonempty string of at most 64 characters.")
    if not isinstance(reason, str) or len(reason) > 500:
        raise ValueError("reason must be a string of at most 500 characters.")
    with transaction.atomic():
        # Write before reading: SQLite serializes competing writers here.
        try:
            with transaction.atomic():
                spend = XPSpend.objects.create(
                    character_id=character_id,
                    amount=amount,
                    ref_key=ref_key,
                    category=category,
                    reason=reason,
                )
        except IntegrityError:
            spend = XPSpend.objects.filter(ref_key=ref_key).first()
            if spend is None:
                raise
            if (spend.character_id, spend.amount, spend.category) != (
                character_id,
                amount,
                category,
            ):
                raise ValueError("ref_key already belongs to a different XP spend.") from None
            return spend
        updated = CharacterXP.objects.filter(
            character_id=character_id,
            current_balance__gte=amount,
        ).update(
            current_balance=F("current_balance") - amount,
            total_spent=F("total_spent") + amount,
            updated_at=timezone.now(),
        )
        if updated != 1:
            raise InsufficientXP("Not enough XP.")
        transaction.on_commit(
            lambda: xp_spent.send(
                sender=XPSpend,
                character_id=character_id,
                spend=spend,
            )
        )
    return spend


def refund_xp(character_id, *, ref_key, by=None):
    """Return the original debit once, or zero for a missing/already refunded row."""
    with transaction.atomic():
        updated = XPSpend.objects.filter(
            character_id=character_id,
            ref_key=ref_key,
            refunded_at__isnull=True,
        ).update(refunded_at=timezone.now(), refunded_by_id=getattr(by, "pk", None))
        if not updated:
            return Decimal(0)
        spend = XPSpend.objects.get(character_id=character_id, ref_key=ref_key)
        updated = CharacterXP.objects.filter(character_id=character_id).update(
            current_balance=F("current_balance") + spend.amount,
            total_spent=F("total_spent") - spend.amount,
            updated_at=timezone.now(),
        )
        if updated != 1:
            raise InsufficientXP("The XP balance row is missing; refund was rolled back.")
        transaction.on_commit(
            lambda: xp_refunded.send(
                sender=XPSpend,
                character_id=character_id,
                spend=spend,
            )
        )
    return spend.amount
