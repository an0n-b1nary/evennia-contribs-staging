# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real optional partners in a freshly installed host; no import stubs."""

from importlib.util import find_spec
from unittest.mock import patch

from django.apps import apps
from django.conf import settings
from django.test import override_settings
from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaTest

from evennia_economy import assets
from evennia_economy.exchange import accept_offer, create_offer
from evennia_economy.models import ReviewFlag
from evennia_economy.services import EconomyError, balance, credit


@override_settings(DEFAULT_HOME="#1")
class EconomyPartnerTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)

    def test_absence_is_physical(self):
        for name in getattr(settings, "ECONOMY_ABSENT_PARTNERS", []):
            self.assertFalse(apps.is_installed(name))
            self.assertIsNone(find_spec(name))

    def test_resource_provider_real_atomic_swap_or_absence(self):
        spec = [{"kind": "resource", "key": "grain", "quantity": 3}]
        if not apps.is_installed("evennia_rp_resources"):
            self.assertNotIn("resource", assets.providers())
            with self.assertRaises(EconomyError):
                create_offer(self.char1, self.char2, spec)
            return
        from evennia_rp_resources.models import ResourceDefinition, ResourceGrant
        from evennia_rp_resources.services import grant, total_held

        ResourceDefinition.objects.create(key="grain", name="Grain", category="provisions")
        grant(self.char1, "grain", 3)
        credit(self.char2, 10)
        offer = create_offer(
            self.char1, self.char2, spec, [{"kind": "money", "key": "", "quantity": 5}]
        )
        with override_settings(RP_ECONOMY_FEE_TRADE=1), self.assertRaises(EconomyError):
            accept_offer(self.char2, offer.pk)
        self.assertEqual(total_held(self.char1), 3)
        self.assertEqual(balance(self.char2), 10)
        with (
            patch("evennia_rp_resources.economy.grant", side_effect=RuntimeError("Credit failed")),
            self.assertRaises(RuntimeError),
        ):
            accept_offer(self.char2, offer.pk)
        self.assertEqual(total_held(self.char1), 3)
        self.assertEqual(total_held(self.char2), 0)
        self.assertEqual(balance(self.char2), 10)
        accept_offer(self.char2, offer.pk)
        self.assertEqual(total_held(self.char1), 0)
        self.assertEqual(total_held(self.char2), 3)
        self.assertEqual(balance(self.char1), 5)
        self.assertEqual(
            ResourceGrant.objects.filter(source="exchange", exchange_id=offer.pk).count(), 2
        )
        self.account.characters.add(self.char2)
        with self.assertRaisesRegex(EconomyError, "same account"):
            create_offer(self.char2, self.char1, spec)

    def test_hidden_resources_stay_out_of_player_trades(self):
        if not apps.is_installed("evennia_rp_resources"):
            return
        from evennia_rp_resources.models import ResourceDefinition
        from evennia_rp_resources.services import grant

        ResourceDefinition.objects.get_or_create(
            key="grain", defaults={"name": "Grain", "category": "provisions"}
        )
        grant(self.char2, "grain", 3)
        spec = [{"kind": "resource", "key": "grain", "quantity": 1}]
        with override_settings(RP_RESOURCES_REVEALED=False):
            self.assertNotIn("resource", assets.providers(self.char2))
            self.assertIn("resource", assets.providers(self.char1))  # staff still see it
            with self.assertRaises(EconomyError):
                assets.parse_spec(self.char2, "1 grain")
            with self.assertRaises(EconomyError):
                create_offer(self.char2, self.char1, spec)

    def test_resource_to_money_roundtrip_is_reviewed(self):
        if not apps.is_installed("evennia_rp_resources"):
            return
        from evennia_rp_resources.models import ResourceDefinition
        from evennia_rp_resources.services import grant

        alt = create_object(
            "evennia.objects.objects.DefaultCharacter", key="Test alt", location=self.room1
        )
        self.account.characters.add(alt)
        ResourceDefinition.objects.create(key="grain", name="Grain", category="provisions")
        grant(self.char1, "grain", 1)
        credit(self.char2, 10)
        with override_settings(RP_ECONOMY_FLAG_REVIEW_HOOK=None):
            offer = create_offer(
                self.char1, self.char2, [{"kind": "resource", "key": "grain", "quantity": 1}]
            )
            accept_offer(self.char2, offer.pk)
            offer = create_offer(self.char2, alt, [{"kind": "money", "key": "", "quantity": 1}])
            accept_offer(alt, offer.pk)
        self.assertEqual(ReviewFlag.objects.count(), 1)

    def test_equipment_pre_give_hook_and_transfer_seal(self):
        if not apps.is_installed("evennia_rp_equipment"):
            return
        from evennia_rp_equipment.typeclasses import Equipment

        gear = create_object(Equipment, key="Test cloak", location=self.char1)
        gear.maker_id = self.char1.pk
        spec = [{"kind": "item", "key": str(gear.pk), "quantity": 1}]
        offer = create_offer(self.char1, self.char2, spec)
        gear.tags.add("worn", category="rp_equipment")
        with self.assertRaises(EconomyError):
            accept_offer(self.char2, offer.pk)
        gear.tags.remove("worn", category="rp_equipment")
        with self.captureOnCommitCallbacks(execute=True):
            accept_offer(self.char2, offer.pk)
        self.assertEqual(gear.location, self.char2)
        self.assertTrue(gear.sealed)

    def test_roundtrip_real_review_job_or_hookless_queue(self):
        hook = (
            "evennia_jobs.integrations.staff_review.file_review_job"
            if apps.is_installed("evennia_jobs")
            else None
        )
        alt = create_object(
            "evennia.objects.objects.DefaultCharacter", key="Test alt", location=self.room1
        )
        self.account.characters.add(alt)
        credit(self.char1, 10)
        with (
            override_settings(RP_ECONOMY_FLAG_REVIEW_HOOK=hook),
            self.captureOnCommitCallbacks(execute=True),
        ):
            offer = create_offer(
                self.char1, self.char2, [{"kind": "money", "key": "", "quantity": 2}]
            )
            accept_offer(self.char2, offer.pk)
            self.obj1.location = self.char2
            offer = create_offer(
                self.char2, alt, [{"kind": "item", "key": str(self.obj1.pk), "quantity": 1}]
            )
            accept_offer(alt, offer.pk)
        self.assertEqual(ReviewFlag.objects.count(), 1)
        if hook:
            from evennia_jobs.models import Job

            self.assertTrue(Job.objects.filter(title="Economy: possible asset round trip").exists())
