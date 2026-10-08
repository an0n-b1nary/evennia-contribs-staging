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

The comparison is ``CharacterXP.last_payout_week`` (the most recent batch that
paid this character) against the character's ``last_xp_summary_week``
Attribute (the most recent week it was shown). They differ exactly once per
paying batch, so the summary never repeats and a quiet week shows nothing.

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


def notify_xp_summary(character):
    """Show *character* its XP summary if a batch has paid it since it last saw one.

    Never raises: a failure here must not break login, so any error is logged
    and the summary skipped (the week is then *not* marked seen, so the next
    login retries).

    Args:
        character: The puppeted character (anything with ``pk``, ``msg`` and
            ``attributes``).

    Returns:
        bool: True if a summary was shown.
    """
    try:
        return _notify(character)
    except Exception:
        logger.log_trace(f"evennia_xp: XP summary notification failed for #{character.pk}")
        return False


def _notify(character):
    from evennia_xp.models import CharacterXP, XPLog

    payout_week = (
        CharacterXP.objects.filter(character_id=character.pk)
        .values_list("last_payout_week", flat=True)
        .first()
    )
    if not payout_week or payout_week == character.attributes.get(SUMMARY_WEEK_ATTRIBUTE):
        return False

    logs = XPLog.objects.filter(character_id=character.pk, week=payout_week)
    by_source = {}
    total = Decimal("0.00")
    for row in logs:
        label = row.get_source_type_display()
        by_source[label] = by_source.get(label, Decimal("0.00")) + row.amount
        total += row.amount
    if not by_source:
        return False

    if uses_screenreader(character):
        lines = [f"XP awarded for week {payout_week}: {total} XP total"]
        lines += [f"  {source}: +{amount}" for source, amount in sorted(by_source.items())]
        lines.append("Use +xp to view your balance and history.")
    else:
        lines = [f"|wXP awarded for week {payout_week}:|n {total} XP total"]
        lines += [f"  |w•|n {source} (+{amount})" for source, amount in sorted(by_source.items())]
        lines.append("|xUse |w+xp|n|x to view your balance and history.|n")

    character.msg("\n".join(lines))
    character.attributes.add(SUMMARY_WEEK_ATTRIBUTE, payout_week)
    return True
