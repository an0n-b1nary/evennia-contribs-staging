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
        gains = gains_text(character, receipt.week)
        details = receipt.details
        full = "cap" in details and details.get("held", 0) >= details["cap"]
        told_full = character.attributes.get("resource_full_notified", default=False)
        character.attributes.add("last_resource_summary_week", receipt.week)
        character.attributes.add("resource_full_notified", full)
        if full and told_full and gains == "none":
            return False  # still full and already told; never nag weekly
        message = f"This week you gathered: {gains}."
        if full and not told_full:
            message += " Your stores are full."
        elif details.get("tapered") and not full:
            message += " Your stores are nearing capacity."
        character.msg(message + " Use +resources to view your stores.")
        return True
    except Exception:
        logger.exception("Resource login summary failed for #%s", character.pk)
        return False
