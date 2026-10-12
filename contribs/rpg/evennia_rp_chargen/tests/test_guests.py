# SPDX-License-Identifier: BSD-3-Clause
"""A disposable reset cannot retain ratings or purchases from the last trial."""

from unittest.mock import patch

from django.test import override_settings

from evennia_rp_chargen import abilities, services
from evennia_rp_chargen.models import AbilityDefinition, AbilityTransaction, CharacterAbility
from evennia_rp_chargen.stats import StatHandler

from .base import ChargenTest


@override_settings(RP_CHARGEN_GUEST_TRIALS=True)
class GuestTrialTests(ChargenTest):
    def setUp(self):
        super().setUp()
        self.char1.tags.add("character", category="guest")
        self.room1.tags.add("wing", category="guest")
        self.char1.location = self.room1
        self.ability = AbilityDefinition.objects.create(key="trial", name="Trial", xp_cost=1)

    def test_reset_discards_only_guest_ratings_purchases_and_audit(self):
        StatHandler(self.char1).set("brawn", self.ruleset.parse_rating("Mid"))
        StatHandler(self.char2).set("brawn", self.ruleset.parse_rating("High"))
        for character in (self.char1, self.char2):
            services.ensure_build(character)
            CharacterAbility.objects.create(character=character, ability=self.ability)
            AbilityTransaction.objects.create(character_id=character.pk, kind="acquire")
        services.reset_trial(self.char1)
        self.assertEqual(StatHandler(self.char1).raw(), {})
        self.assertFalse(CharacterAbility.objects.filter(character=self.char1).exists())
        self.assertFalse(AbilityTransaction.objects.filter(character_id=self.char1.pk).exists())
        self.assertIsNotNone(StatHandler(self.char2).get("brawn"))
        self.assertTrue(CharacterAbility.objects.filter(character=self.char2).exists())
        self.assertTrue(AbilityTransaction.objects.filter(character_id=self.char2.pk).exists())

    def test_guest_deletion_removes_purchase_audit(self):
        identity = self.char1.pk
        AbilityTransaction.objects.create(character_id=identity, kind="acquire")
        self.char1.delete()
        self.assertFalse(AbilityTransaction.objects.filter(character_id=identity).exists())

    def test_ordinary_character_deletion_preserves_purchase_audit(self):
        identity = self.char2.pk
        AbilityTransaction.objects.create(character_id=identity, kind="acquire")
        self.char2.delete()
        self.assertTrue(AbilityTransaction.objects.filter(character_id=identity).exists())

    def test_guest_never_spends_real_xp_when_trial_allowance_runs_out(self):
        build = services.ensure_build(self.char1)
        build.starting_allowance = 0
        build.save()
        with (
            patch("evennia_rp_chargen.abilities.get_ledger") as ledger,
            self.assertRaisesMessage(services.ChargenError, "starting allowance"),
        ):
            abilities.acquire(self.char1, "trial")
        ledger.assert_not_called()
        self.assertFalse(CharacterAbility.objects.filter(character=self.char1).exists())
        self.assertFalse(AbilityTransaction.objects.filter(character_id=self.char1.pk).exists())
