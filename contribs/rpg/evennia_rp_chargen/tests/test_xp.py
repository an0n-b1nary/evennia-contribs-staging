# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real ledger seams and rollback of the complete ability purchase."""

from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.test import override_settings
from evennia.utils.test_resources import EvenniaCommandTest

from evennia_rp_chargen import abilities
from evennia_rp_chargen.models import AbilityTransaction, CharacterAbility, CharacterBuild
from evennia_rp_chargen.services import ChargenError

from .test_abilities import CatalogTest

LEDGER = "evennia_rp_chargen.integrations.xp.EvenniaXPLedger"


@skipUnless(apps.is_installed("evennia_xp"), "optional XP partner absent")
@override_settings(RP_CHARGEN_XP_LEDGER=LEDGER)
class XPLedgerTests(CatalogTest, EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        from evennia_xp.awards import record_xp
        from evennia_xp.models import XPLog

        record_xp(self.char1.pk, 10, XPLog.SourceType.MANUAL_GRANT, 0)
        abilities.set_allowance(self.char1, 1)

    def test_commands_buy_and_upgrade_with_real_xp(self):
        from evennia_xp.models import XPSpend

        from evennia_rp_chargen.commands import CmdSpend, CmdUpgrade

        result = self.call(CmdSpend(), "/ability domain expertise: climbing")
        self.assertIn("1 starting allowance and 2 XP", result)
        self.assertIn("level 2", self.call(CmdUpgrade(), "domain expertise: climbing"))
        self.assertEqual(abilities.balance(self.char1), (0, 6))
        self.assertEqual(XPSpend.objects.count(), 2)

    def test_failed_copy_creation_rolls_back_both_funding_sources(self):
        from evennia_xp.models import XPSpend

        before = AbilityTransaction.objects.count()
        with (
            patch.object(
                CharacterAbility.objects, "create", side_effect=RuntimeError("copy failed")
            ),
            self.assertRaises(RuntimeError),
        ):
            abilities.acquire(self.char1, "domain expertise", "climbing")
        self.assertEqual(abilities.balance(self.char1), (1, 10))
        self.assertFalse(XPSpend.objects.exists())
        self.assertEqual(AbilityTransaction.objects.count(), before)
        self.assertEqual(CharacterBuild.objects.get(character=self.char1).allowance_spent, 0)

    def test_stale_upgrade_rolls_back_its_xp_debit(self):
        from evennia_xp.models import XPSpend

        abilities.acquire(self.char1, "domain expertise", "climbing")
        stale = abilities.find_owned(self.char1, "domain expertise", "climbing")
        abilities.upgrade(self.char1, "domain expertise", "climbing")
        before = abilities.balance(self.char1)
        with (
            patch("evennia_rp_chargen.abilities.find_owned", return_value=stale),
            self.assertRaisesMessage(ChargenError, "changed while"),
        ):
            abilities.upgrade(self.char1, "domain expertise", "climbing")
        self.assertEqual(abilities.balance(self.char1), before)
        self.assertEqual(XPSpend.objects.count(), 2)
