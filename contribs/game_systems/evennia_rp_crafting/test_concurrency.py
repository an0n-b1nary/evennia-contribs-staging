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
from .tests import CraftingFixture
from .wave_two import activate


class JournalRaces(CraftingFixture, EvenniaTestMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        if connection.vendor == "sqlite" and "mode=memory" in str(connection.settings_dict["NAME"]):
            self.skipTest("Race gate requires a file-backed test database")
        self.unlock()
        self.journal = self.book(configuration={"journal": 2}, selected={"wood": 2})

    def test_last_page_capacity_serializes_committed_writers(self):
        from .models import JournalRevision
        from .readables import write

        write(self.char1, self.journal, "One", "First.")
        with self.assertRaisesMessage(CraftingError, "unused pages"):
            committed_race(
                lambda: write(self.char1, self.journal, "Two", "Winner."),
                lambda: write(self.char1, self.journal, "Three", "Over capacity."),
            )
        self.assertEqual(JournalRevision.objects.filter(craft=self.journal.craft_record).count(), 2)

    def test_committed_revision_invalidates_competing_copy_before_payment(self):
        from .models import ReadableEdition
        from .readables import copy_book, snapshot, write

        write(self.char1, self.journal, "One", "First.")
        expected = snapshot(self.char1, self.journal)[3]
        before = self.held()
        with self.assertRaisesMessage(CraftingError, "source has changed"):
            committed_race(
                lambda: write(self.char1, self.journal, "One", "Changed.", page=1),
                lambda: copy_book(
                    self.char1,
                    self.journal,
                    "writing-0",
                    "Edition",
                    "A copy.",
                    {"wood": 1},
                    expected=expected,
                ),
            )
        self.assertEqual(self.held(), before)
        self.assertFalse(ReadableEdition.objects.exists())


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


class LetterRaces(CraftingFixture, EvenniaTestMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        if connection.vendor == "sqlite" and "mode=memory" in str(connection.settings_dict["NAME"]):
            self.skipTest("Race gate requires a file-backed test database")
        self.unlock()
        from .models import CraftRecord

        self.signet = self.book()
        CraftRecord.objects.filter(pk=self.signet.craft_record.pk).update(
            behaviour="wearable",
            verbs=[],
            prose={"facets": {"signet": {"design": "A Rose", "niche": "jewellery"}}},
        )
        self.letter = self.book(configuration={"journal": 2}, selected={"wood": 2})
        from .readables import write

        write(self.char1, self.letter, "One", "Original text.")

    def test_committed_sealing_freezes_a_competing_journal_write(self):
        from .letters import seal
        from .models import JournalRevision
        from .readables import write

        with self.assertRaisesMessage(CraftingError, "permanently freezes"):
            committed_race(
                lambda: seal(self.char1, self.letter, self.signet),
                lambda: write(self.char1, self.letter, "One", "Changed.", page=1),
            )
        self.assertEqual(JournalRevision.objects.filter(craft=self.letter.craft_record).count(), 1)
        self.assertIn("Original text.", self.letter.read(self.char1))

    def test_committed_writing_is_included_in_the_competing_seal(self):
        from .letters import seal
        from .readables import write

        committed_race(
            lambda: write(self.char1, self.letter, "One", "Committed text.", page=1),
            lambda: seal(self.char1, self.letter, self.signet),
        )
        self.assertIn("Committed text.", self.letter.read(self.char1))

    def test_sealing_blocks_a_competing_copy_before_payment(self):
        from .letters import seal
        from .models import ReadableEdition
        from .readables import copy_book, snapshot

        expected = snapshot(self.char1, self.letter)[3]
        before = self.held()
        with self.assertRaisesMessage(CraftingError, "intact seal"):
            committed_race(
                lambda: seal(self.char1, self.letter, self.signet),
                lambda: copy_book(
                    self.char1,
                    self.letter,
                    "writing-0",
                    "Edition",
                    "A copy.",
                    {"wood": 1},
                    expected=expected,
                ),
            )
        self.assertFalse(ReadableEdition.objects.exists())
        self.assertEqual(self.held(), before)

    def test_two_readers_break_the_same_seal_only_once(self):
        from .letters import seal
        from .models import LetterState

        seal(self.char1, self.letter, self.signet)
        second = committed_race(
            lambda: self.letter.read(self.char1),
            lambda: self.letter.read(self.char2),
        )
        self.assertIn("Original text.", second)
        self.assertNotIn("You break the seal", second)
        state = LetterState.objects.get(craft=self.letter.craft_record)
        self.assertFalse(state.intact)
        self.assertEqual(state.opened_at, state.first_opened_at)


@skipUnless(apps.is_installed("evennia_rp_equipment"), "Equipment absent")
class WearableStateRaces(CraftingFixture, EvenniaTestMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        if connection.vendor == "sqlite" and "mode=memory" in str(connection.settings_dict["NAME"]):
            self.skipTest("Race gate requires a file-backed test database")
        from .test_states import FACET

        self.unlock("weaving")
        self.cloak = services.craft(
            self.char1,
            "weaving",
            "wearable",
            "racing cloak",
            "A cloak.",
            {"worn_line": "a cloak"},
            {"wood": 3},
            facets={"states": FACET},
        )

    def test_concurrent_selections_commit_one_valid_key_without_rewriting_prose(self):
        from . import states

        original = self.cloak.craft_record.prose
        committed_race(
            lambda: states.select(self.char1, self.cloak, "up"),
            lambda: states.select(self.char1, self.cloak, "down"),
        )
        self.cloak.attributes.reset_cache()
        self.assertEqual(states.current(self.cloak, states.configuration(self.cloak)), "down")
        self.assertEqual(self.cloak.craft_record.prose, original)

    def test_committed_transfer_refuses_old_holders_competing_selection(self):
        from evennia.objects.models import ObjectDB

        from . import states

        with self.assertRaisesMessage(CraftingError, "carrying"):
            committed_race(
                lambda: ObjectDB.objects.filter(pk=self.cloak.pk).update(
                    db_location_id=self.char2.pk
                ),
                lambda: states.select(self.char1, self.cloak, "up"),
            )
        self.cloak.attributes.reset_cache()
        self.assertEqual(states.current(self.cloak, states.configuration(self.cloak)), "down")
