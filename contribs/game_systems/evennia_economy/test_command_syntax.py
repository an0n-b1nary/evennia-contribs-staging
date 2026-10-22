# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Currency adjustments accept comments without mixing them into amounts."""

from django.test import override_settings
from evennia.utils.test_resources import EvenniaCommandTest

from .commands import CmdEconomy, CmdShop
from .models import LedgerEntry, Purse
from .services import balance


@override_settings(RP_ECONOMY_REVEALED=True, RP_ECONOMY_FROZEN=False)
class EconomySyntaxTests(EvenniaCommandTest):
    def test_credit_and_debit_preserve_notes_and_staff_identity(self):
        reason = "Trade #12.3: A=B, C; keep # this CASE"
        self.call(CmdEconomy(), f"/CREDIT #{self.char2.pk}=10 # {reason}", "Purse updated")
        self.call(CmdEconomy(), "/deb Char2=2 # Fee", "Purse updated")
        self.assertEqual(balance(self.char2), 8)
        rows = list(LedgerEntry.objects.order_by("pk"))
        self.assertEqual(
            [(row.amount, row.note, row.by_id) for row in rows],
            [(10, reason, self.char1.pk), (2, "Fee", self.char1.pk)],
        )

    def test_old_forms_bad_amounts_and_switches_leave_no_purse_or_ledger(self):
        for args in (
            "/credit Char2=10,Old note",
            "/debit Char2=2,Old note",
            "/credit/audit Char2=10",
            "/credit/typo Char2=10",
            "/r Char2=10",
            "/typo Char2=10",
            "/credit Char2=2.5 # Note",
            "/credit Char2=0 # Note",
            "/credit Char2=-1 # Note",
        ):
            with self.subTest(args=args):
                self.call(CmdEconomy(), args)
                self.assertFalse(LedgerEntry.objects.exists())
                self.assertFalse(Purse.objects.exists())

    def test_notes_remain_optional_and_players_cannot_adjust(self):
        self.call(CmdEconomy(), "/credit Char2=3", "Purse updated")
        self.assertEqual(LedgerEntry.objects.get().note, "")
        self.call(CmdEconomy(), "/credit Char2=4 # No", "Only staff", caller=self.char2)
        self.assertEqual(balance(self.char2), 3)
        self.assertEqual(LedgerEntry.objects.count(), 1)

    def test_shop_refuses_unknown_switch_instead_of_closing(self):
        # With switch_options, MuxCommand would otherwise discard /typo.
        self.assertIn("one switch", self.call(CmdShop(), "/close/typo 123").lower())
