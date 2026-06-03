# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
XP award service for evennia_xp.

Single entry point: record_xp(). All XP writes flow through here so that
idempotency, CharacterXP aggregation, and the xp_awarded signal are handled
in one place.

Usage::

    from evennia_xp.awards import record_xp
    from evennia_xp.models import XPLog

    log = record_xp(
        character_id=char.pk,
        amount=Decimal("1.0"),
        source_type=XPLog.SourceType.RP_SESSION,
        source_ref_id=session.pk,
        week="2026-W18",
        character_name=char.key,
    )
    if log is None:
        pass  # already awarded (idempotent no-op)

For MANUAL_GRANT, call with source_type=MANUAL_GRANT; source_ref_id is
ignored and will be set to the row's own pk after creation.
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger("evennia")


def _current_week() -> str:
    """Return the current ISO week string, e.g. '2026-W18'."""
    now = timezone.now()
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _resolve_character_name(character_id: int, fallback: str = "") -> str:
    """Try to look up the character's current display name via Evennia."""
    if fallback:
        return fallback
    try:
        import evennia

        results = evennia.search_object(f"#{character_id}", global_search=True)
        if results:
            return results[0].key
    except Exception:
        pass
    return ""


def record_xp(
    character_id: int,
    amount,
    source_type: str,
    source_ref_id: int,
    *,
    week: str = "",
    reason: str = "",
    character_name: str = "",
    multiplier_applied=None,
    granted_by=None,
):
    """Write one XPLog row and update CharacterXP aggregates atomically.

    For non-MANUAL_GRANT sources, this is idempotent: if a row with the
    same (source_type, source_ref_id) already exists, returns None without
    modifying anything. The weekly batch relies on this guarantee.

    For MANUAL_GRANT, a new row is always created (no duplicate check).
    source_ref_id is set to the row's own pk immediately after creation.

    Args:
        character_id: ObjectDB pk of the recipient character.
        amount: XP to award. Converted to Decimal internally.
        source_type: One of XPLog.SourceType choices.
        source_ref_id: PK of the upstream item (RPSession, LoreEntry, etc.).
            Ignored for MANUAL_GRANT.
        week: ISO week string (e.g. "2026-W18"). Defaults to current week.
        reason: Human-readable description. Required for MANUAL_GRANT.
        character_name: Display name for denormalization. Auto-resolved if empty.
        multiplier_applied: Decimal multiplier that was active. Defaults to 1.0.
        granted_by: ObjectDB staff character for MANUAL_GRANT audit trail.

    Returns:
        XPLog instance if a new row was created, None if already awarded.
    """
    from evennia_xp.models import CharacterXP, XPLog
    from evennia_xp.signals import xp_awarded

    amount = Decimal(str(amount))
    if multiplier_applied is None:
        multiplier_applied = Decimal("1.0")
    else:
        multiplier_applied = Decimal(str(multiplier_applied))

    if not week:
        week = _current_week()

    name = _resolve_character_name(character_id, fallback=character_name)

    is_manual = source_type == XPLog.SourceType.MANUAL_GRANT

    with transaction.atomic():
        if is_manual:
            log = XPLog.objects.create(
                character_id=character_id,
                character_name=name,
                amount=amount,
                source_type=source_type,
                source_ref_id=0,  # temporary; replaced below
                week=week,
                reason=reason,
                multiplier_applied=multiplier_applied,
                granted_by_id=granted_by.pk if granted_by else None,
                granted_by_name=granted_by.key if granted_by else "",
            )
            # Use own pk as source_ref_id so each manual grant is addressable.
            log.source_ref_id = log.pk
            log.save(update_fields=["source_ref_id"])
            created = True
        else:
            log, created = XPLog.objects.get_or_create(
                source_type=source_type,
                source_ref_id=source_ref_id,
                defaults={
                    "character_id": character_id,
                    "character_name": name,
                    "amount": amount,
                    "week": week,
                    "reason": reason,
                    "multiplier_applied": multiplier_applied,
                },
            )

        if not created:
            return None

        # Update (or create) the CharacterXP aggregate row.
        rows_updated = CharacterXP.objects.filter(character_id=character_id).update(
            total_earned=F("total_earned") + amount,
            current_balance=F("current_balance") + amount,
            last_payout_week=week,
        )
        if not rows_updated:
            CharacterXP.objects.create(
                character_id=character_id,
                character_name=name,
                total_earned=amount,
                total_spent=Decimal("0.00"),
                current_balance=amount,
                last_payout_week=week,
            )

    xp_awarded.send(
        sender=XPLog,
        character_id=character_id,
        xplog=log,
        source_type=source_type,
    )
    return log
