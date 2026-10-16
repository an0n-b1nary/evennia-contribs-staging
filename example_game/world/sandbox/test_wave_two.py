# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Actual ownership, economy, rendering, logging and combat partner seams."""

from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.core.management import call_command
from django.test import override_settings
from evennia.objects.objects import DefaultCharacter
from evennia.utils.test_resources import EvenniaTest
from evennia_rp_crafting import fixtures
from evennia_rp_crafting.errors import CraftingError
from evennia_rp_crafting.models import FixtureInstallation
from evennia_rp_crafting.test_wave_two import WaveTwoFixture
from evennia_rp_crafting.wave_two import activate
from typeclasses.characters import Character
from typeclasses.rooms import Room

from evennia_links.rooms import can, owner_of


@skipUnless(apps.is_installed("evennia_building"), "building absent")
class WaveTwoSeams(WaveTwoFixture, EvenniaTest):
    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        from evennia_building import services
        from evennia_building.models import Property

        override = override_settings(
            BUILDING_REVEALED=True,
            BUILDING_REUSE_ACKNOWLEDGEMENT="This submitted content may be reused.",
            LINKS_ROOM_PERMISSION="evennia_building.access.room_permission",
            LINKS_ROOM_OWNER="evennia_building.access.owner_of",
            LINKS_ROOM_LIVE="evennia_building.access.room_is_live",
            LINKS_ROOM_LOCK="evennia_building.access.lock_room_state",
            LINKS_OWNED_ROOMS="evennia_building.access.owned_room_ids",
        )
        override.enable()
        self.addCleanup(override.disable)
        self.char2.permissions.add("Builder")
        self.account2.permissions.add("Builder")
        self.room1.db.room_type = "ic"
        self.room1.db.allow_teleport = "public"
        project = services.new_project(self.char1, "Lantern home")
        services.attach(self.char1, project, self.room1, "lantern home")
        project.refresh_from_db()
        submission = services.submit(
            self.char1,
            project,
            expected_version=project.version,
            acknowledgement="This submitted content may be reused.",
        )
        services.review(
            self.char2,
            submission,
            expected_revision=submission.revision,
            outcome="approved",
            reason="A suitable small home.",
        )
        self.property = Property.objects.get(promotion=submission)
        self.home = self.property.rooms.get().room
        self.char1.move_to(self.home, quiet=True)
        self.char2.move_to(self.home, quiet=True)

    def test_real_property_transfer_archive_restore_and_credit(self):
        from evennia_building import lifecycle, services

        item = self.fixture()
        fixtures.install(self.char1, item, self.home)
        self.assertEqual(owner_of(self.home), self.char1)
        self.assertIn("Warm light", self.home.return_appearance(self.char1))
        self.assertIn("Warm light", self.home.get_display_desc(self.char1))
        self.assertEqual(item.craft_record.furnishing_weeks, Decimal("0.2"))
        if apps.is_installed("evennia_economy"):
            from evennia_economy.batch import money_cap

            before = money_cap(self.char2)
        services.transfer(
            self.char2,
            self.property,
            self.char2,
            expected_owner=self.char1.pk,
            reason="Pass on the furnished home.",
        )
        self.assertEqual(owner_of(self.home), self.char2)
        if apps.is_installed("evennia_economy"):
            self.assertGreater(money_cap(self.char2), before)
        with self.assertRaises(CraftingError):
            fixtures.uninstall(self.char1, item)
        lifecycle.archive(self.char2, self.property, reason="Keep it for later.")
        self.assertEqual(fixtures.layers(self.home), [])
        self.assertEqual(fixtures.furnishing_caps(None, self.char2)["furnishing"]["money"], 0)
        self.assertTrue(FixtureInstallation.objects.filter(active=True).exists())
        self.assertEqual(item.location, self.home)
        lifecycle.restore(self.char2, self.property, reason="Return to the house.")
        self.assertIn("Warm light", self.home.get_display_desc(self.char2))
        self.char2.move_to(self.home, quiet=True)
        fixtures.uninstall(self.char2, item)
        self.assertEqual(item.location, self.char2)

    def test_actual_resident_install_never_grants_removal(self):
        from evennia_building import services

        self.char2.permissions.remove("Builder")
        self.account2.permissions.remove("Builder")
        services.set_resident(self.char1, self.property, self.char2, can_install=True)
        item = self.fixture()
        item.move_to(self.char2, quiet=True)
        fixtures.install(self.char2, item, self.home)
        self.assertTrue(can(self.char2, self.home, "install"))
        with self.assertRaises(CraftingError):
            fixtures.uninstall(self.char2, item)
        fixtures.uninstall(self.char1, item)
        self.assertEqual(item.location, self.char1)

    @skipUnless(apps.is_installed("evennia_scenes"), "scenes absent")
    def test_emission_is_logged_ignored_and_never_counted_as_a_pose(self):
        from evennia_scenes.models import LogEntry, Scene, SceneParticipant

        scene = Scene.objects.create(title="An evening tune", room=self.home, creator=self.char1)
        item = self.instrument()
        self.account2.db.ignore_list = [self.account.pk]
        received = []
        last_pose = self.char1.last_pose_time
        if apps.is_installed("evennia_rptracker"):
            from evennia_rptracker.models import RPSession

            sessions_before = RPSession.objects.count()
        with (
            patch.object(
                DefaultCharacter,
                "msg",
                lambda target, text=None, **kwargs: received.append((target.pk, text)),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            activate(self.char1, item)
        self.assertFalse(any(target == self.char2.pk for target, _ in received))
        entry = LogEntry.objects.get(scene=scene)
        self.assertEqual(entry.author_id, self.char1.pk)
        self.assertEqual(entry.log_type, "emit")
        self.assertFalse(SceneParticipant.objects.filter(scene=scene).exists())
        scene.refresh_from_db()
        self.assertEqual(scene.status, Scene.Status.OPEN)
        self.assertEqual(self.char1.last_pose_time, last_pose)
        if apps.is_installed("evennia_rptracker"):
            self.assertEqual(RPSession.objects.count(), sessions_before)

    @skipUnless(
        apps.is_installed("evennia_rp_combat") and apps.is_installed("evennia_accessibility"),
        "combat/accessibility absent",
    )
    def test_ambient_pauses_in_real_room_fight(self):
        from evennia_rp_combat.models import Fight

        fixtures.install(self.char1, self.fixture(ambient="A soft chime sounds."), self.home)
        fight = Fight.objects.create(room=self.home, status=Fight.OPEN, state={})
        self.assertEqual(fixtures.ambient_tick(), 0)
        fight.status = Fight.ENDED
        fight.save(update_fields=["status"])
        self.assertEqual(fixtures.ambient_tick(), 1)


class WaveTwoSeedSeams(EvenniaTest):
    character_typeclass = Character
    room_typeclass = Room

    def test_seeded_fixture_is_visible_and_reseed_preserves_history(self):
        from evennia.objects.models import ObjectDB
        from evennia_rp_crafting.models import CraftRecord

        from world.sandbox import crafting

        call_command("seed_sandbox", verbosity=0)
        item = ObjectDB.objects.get(db_key=crafting.FIXTURE_NAME)
        record = item.craft_record
        self.assertIn(crafting.FIXTURE_LINE, item.location.return_appearance(self.char1))
        self.assertEqual(fixtures.furnishing_caps(None, self.char1)["furnishing"]["money"], 0)
        call_command("seed_sandbox", verbosity=0)
        self.assertEqual(ObjectDB.objects.filter(db_key=crafting.FIXTURE_NAME).count(), 1)
        self.assertTrue(CraftRecord.objects.filter(pk=record.pk).exists())
        self.assertFalse(FixtureInstallation.objects.filter(craft=record, active=True).exists())
