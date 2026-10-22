# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Ability addresses, independent staff operations and raw switch refusals."""

from django.test import override_settings

from evennia_rp_chargen import abilities
from evennia_rp_chargen.catalog import seed_catalog
from evennia_rp_chargen.commands import CmdAbilities, CmdChargen, CmdSpend, CmdUpgrade
from evennia_rp_chargen.models import AbilityTransaction, CharacterAbility

from .base import ChargenCommandTest
from .catalog_fixture import CATALOG_SETTINGS


@override_settings(**CATALOG_SETTINGS)
class CommandSyntaxTests(ChargenCommandTest):
    def expect(self, command, args, text=None, **kwargs):
        output = self.call(command, args, **kwargs)
        if text is not None:
            self.assertIn(text, output)
        return output

    def setUp(self):
        super().setUp()
        seed_catalog()

    def test_player_addresses_and_unique_switch_prefixes(self):
        self.expect(CmdSpend(), "/AbI domain expertise/riddles", "You learn", caller=self.char2)
        copy = CharacterAbility.objects.get(character_id=self.char2.pk)
        self.assertEqual((copy.tag.key, copy.level), ("riddles", 1))
        self.expect(CmdUpgrade(), "domain expertise/riddles", "now level 2", caller=self.char2)
        self.expect(CmdAbilities(), "/UnE domain expertise/riddles", "no longer", caller=self.char2)
        copy.refresh_from_db()
        self.assertFalse(copy.equipped)

    def test_staff_grant_level_and_standalone_refund(self):
        command = CmdChargen()
        self.expect(command, f"/GrA #{self.char2.pk}=domain expertise/riddles", "now has")
        self.expect(command, f"/LeV #{self.char2.pk}=3", "at level 3")
        copy = CharacterAbility.objects.get(character_id=self.char2.pk)
        self.assertEqual((copy.tag.key, copy.level), ("riddles", 3))
        abilities.acquire(self.char2, "domain expertise", "climbing")
        self.expect(command, "/refund Char2=domain expertise/climbing", "Refunded 3")
        self.assertFalse(
            CharacterAbility.objects.filter(
                character_id=self.char2.pk, tag__key="climbing"
            ).exists()
        )
        self.expect(command, "/revoke Char2=domain expertise/riddles", "Revoked")
        self.assertFalse(CharacterAbility.objects.filter(character_id=self.char2.pk).exists())

    def test_level_context_cannot_cross_character_or_staff_or_recreated_copy(self):
        command = CmdChargen()
        self.expect(command, "/grant Char2=domain expertise/riddles")
        self.expect(command, "/level Char1=3")
        self.char2.permissions.add("Developer")
        self.expect(command, "/level Char2=3", caller=self.char2)
        copy = CharacterAbility.objects.get(character_id=self.char2.pk)
        self.assertEqual(copy.level, 1)
        abilities.revoke(self.char2, "domain expertise", "riddles")
        abilities.grant(self.char2, "domain expertise", "riddles")
        self.expect(command, "/level Char2=3")
        self.assertEqual(CharacterAbility.objects.get(character_id=self.char2.pk).level, 1)

    def test_invalid_and_old_forms_have_no_financial_or_ability_effects(self):
        for command, args in (
            (CmdSpend(), "/ability domain expertise: riddles"),
            (CmdSpend(), "/ability domain expertise=riddles"),
            (CmdSpend(), "/ability/bogus lucky"),
            (CmdSpend(), "/bogus/ability lucky"),
            (CmdAbilities(), "/flaw/bogus domain ineptitude/climbing"),
            (CmdChargen(), "/grant Char2/lucky=2"),
            (CmdChargen(), "/grant Char2/domain expertise: riddles=2"),
            (CmdChargen(), "/grant/bogus Char2=lucky"),
            (CmdChargen(), "/r Char2=lucky"),
        ):
            with self.subTest(args=args):
                self.expect(command, args)
                self.assertFalse(CharacterAbility.objects.exists())
                self.assertFalse(AbilityTransaction.objects.exists())
        abilities.acquire(self.char2, "domain expertise", "riddles")
        count = AbilityTransaction.objects.count()
        for args in (
            "/revoke/refund Char2/domain expertise: riddles",
            "/refund/bogus Char2=domain expertise/riddles",
        ):
            self.expect(CmdChargen(), args)
            self.assertEqual(AbilityTransaction.objects.count(), count)
            self.assertTrue(CharacterAbility.objects.filter(character_id=self.char2.pk).exists())
