# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
First-login XP summary — a one-time breakdown after each weekly batch.

When a player puppets a character for the first time since a batch paid it,
they see what they earned that week, grouped by source::

    XP awarded for week 2026-W18: 3.50 XP total
      • Cutscene (+1.00)
      • RP Session (+2.50)
    Use +xp to view your balance and history.

With a configured Inbox, each paid week is a routine XP notice. Otherwise
the current eligible payout is shown on the first eligible puppet.

Two ways to wire it:

    # 1. The mixin — put it before DefaultCharacter in the MRO
    from evennia_xp.typeclasses import XPSummaryCharacterMixin

    class Character(XPSummaryCharacterMixin, ObjectParent, DefaultCharacter):
        ...

    # 2. Or call it from your own at_post_puppet
    from evennia_xp.summary import notify_xp_summary

    def at_post_puppet(self, **kwargs):
        super().at_post_puppet(**kwargs)
        notify_xp_summary(self)
"""

from decimal import Decimal

from django.db.models import Sum
from evennia.utils import logger

try:
    from evennia_accessibility import uses_screenreader
except ImportError:

    def uses_screenreader(_):
        """Fallback when evennia-accessibility is not installed."""
        return False


#: Attribute (default category) recording the last week summarised. Same key
#: the source project used, so a game adopting the contrib keeps its state.
SUMMARY_WEEK_ATTRIBUTE = "last_xp_summary_week"


def grouped_totals(character_id, weeks):
    """Load only displayable ledger fields in a single query for this character."""
    from .models import XPLog

    by_week = {}
    labels = dict(XPLog.SourceType.choices)
    rows = (
        XPLog.objects.filter(character_id=character_id, week__in=weeks)
        .order_by()
        .values("week", "source_type")
        .annotate(amount=Sum("amount"))
    )
    for row in rows:
        sources = by_week.setdefault(row["week"], {})
        label = labels.get(row["source_type"], "Other XP")
        sources[label] = sources.get(label, Decimal("0.00")) + row["amount"].quantize(
            Decimal("0.01")
        )
    return by_week


def summary_text(week, by_source, *, plain=False):
    total = sum(by_source.values(), Decimal("0.00"))
    if plain:
        lines = [f"XP awarded for week {week}: {total} XP total"]
        lines += [f"  {source}: +{amount}" for source, amount in sorted(by_source.items())]
        lines.append("Use +xp to view your balance and history.")
    else:
        lines = [f"|wXP awarded for week {week}:|n {total} XP total"]
        lines += [f"  |w•|n {source} (+{amount})" for source, amount in sorted(by_source.items())]
        lines.append("|xUse |w+xp|n|x to view your balance and history.|n")
    return "\n".join(lines)


def notify_xp_summary(character):
    """Prepare this character's payout. Return True for a confirmed standalone write."""
    from .notices import prepare_character

    try:
        return prepare_character(character)
    except Exception:
        logger.log_trace(f"evennia_xp: XP summary notification failed for #{character.pk}")
        return False
