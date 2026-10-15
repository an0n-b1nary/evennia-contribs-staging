# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Committed property transitions serialize with fixture authority checks."""

from unittest import skipUnless

from django.apps import apps
from django.db import connection
from django.test import TransactionTestCase, override_settings
from evennia.utils.test_resources import EvenniaTestMixin

from evennia_links.test_transactions import committed_race

from . import fixtures, services
from .errors import CraftingError
from .models import ActivationUse, FixtureInstallation
from .test_wave_three import WaveThreeFixture
from .test_wave_two import WaveTwoFixture
from .wave_two import activate


@skipUnless(apps.is_installed("evennia_economy"), "Economy absent")
class ModifierAcceptanceRaces(WaveThreeFixture, EvenniaTestMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        if connection.vendor == "sqlite" and "mode=memory" in str(connection.settings_dict["NAME"]):
            self.skipTest("Race gate requires a file-backed test database")

    def test_cancellation_waits_for_committed_acceptance(self):
        from . import modifiers
        from .models import ModificationLayer

        offer = self.offer()
        with self.assertRaises(ValueError):
            committed_race(
                lambda: modifiers.accept(self.char2, offer.pk),
                lambda: modifiers.cancel(self.char2, offer.pk),
            )
        self.assertEqual(ModificationLayer.objects.filter(service=offer).count(), 1)

    def test_acceptance_waits_for_committed_cancellation(self):
        from . import modifiers
        from .models import ModificationLayer

        offer = self.offer()
        with self.assertRaises(ValueError):
            committed_race(
                lambda: modifiers.cancel(self.char2, offer.pk),
                lambda: modifiers.accept(self.char2, offer.pk),
            )
        self.assertFalse(ModificationLayer.objects.filter(service=offer).exists())

    def test_duplicate_acceptance_commits_one_payment_and_layer(self):
        from evennia_economy.services import balance

        from . import modifiers
        from .models import ModificationLayer

        if connection.vendor == "sqlite" and "mode=memory" in str(connection.settings_dict["NAME"]):
            self.skipTest("Race gate requires a file-backed test database")
        offer = self.offer()
        before = balance(self.char1)
        with self.assertRaises(ValueError):
            committed_race(
                lambda: modifiers.accept(self.char2, offer.pk),
                lambda: modifiers.accept(self.char2, offer.pk),
            )
        self.assertEqual(ModificationLayer.objects.filter(service=offer).count(), 1)
        self.assertEqual(balance(self.char1), before + 30)


@skipUnless(apps.is_installed("evennia_building"), "building absent")
class FixtureAuthorityRaces(WaveTwoFixture, EvenniaTestMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        if connection.vendor == "sqlite" and "mode=memory" in str(connection.settings_dict["NAME"]):
            self.skipTest("Race gate requires a file-backed test database")
        from evennia_building import services
        from evennia_building.models import Property

        override = override_settings(
            BUILDING_REVEALED=True,
            LINKS_ROOM_PERMISSION="evennia_building.access.room_permission",
            LINKS_ROOM_OWNER="evennia_building.access.owner_of",
            LINKS_ROOM_LIVE="evennia_building.access.room_is_live",
            LINKS_ROOM_LOCK="evennia_building.access.lock_room_state",
            BUILDING_REUSE_ACKNOWLEDGEMENT="Race acknowledgement",
        )
        override.enable()
        self.addCleanup(override.disable)
        self.char2.permissions.add("Builder")
        self.account2.permissions.add("Builder")
        self.room1.db.room_type = "ic"
        self.room1.db.allow_teleport = "public"
        project = services.new_project(self.char1, "Fixture race home")
        services.attach(self.char1, project, self.room1, "race home")
        project.refresh_from_db()
        submission = services.submit(
            self.char1,
            project,
            expected_version=project.version,
            acknowledgement="Race acknowledgement",
        )
        services.review(
            self.char2,
            submission,
            expected_revision=submission.revision,
            outcome="approved",
            reason="Race fixture approved.",
        )
        self.property = Property.objects.get(promotion=submission)
        self.home = self.property.rooms.get().room
        self.char1.move_to(self.home, quiet=True)
        self.char2.move_to(self.home, quiet=True)
        self.item = self.fixture()
        fixtures.install(self.char1, self.item, self.home)

    def transfer(self):
        from evennia_building import services

        return services.transfer(
            self.char2,
            self.property,
            self.char2,
            expected_owner=self.char1.pk,
            reason="Transfer furnished home.",
        )

    def test_transfer_commits_first_denies_former_owner_uninstall(self):
        with self.assertRaisesMessage(CraftingError, "property owner"):
            committed_race(self.transfer, lambda: fixtures.uninstall(self.char1, self.item))
        self.assertTrue(FixtureInstallation.objects.filter(active=True).exists())
        self.assertEqual(self.item.location, self.home)

    def test_uninstall_commits_first_transfers_an_unfurnished_property(self):
        committed_race(lambda: fixtures.uninstall(self.char1, self.item), self.transfer)
        self.assertFalse(FixtureInstallation.objects.filter(active=True).exists())
        self.assertEqual(self.item.location, self.char1)

    def test_simultaneous_visitors_cannot_bypass_activation_cooldown(self):
        item = services.craft(
            self.char1,
            "decoration",
            "installable",
            "a race music box",
            "A small box.",
            {"room_line": "A music box rests here."},
            {"wood": 2},
            verbs=[
                {
                    "key": "activatable",
                    "niche": "music",
                    "configuration": {"modes": {"play": ["A melody sounds."]}},
                }
            ],
        )
        fixtures.install(self.char1, item, self.home)
        with self.assertRaisesMessage(CraftingError, "item was just used"):
            committed_race(lambda: activate(self.char1, item), lambda: activate(self.char2, item))
        self.assertEqual(ActivationUse.objects.count(), 1)
