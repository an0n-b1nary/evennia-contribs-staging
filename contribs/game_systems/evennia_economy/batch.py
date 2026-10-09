# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Passive income and once-only eligibility/reveal stipends; never RP quotas.

The reveal stipend is an event, not a second starting stipend. It's paid only
when a game that has run hidden is revealed: to every character eligible at that
moment, plus anyone who had already received a starting stipend before it (so a
sweep failure is made good later). A game that is never hidden never pays it,
and characters who first become eligible after the reveal get only the starting
stipend. Hiding and revealing again pays nothing more.
"""

import logging
import math

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from evennia_links import periodic
from evennia_links.characters import is_playable, playable_characters
from evennia_links.runtime import cap_raise, get

from . import conf
from .models import StipendPayment, UBIPayment
from .services import balance, credit, lock_characters, require_open

logger = logging.getLogger("evennia")
HIDDEN_MARKER = "economy:hidden_seen"
REVEALED_MARKER = "economy:revealed_at"


def _marker(key):
    from evennia.server.models import ServerConfig
    from evennia.utils.dbserialize import from_pickle

    # Read past Evennia's identity cache, as evennia_links.runtime does.
    raw = ServerConfig.objects.filter(db_key=key).values_list("db_value", flat=True).first()
    return from_pickle(raw) if raw is not None else None


def _set_marker(key, **extra):
    from evennia.server.models import ServerConfig

    ServerConfig.objects.conf(key, {"at": timezone.now().isoformat(), **extra})


def revealed_at():
    """The reveal of a game that ran hidden ({"at", "last_stipend"}), or None.

    `last_stipend` is the newest stipend row at the reveal; ids, unlike clocks,
    order a starting stipend before or after it exactly.
    """
    return _marker(REVEALED_MARKER)


def note_visibility():
    """Record that the game ran hidden, and run the reveal sweep once it's revealed.

    Called by the scheduler every tick and by runtime changes, so a reveal made
    through settings and a restart is noticed too. While frozen the sweep waits.
    """
    if not get("RP_ECONOMY_REVEALED"):
        if _marker(HIDDEN_MARKER) is None:
            _set_marker(HIDDEN_MARKER)
        return None
    if _marker(HIDDEN_MARKER) is None or revealed_at() is not None or get("RP_ECONOMY_FROZEN"):
        return None
    last = StipendPayment.objects.aggregate(last=Max("pk"))["last"] or 0
    _set_marker(REVEALED_MARKER, last_stipend=last)
    return run_stipends(at_reveal=True)


def on_runtime_change(sender, name, value, **kwargs):
    if name in ("RP_ECONOMY_REVEALED", "RP_ECONOMY_FROZEN"):
        note_visibility()


def period_key(reference=None):
    return periodic.period_key(get("RP_ECONOMY_PERIOD_SECONDS"), reference)


def eligible_characters():
    return playable_characters(conf.hook("RP_ECONOMY_ELIGIBLE"))


def is_eligible(character):
    return is_playable(character, conf.hook("RP_ECONOMY_ELIGIBLE"))


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


def _owes_reveal(paid, revealed, at_reveal):
    """`paid` maps kind -> stipend id; see the rule in the module docstring."""
    if not revealed or "reveal" in paid:
        return False
    return at_reveal or paid.get("starting", float("inf")) <= revealed["last_stipend"]


def _owed(character, *, at_reveal=False):
    """The stipend kinds `character` is still owed."""
    paid = dict(StipendPayment.objects.filter(character=character).values_list("kind", "pk"))
    kinds = [] if "starting" in paid else ["starting"]
    if _owes_reveal(paid, revealed_at(), at_reveal):
        kinds.append("reveal")
    return kinds


def _stipends(character, *, dry_run=False, at_reveal=False):
    paid = {}
    for kind in _owed(character, at_reveal=at_reveal):
        amount = get(f"RP_ECONOMY_{kind.upper()}_STIPEND")
        paid[kind] = amount
        if not dry_run:
            StipendPayment.objects.create(character=character, kind=kind, amount=amount)
            if amount:
                credit(character, amount, kind=f"{kind}_stipend")
    return paid


def ensure_stipends(character):
    """Pay what one character is owed. Host approval or login hooks call this."""
    if not _owed(character) or not is_eligible(character):
        return {}
    with transaction.atomic():
        require_open()
        lock_characters(character)
        return _stipends(character)


def run_stipends(*, at_reveal=False):
    """Pay every eligible character what they're owed; staff reconciliation and the reveal.

    Characters already paid are skipped before the eligibility predicate runs.
    """
    result = {"characters": {}, "errors": []}
    if get("RP_ECONOMY_FROZEN"):
        return result
    revealed = revealed_at()
    predicate = conf.hook("RP_ECONOMY_ELIGIBLE")
    paid = {}
    for character_id, kind, pk in StipendPayment.objects.values_list("character_id", "kind", "pk"):
        paid.setdefault(character_id, {})[kind] = pk
    for character in playable_characters():
        done = paid.get(character.pk, {})
        owed = "starting" not in done or _owes_reveal(done, revealed, at_reveal)
        if not owed or (predicate is not None and not predicate(character)):
            continue
        try:
            with transaction.atomic():
                require_open()
                lock_characters(character)
                result["characters"][character.pk] = _stipends(character, at_reveal=at_reveal)
        except Exception as exc:
            logger.exception("Economy stipend failed for #%s", character.pk)
            result["errors"].append(f"#{character.pk}: {exc}")
    return result


def run_weekly_batch(week=None, *, dry_run=False, characters=None):
    week = week or period_key()
    if not isinstance(week, str) or not week or len(week) > 80:
        raise ValueError("Invalid batch period label.")
    result = {
        "week": week,
        "characters": {},
        "errors": [],
        "failed": [],
        "frozen": get("RP_ECONOMY_FROZEN"),
    }
    if result["frozen"]:
        return result
    if not dry_run:
        note_visibility()
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
            result["failed"].append(character.pk)
    return result


def run_due_period(week, ids=None):
    """Scheduler entry point: pay everyone, or retry only `ids`; return failed ids."""
    characters = None
    if ids is not None:
        wanted = set(ids)
        characters = [c for c in eligible_characters() if c.pk in wanted]
    return run_weekly_batch(week, characters=characters)["failed"]
