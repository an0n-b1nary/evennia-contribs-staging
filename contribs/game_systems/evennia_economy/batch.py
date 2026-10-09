# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Passive income and once-only eligibility/reveal stipends; never RP quotas."""

import logging
import math
from datetime import UTC, datetime, timedelta

from django.db import transaction
from django.utils import timezone

from evennia_links.runtime import cap_raise, get

from . import conf
from .models import StipendPayment, UBIPayment
from .services import balance, credit, lock_characters, playable_accounts, require_open

logger = logging.getLogger("evennia")
ANCHOR = datetime(1970, 1, 5, tzinfo=UTC)


def on_runtime_change(sender, name, value, **kwargs):
    if name == "RP_ECONOMY_REVEALED" and value:
        run_stipends()


def period_key(reference=None):
    seconds = get("RP_ECONOMY_PERIOD_SECONDS")
    reference = (reference or timezone.now()).astimezone(UTC)
    index = int((reference - ANCHOR).total_seconds() // seconds)
    end = ANCHOR + timedelta(seconds=index * seconds)
    if seconds == 604800:
        year, week, _ = (end - timedelta(seconds=1)).isocalendar()
        return f"{year}-W{week:02d}"
    return f"{seconds}s:{end.isoformat()}"


def eligible_characters():
    predicate = conf.hook("RP_ECONOMY_ELIGIBLE")
    seen = set()
    for _, characters in playable_accounts():
        for character in characters:
            if character and character.pk not in seen:
                seen.add(character.pk)
                if predicate is None or predicate(character):
                    yield character


def money_cap(character):
    return math.ceil(
        get("RP_ECONOMY_WEEKLY_AMOUNT") * get("RP_ECONOMY_BASE_CAP_WEEKS")
    ) + cap_raise(character, "money")


def income_amount(held, cap):
    if cap <= 0:
        return 0
    threshold = cap * get("RP_ECONOMY_TAPER_FRACTION")
    factor = min(1, max(0, (cap - held) / (cap - threshold)))
    return min(max(0, cap - held), math.ceil(get("RP_ECONOMY_WEEKLY_AMOUNT") * factor))


def _stipends(character, *, dry_run=False):
    paid = {}
    kinds = ["starting", "reveal"] if get("RP_ECONOMY_REVEALED") else ["starting"]
    for kind in kinds:
        if StipendPayment.objects.filter(character=character, kind=kind).exists():
            continue
        amount = get(f"RP_ECONOMY_{kind.upper()}_STIPEND")
        paid[kind] = amount
        if not dry_run:
            StipendPayment.objects.create(character=character, kind=kind, amount=amount)
            if amount:
                credit(character, amount, kind=f"{kind}_stipend")
    return paid


def ensure_stipends(character):
    """Host approval hooks may call this immediately; scheduler also reconciles."""
    if not any(c.pk == character.pk for c in eligible_characters()):
        return {}
    with transaction.atomic():
        require_open()
        lock_characters(character)
        return _stipends(character)


def run_stipends():
    result = {"characters": {}, "errors": []}
    if get("RP_ECONOMY_FROZEN"):
        return result
    for character in eligible_characters():
        try:
            with transaction.atomic():
                require_open()
                lock_characters(character)
                result["characters"][character.pk] = _stipends(character)
        except Exception as exc:
            logger.exception("Economy stipend failed for #%s", character.pk)
            result["errors"].append(f"#{character.pk}: {exc}")
    return result


def run_weekly_batch(week=None, *, dry_run=False, characters=None):
    week = week or period_key()
    if not isinstance(week, str) or not week or len(week) > 80:
        raise ValueError("Invalid batch period label.")
    result = {"week": week, "characters": {}, "errors": [], "frozen": get("RP_ECONOMY_FROZEN")}
    if result["frozen"]:
        return result
    for character in eligible_characters() if characters is None else characters:
        try:
            with transaction.atomic():
                require_open()
                lock_characters(character)
                stipends = _stipends(character, dry_run=dry_run)
                if UBIPayment.objects.filter(character=character, week=week).exists():
                    continue
                held = balance(character) + (sum(stipends.values()) if dry_run else 0)
                cap = money_cap(character)
                amount = income_amount(held, cap)
                details = {
                    "held": held,
                    "cap": cap,
                    "base": get("RP_ECONOMY_WEEKLY_AMOUNT"),
                    "tapered": amount < get("RP_ECONOMY_WEEKLY_AMOUNT"),
                }
                if not dry_run:
                    UBIPayment.objects.create(
                        character=character, week=week, amount=amount, details=details
                    )
                    if amount:
                        credit(character, amount, kind="ubi", note=week)
                result["characters"][character.pk] = {"ubi": amount, "stipends": stipends}
        except Exception as exc:
            logger.exception("Economy batch failed for #%s, period %s", character.pk, week)
            result["errors"].append(f"#{character.pk}: {exc}")
    return result
