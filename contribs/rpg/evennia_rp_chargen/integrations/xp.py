# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Optional evennia-xp ledger; safe to configure when XP is not installed."""

from decimal import Decimal

from django.apps import apps

from evennia_rp_chargen.ledger import InsufficientXP, LedgerUnavailable


class EvenniaXPLedger:
    @property
    def available(self):
        return apps.is_installed("evennia_xp")

    def _require(self):
        if not self.available:
            raise LedgerUnavailable("XP spending isn't available in this game")

    def balance(self, character):
        self._require()
        from evennia_xp.models import CharacterXP

        return CharacterXP.objects.filter(character_id=character.pk).values_list(
            "current_balance", flat=True
        ).first() or Decimal(0)

    def spend(self, character, amount, *, ref_key, reason=""):
        self._require()
        from evennia_xp import spending

        try:
            spending.spend_xp(
                character.pk, amount, ref_key=ref_key, category="ability", reason=reason
            )
        except spending.InsufficientXP as exc:
            raise InsufficientXP(str(exc)) from exc

    def refund(self, character, *, ref_key):
        self._require()
        from evennia_xp.spending import refund_xp

        return refund_xp(character.pk, ref_key=ref_key)
