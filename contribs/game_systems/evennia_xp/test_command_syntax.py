# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Manual grants preserve comment text and reject old or ambiguous input."""

from decimal import Decimal

from django.test import override_settings
from evennia.utils.test_resources import EvenniaCommandTest

from .commands import CmdXp
from .models import CharacterXP, XPLog


@override_settings(XP_STAFF_LOCK="cmd:perm(Builder)")
class XpSyntaxTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.char1.permissions.add("Builder")

    def test_grant_preserves_dbrefs_and_the_entire_reason(self):
        reason = "For #12.3: A=B, C; keep # this CASE"
        self.call(CmdXp(), f"/GR #{self.char2.pk}=2.5 # {reason}", "Granted 2.5 XP")
        row = XPLog.objects.get()
        self.assertEqual(
            (row.character_id, row.amount, row.reason), (self.char2.pk, Decimal("2.5"), reason)
        )
        self.assertEqual(row.granted_by_id, self.char1.pk)
        self.assertEqual(
            CharacterXP.objects.get(character_id=self.char2.pk).current_balance, Decimal("2.5")
        )

    def test_old_forms_bad_amounts_and_switches_cannot_award(self):
        for args in (
            "/grant Char2=3:Old reason",
            "/grant/log Char2=3:Old reason",
            "/grant/typo Char2=3:Old reason",
            "/typo Char2=3 # Reason",
            "/grant Char2=3",
            "/grant Char2=3 # ",
            "/grant Char2=0 # Reason",
            "/grant Char2=-3 # Reason",
            "/grant Char2=NaN # Reason",
            "/grant Char2=Infinity # Reason",
        ):
            with self.subTest(args=args):
                self.call(CmdXp(), args)
                self.assertFalse(XPLog.objects.exists())
                self.assertFalse(CharacterXP.objects.exists())

    def test_new_syntax_still_requires_staff(self):
        self.call(
            CmdXp(), "/grant Char2=3 # Reason", "You need staff permission", caller=self.char2
        )
        self.assertFalse(XPLog.objects.exists())
