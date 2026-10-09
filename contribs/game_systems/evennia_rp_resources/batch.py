# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Passive accrual, independent of RP and XP; one receipt per character/period."""

import logging
import math
import random
from collections import Counter

from django.db import transaction
from evennia.objects.models import ObjectDB

from evennia_links import periodic
from evennia_links.characters import playable_characters
from evennia_links.runtime import cap_raise, get

from . import conf
from .gathering import lean, matches_lean, pool
from .models import ResourceGrant
from .services import grant, total_held

logger = logging.getLogger("evennia")


def period_key(reference=None):
    """Label the completed period. Weekly defaults use the completed ISO week."""
    return periodic.period_key(get("RP_RESOURCES_PERIOD_SECONDS"), reference)


def eligible_characters():
    """Playable characters, even while offline; host eligibility is authoritative."""
    return playable_characters(conf.hook("RP_ECONOMY_ELIGIBLE"))


def holdings_cap(character):
    return get("RP_RESOURCES_BASE_CAP") + cap_raise(character, "resources")


def accrual_quantity(held, cap):
    """Linear taper, rounded up to whole units, bounded by the available space."""
    base = get("RP_RESOURCES_WEEKLY_QUANTITY")
    threshold = cap * get("RP_RESOURCES_TAPER_FRACTION")
    factor = min(1, max(0, (cap - held) / (cap - threshold)))
    return min(max(0, cap - held), math.ceil(base * factor))


def _allocation(character, week, resources):
    held = total_held(character)
    cap = holdings_cap(character)
    amount = accrual_quantity(held, cap)
    choice = lean(character)
    multiplier = get("RP_RESOURCES_LEAN_MULTIPLIER")
    weights = [
        resource.weight * (multiplier if matches_lean(resource, choice) else 1)
        for resource in resources
    ]
    rng = random.Random(f"rp-resources:{character.pk}:{week}")
    draws = rng.choices(resources, weights=weights, k=amount) if resources and amount else []
    quantities = dict(Counter(resource.key for resource in draws))
    return quantities, {
        "held": held,
        "cap": cap,
        "base": get("RP_RESOURCES_WEEKLY_QUANTITY"),
        "quantity": sum(quantities.values()),
        "tapered": amount < get("RP_RESOURCES_WEEKLY_QUANTITY"),
        "pool": [resource.key for resource in resources],
        "weights": weights,
        "lean": dict(choice) if choice else None,
    }


def run_weekly_batch(week=None, *, dry_run=False, characters=None):
    """Preview/pay a completed period. Repeats never pay again, even after spends.

    Each character commits independently. Errors are returned and logged, allowing
    the scheduler to retry failed characters without duplicating successful ones.
    No missed periods are synthesized for newly created characters.
    """
    week = week or period_key()
    if not isinstance(week, str) or not week or len(week) > 80:
        raise ValueError("Invalid batch period label.")
    resources = pool()
    result = {"week": week, "characters": {}, "errors": [], "failed": []}
    for character in eligible_characters() if characters is None else characters:
        try:
            with transaction.atomic():
                ObjectDB.objects.select_for_update().get(pk=character.pk)
                if ResourceGrant.objects.filter(
                    character=character, source="trickle", resource__isnull=True, week=week
                ).exists():
                    continue
                quantities, details = _allocation(character, week, resources)
                if not dry_run:
                    ResourceGrant.objects.create(
                        character=character,
                        quantity=0,
                        source="trickle",
                        week=week,
                        details=details,
                    )
                    for key, quantity in sorted(quantities.items()):
                        grant(character, key, quantity, "trickle", week=week)
                result["characters"][character.pk] = quantities
        except Exception as exc:
            logger.exception("Resources batch failed for #%s, period %s", character.pk, week)
            result["errors"].append(f"#{character.pk}: {exc}")
            result["failed"].append(character.pk)
    return result


def run_due_period(week, ids=None):
    """Scheduler entry point: pay everyone, or retry only `ids`; return failed ids."""
    characters = None
    if ids is not None:
        wanted = set(ids)
        characters = [c for c in eligible_characters() if c.pk in wanted]
    return run_weekly_batch(week, characters=characters)["failed"]
