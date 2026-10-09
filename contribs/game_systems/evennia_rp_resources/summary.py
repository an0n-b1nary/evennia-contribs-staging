# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Quiet first-login summaries; hidden accrual never consumes the seen marker."""

import logging

from evennia_links.runtime import get

from .models import ResourceGrant

logger = logging.getLogger("evennia")


def latest_receipt(character):
    return (
        ResourceGrant.objects.filter(character=character, source="trickle", resource__isnull=True)
        .order_by("-pk")
        .first()
    )


def gains_text(character, week):
    rows = ResourceGrant.objects.filter(
        character=character, source="trickle", week=week, quantity__gt=0
    ).select_related("resource")
    return ", ".join(f"{row.quantity} {row.resource.name}" for row in rows) or "none"


def notify_resource_summary(character):
    try:
        if not get("RP_RESOURCES_REVEALED"):
            return False
        receipt = latest_receipt(character)
        if not receipt or receipt.week == character.attributes.get("last_resource_summary_week"):
            return False
        message = f"This week you gathered: {gains_text(character, receipt.week)}."
        if receipt.details.get("tapered"):
            message += (
                " Your stores are full."
                if receipt.details.get("held", 0) >= receipt.details.get("cap", 0)
                else " Your stores are nearing capacity."
            )
        character.msg(message + " Use +resources to view your stores.")
        character.attributes.add("last_resource_summary_week", receipt.week)
        return True
    except Exception:
        logger.exception("Resource login summary failed for #%s", character.pk)
        return False
