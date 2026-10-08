# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Projected XP: what the next weekly batch would pay a character so far.

``project_for_character`` runs every collector in ``XP_COLLECTORS`` with
``window_end`` = now and keeps the awards for one character, leaving out any
that an ``XPLog`` row already records (the batch's own idempotency key,
``(source_type, source_ref_id)``). Nothing is written to the XP ledger and no
anti-gaming sweep runs, so a session a sweep would later flag can still appear
here: it is a projection, not a promise.

Collectors may create their own eligibility rows with ``get_or_create`` (the
shipped lore and plots collectors do). Those are idempotent markers the batch
reuses; a projection never makes the batch award twice.

Cost: every collector runs over every character, and the results are then
filtered to one character. That is fine on demand, for one player's command,
but don't call it in a loop over the roster.

Two consumers ship:

* ``+xp`` shows a "Projected" block whenever collectors are registered.
* ``activity_lines`` fits evennia-rptracker's ``+activity`` hook::

      RPTRACKER_XP_PROJECTION = "evennia_xp.projection.activity_lines"
"""

import logging
from collections import namedtuple
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

try:
    from evennia_accessibility import uses_screenreader
except ImportError:

    def uses_screenreader(_):
        """Fallback when evennia-accessibility is not installed."""
        return False


logger = logging.getLogger("evennia")

#: ``by_source`` maps each registered collector key to a Decimal, in
#: registry order (zero when it yields nothing for this character).
XPProjection = namedtuple("XPProjection", ["by_source", "total"])


def source_label(key):
    """Display label for a collector key: the XPLog source label if it is one."""
    from evennia_xp.models import XPLog

    try:
        return XPLog.SourceType(key).label
    except ValueError:
        return key.replace("_", " ").title()


def project_for_character(character_id, window_end=None):
    """Return the unawarded XP the registered collectors would pay *character_id*.

    A collector that raises is logged and counts as zero; the others still run.

    Args:
        character_id (int): ObjectDB pk of the character.
        window_end (datetime, optional): end of the collectors' window.
            Defaults to now.

    Returns:
        XPProjection: ``by_source`` (dict of collector key to Decimal) and
        ``total`` (Decimal).
    """
    from evennia_xp.batch import _resolve_dotted
    from evennia_xp.models import XPLog

    if window_end is None:
        window_end = timezone.now()

    registered = getattr(settings, "XP_COLLECTORS", [])
    by_source = {key: Decimal("0.00") for key, _path in registered}
    pending = []
    for key, path in registered:
        try:
            pending.extend(
                (key, award)
                for award in _resolve_dotted(path)(window_end)
                if award.character_id == character_id
            )
        except Exception:
            logger.exception("XP projection: collector %r raised an exception", key)

    if pending:
        already_awarded = set(
            XPLog.objects.filter(
                source_ref_id__in={award.source_ref_id for _key, award in pending}
            ).values_list("source_type", "source_ref_id")
        )
        for key, award in pending:
            if (award.source_type, award.source_ref_id) not in already_awarded:
                by_source[key] += award.amount

    return XPProjection(by_source=by_source, total=sum(by_source.values(), Decimal("0.00")))


def activity_lines(character_pk, window_end):
    """``RPTRACKER_XP_PROJECTION`` hook: projected-XP lines for ``+activity``.

    Lists the sources with something pending and the total, or says nothing is
    pending yet. Plain text under screen-reader mode. Returns ``[]`` when no
    collectors are registered or anything goes wrong, because ``+activity``
    calls this without a guard of its own.

    Args:
        character_pk (int): ObjectDB pk of the character running ``+activity``.
        window_end (datetime): passed through to the collectors (now).

    Returns:
        list[str]
    """
    try:
        if not getattr(settings, "XP_COLLECTORS", []):
            return []
        from evennia.objects.models import ObjectDB

        projection = project_for_character(character_pk, window_end)
        pending = [
            (source_label(key), amount) for key, amount in projection.by_source.items() if amount
        ]
        screenreader = uses_screenreader(ObjectDB.objects.filter(pk=character_pk).first())

        if screenreader:
            if pending:
                parts = ", ".join(f"{label} {amount}" for label, amount in pending)
                summary = f"Projected XP, not yet awarded: {parts}. Total {projection.total}."
            else:
                summary = "Projected XP: nothing pending yet."
            return [summary, "XP is paid in the weekly batch. Use +xp for your balance."]

        if pending:
            parts = " | ".join(f"{label} +{amount}" for label, amount in pending)
            summary = (
                f"  |wProjected XP|n (not yet awarded): {parts} | Total |w{projection.total}|n"
            )
        else:
            summary = "  |wProjected XP|n: nothing pending yet."
        return [
            "-" * 50,
            summary,
            "  XP is paid in the weekly batch. Use |w+xp|n for your balance.",
        ]
    except Exception:
        logger.exception("XP projection: +activity lines failed for character #%s", character_pk)
        return []
