# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Typeclass mixin for evennia_xp.

    from evennia_xp.typeclasses import XPSummaryCharacterMixin

    class Character(XPSummaryCharacterMixin, ObjectParent, DefaultCharacter):
        ...

Cooperative: ``at_post_puppet`` calls ``super()`` first, so it composes with
other contribs' mixins in any order. See ``evennia_xp.summary``.
"""

from evennia_xp.summary import notify_xp_summary


class XPSummaryCharacterMixin:
    """Show the first-login XP summary after each weekly batch."""

    def at_post_puppet(self, **kwargs):
        super().at_post_puppet(**kwargs)
        notify_xp_summary(self)
