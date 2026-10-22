# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Wave-two policies under ordinary actors, real partners and persisted history."""

from datetime import timedelta
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.db import transaction
from django.test import override_settings
from django.utils import timezone
from evennia.objects.models import ObjectDB
from evennia.objects.objects import DefaultRoom
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from evennia_links.rooms import can
from evennia_links.runtime import cap_raise

from . import conf, fixtures, services
from .commands import CmdCraft, CmdUse, CmdWorkshop
from .errors import CraftingError
from .models import (
    ActivationUse,
    CraftRecord,
    EventRoomLimit,
    FixtureInstallation,
    NicheDefinition,
    RoomLayer,
)
from .room_commands import CmdFixture, CmdListen, CmdSense
from .tests import CraftingFixture
from .typeclasses import CraftingRoomMixin
from .wave_two import activate


class FixtureRoom(CraftingRoomMixin, DefaultRoom):
    pass


class WaveTwoFixture(CraftingFixture):
    def setUp(self):
        super().setUp()
        self.owner = self.char1
        self.live = True
        override = override_settings(
            RP_CRAFTING_COMBINATIONS=conf.DEFAULT_COMBINATIONS,
            RP_CRAFTING_WAVE_TWO_REVEALED=True,
            LINKS_ROOM_PERMISSION=lambda actor, room, action: actor == self.owner,
            LINKS_ROOM_OWNER=lambda room, include_inactive=False: (
                self.owner if self.live or include_inactive else None
            ),
            LINKS_ROOM_LIVE=lambda room: self.live,
            LINKS_ROOM_LOCK=None,
            LINKS_OWNED_ROOMS=None,
            SOCIAL_ROOM_MOOD_PERMISSION=None,
            RP_CRAFTING_FIXTURE_ROOM_LIMIT=5,
            RP_CRAFTING_TEMPORARY_LAYER_LIMIT=3,
            RP_CRAFTING_TEMPORARY_LAYER_SECONDS=3600,
            RP_CRAFTING_EVENT_ROOM_COOLDOWN=30,
            RP_CRAFTING_ACTIVATION_ITEM_COOLDOWN=30,
            RP_CRAFTING_AMBIENT_INTERVAL=300,
            RP_CRAFTING_BASIC_FIXTURE_WEEKS="0.2",
            RP_CRAFTING_FURNISHING_REFERENCE=1,
            RP_CRAFTING_FURNISHING_CATEGORY_VALUES={"materials": 1, "essences": 2, "provisions": 1},
            RP_CRAFTING_FURNISHING_COIN_VALUE="0.01",
        )
        override.enable()
        self.addCleanup(override.disable)
        for key, kind in (("decoration", "installable"), ("music", "activatable")):
            NicheDefinition.objects.create(
                key=key,
                name=key.title(),
                behaviours=[kind],
                input_categories=["materials", "essences"],
                unlock_money=0,
                unlock_resources={"materials": 3},
            )
            self.unlock(key)

    def fixture(self, **config):
        return services.craft(
            self.char1,
            "decoration",
            "installable",
            "a brass lantern",
            "A hand-worked lantern.",
            {"room_line": "Warm light falls on the walls.", **config},
            {"wood": 1, **({"spark": 1} if config.get("ambient") else {})},
        )

    def instrument(self, kind="activatable", verbs=None, selected=None, configuration=None):
        return services.craft(
            self.char1,
            "music",
            kind,
            "a small lute",
            "A stringed instrument.",
            configuration or {"modes": {"play": ["A bright melody rings out."]}},
            selected or {"wood": 1},
            verbs=verbs,
        )

    def expire_event(self):
        EventRoomLimit.objects.update(last_used=timezone.now() - timedelta(seconds=31))
        ActivationUse.objects.update(created_at=timezone.now() - timedelta(seconds=31))


class FixtureTests(WaveTwoFixture, EvenniaTest):
    def test_installation_preserves_base_prose_and_blocks_get_give_delete(self):
        item = self.fixture(smell="Beeswax.", sound="A quiet metallic hum.")
        before = self.room1.db.desc
        row = fixtures.install(self.char1, item, self.room1)
        self.assertEqual(item.location, self.room1)
        self.assertEqual(item.home, self.room1)
        self.assertEqual(
            fixtures.layers(self.room1), ["a brass lantern: Warm light falls on the walls."]
        )
        self.assertEqual(fixtures.layers(self.room1, "smell"), ["a brass lantern: Beeswax."])
        self.assertEqual(self.room1.db.desc, before)
        self.assertFalse(item.move_to(self.char2, quiet=True))
        self.assertFalse(item.at_pre_get(self.char2))
        self.assertFalse(item.delete())
        self.assertTrue(FixtureInstallation.objects.get(pk=row.pk).active)

    def test_deleting_a_room_returns_its_fixtures_and_ends_its_layers(self):
        from evennia.utils.create import create_object

        room = create_object(FixtureRoom, key="a workshop loft")
        self.char1.move_to(room, quiet=True)
        item = self.fixture()
        placement = fixtures.install(self.char1, item, room)
        layer = fixtures.decorate(self.char1, self.fixture(room_line="Paper lanterns."), room)
        self.char1.move_to(self.room1, quiet=True)
        self.assertTrue(room.delete())
        placement.refresh_from_db()
        layer.refresh_from_db()
        self.assertFalse(placement.active)
        self.assertIsNotNone(placement.removed_at)
        self.assertIsNotNone(layer.cleared_at)
        self.assertEqual(ObjectDB.objects.get(pk=item.pk).location, self.char1)

    def test_one_fixture_supplies_one_layer_at_a_time(self):
        item = self.fixture()
        row = fixtures.decorate(self.char1, item, self.room1)
        with self.assertRaisesMessage(CraftingError, "already on display"):
            fixtures.decorate(self.char1, item, self.room1)
        self.char1.move_to(self.room2, quiet=True)
        with self.assertRaisesMessage(CraftingError, "already on display"):
            fixtures.decorate(self.char1, item, self.room2)
        with self.assertRaisesMessage(CraftingError, "already on display"):
            fixtures.install(self.char1, item, self.room2)
        self.char1.move_to(self.room1, quiet=True)
        fixtures.clear_layer(self.char1, row.pk)
        self.char1.move_to(self.room2, quiet=True)
        fixtures.install(self.char1, item, self.room2)
        self.assertEqual(fixtures.layers(self.room1), [])

    def test_resident_install_permission_never_grants_removal(self):
        item = self.fixture()
        item.move_to(self.char2, quiet=True)
        with override_settings(
            LINKS_ROOM_PERMISSION=lambda actor, room, action: action == "install"
        ):
            fixtures.install(self.char2, item, self.room1)
            with self.assertRaisesMessage(CraftingError, "property owner"):
                fixtures.uninstall(self.char2, item)
        fixtures.uninstall(self.char1, item)
        self.assertEqual(item.location, self.char1)
        self.assertFalse(FixtureInstallation.objects.get(craft=item.craft_record).active)

    def test_transfer_moves_control_and_credit_without_rewriting_provenance(self):
        item = self.fixture()
        original = item.craft_record.hallmark
        fixtures.install(self.char1, item, self.room1)
        self.owner = self.char2
        with self.assertRaises(CraftingError):
            fixtures.uninstall(self.char1, item)
        self.assertEqual(item.craft_record.hallmark, original)
        fixtures.uninstall(self.char2, item)
        self.assertEqual(item.location, self.char2)

    def test_archive_suspends_layers_and_credit_and_preserves_fixture(self):
        item = self.fixture()
        fixtures.install(self.char1, item, self.room1)
        self.live = False
        self.assertEqual(fixtures.layers(self.room1), [])
        self.assertEqual(fixtures.furnishing_caps(None, self.char1)["furnishing"]["money"], 0)
        self.assertTrue(FixtureInstallation.objects.filter(active=True).exists())
        self.assertTrue(ObjectDB.objects.filter(pk=item.pk).exists())
        fixtures.uninstall(self.char1, item)
        self.assertEqual(item.location, self.char1)

    def test_five_fixture_limit_and_atomic_failed_move(self):
        for _ in range(5):
            fixtures.install(self.char1, self.fixture(), self.room1)
        extra = self.fixture()
        with self.assertRaisesMessage(CraftingError, "fixture limit"):
            fixtures.install(self.char1, extra, self.room1)
        self.assertEqual(extra.location, self.char1)
        self.assertEqual(FixtureInstallation.objects.filter(active=True).count(), 5)
        fixtures.uninstall(
            self.char1, ObjectDB.objects.get(pk=FixtureInstallation.objects.first().craft.item_id)
        )
        with patch.object(extra, "move_to", return_value=False), self.assertRaises(CraftingError):
            fixtures.install(self.char1, extra, self.room1)
        self.assertFalse(FixtureInstallation.objects.filter(craft=extra.craft_record).exists())

    @skipUnless(apps.is_installed("evennia_economy"), "economy absent")
    def test_captured_valuation_scales_with_ubi_but_not_resale_or_retuned_input_values(self):
        item = self.fixture()
        self.assertEqual(item.craft_record.furnishing_weeks, Decimal("0.2"))
        fixtures.install(self.char1, item, self.room1)
        with override_settings(RP_ECONOMY_WEEKLY_AMOUNT=100, RP_CRAFTING_BASIC_FIXTURE_WEEKS="9"):
            self.assertEqual(fixtures.furnishing_caps(None, self.char1)["furnishing"]["money"], 20)
            self.assertGreaterEqual(cap_raise(self.char1, "money"), 20)
        with override_settings(RP_ECONOMY_WEEKLY_AMOUNT=200):
            self.assertEqual(fixtures.furnishing_caps(None, self.char1)["furnishing"]["money"], 40)
        self.owner = self.char2
        with override_settings(RP_ECONOMY_WEEKLY_AMOUNT=100):
            self.assertEqual(fixtures.furnishing_caps(None, self.char1)["furnishing"]["money"], 0)
            self.assertEqual(fixtures.furnishing_caps(None, self.char2)["furnishing"]["money"], 20)
        self.owner = None
        self.assertEqual(fixtures.furnishing_caps(None, self.char2)["furnishing"]["money"], 0)

    def test_bad_valuation_rolls_back_payment_item_and_record(self):
        before = self.held(), ObjectDB.objects.count(), CraftRecord.objects.count()
        with (
            override_settings(RP_CRAFTING_FURNISHING_REFERENCE=0),
            self.assertRaises(CraftingError),
        ):
            self.fixture()
        self.assertEqual(
            (self.held(), ObjectDB.objects.count(), CraftRecord.objects.count()), before
        )

    def test_temporary_layers_share_mood_policy_but_not_installation_or_credit(self):
        item = self.fixture()
        item.move_to(self.char2, quiet=True)
        with override_settings(SOCIAL_ROOM_MOOD_PERMISSION=lambda actor, room: actor == self.char2):
            self.assertTrue(can(self.char2, self.room1, "decorate"))
            self.assertFalse(can(self.char2, self.room1, "install"))
            with self.assertRaises(CraftingError):
                fixtures.install(self.char2, item, self.room1)
            row = fixtures.decorate(self.char2, item, self.room1, seconds=60)
        self.assertIn("Warm light", fixtures.layers(self.room1)[0])
        self.assertFalse(FixtureInstallation.objects.exists())
        self.assertEqual(fixtures.furnishing_caps(None, self.char2)["furnishing"]["money"], 0)
        fixtures.clear_layer(self.char2, row.pk)
        self.assertEqual(fixtures.layers(self.room1), [])

    def test_temporary_expiry_separate_capacity_and_owner_cleanup(self):
        for _ in range(3):
            fixtures.decorate(self.char1, self.fixture(), self.room1)
        with self.assertRaisesMessage(CraftingError, "temporary layer limit"):
            fixtures.decorate(self.char1, self.fixture(), self.room1)
        fixtures.install(self.char1, self.fixture(), self.room1)
        row = RoomLayer.objects.first()
        with self.assertRaises(CraftingError):
            fixtures.clear_layer(self.char2, row.pk)
        fixtures.clear_layer(self.char1, row.pk)
        RoomLayer.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(fixtures.active_layers(self.room1), [])
        fixtures.ambient_tick()
        self.assertFalse(RoomLayer.objects.filter(cleared_at__isnull=True).exists())

    @skipUnless(apps.is_installed("evennia_scenes"), "scenes absent")
    def test_scene_close_clears_layers_and_never_permanent_fixtures(self):
        from evennia_scenes.models import Scene
        from evennia_scenes.signals import scene_closed

        scene = Scene.objects.create(title="A gathering", room=self.room1, creator=self.char1)
        row = fixtures.decorate(self.char1, self.fixture(), self.room1)
        fixtures.install(self.char1, self.fixture(), self.room1)
        self.assertEqual(row.scene_id, scene.pk)
        scene_closed.send(sender=Scene, scene=scene, closer=self.char1)
        self.assertEqual(fixtures.active_layers(self.room1), [])
        self.assertEqual(FixtureInstallation.objects.filter(active=True).count(), 1)

    @skipUnless(apps.is_installed("evennia_accessibility"), "accessibility absent")
    def test_room_has_only_one_ambient_emitter_across_temporary_and_permanent_layers(self):
        fixtures.decorate(self.char1, self.fixture(ambient="A small chime rings."), self.room1)
        second = self.fixture(ambient="A candle flickers.")
        with self.assertRaisesMessage(CraftingError, "ambient emitter"):
            fixtures.install(self.char1, second, self.room1)
        with self.assertRaisesMessage(CraftingError, "ambient emitter"):
            fixtures.decorate(self.char1, second, self.room1)

    @skipUnless(apps.is_installed("evennia_accessibility"), "accessibility absent")
    def test_ambient_limits_mute_archive_and_transaction_rollback(self):
        from evennia_accessibility import mutes_ambient

        fixtures.install(self.char1, self.fixture(ambient="A chime rings softly."), self.room1)
        self.account2.options.options_dict = dict(self.account2.options.options_dict) | {
            "mute_ambient_effects": ("Ambient effects", "Boolean", False)
        }
        self.account2.options.set("mute_ambient_effects", "True")
        self.assertTrue(mutes_ambient(self.char2))
        with patch.object(self.char2, "msg") as heard, self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(fixtures.ambient_tick(), 1)
        heard.assert_not_called()
        self.assertEqual(fixtures.ambient_tick(), 0)
        now = timezone.now() + timedelta(seconds=301)
        self.live = False
        self.assertEqual(fixtures.ambient_tick(now), 0)
        self.live = True
        with (
            patch("evennia_rp_crafting.fixtures.emit") as emit,
            self.captureOnCommitCallbacks(execute=True),
            self.assertRaises(ValueError),
            transaction.atomic(),
        ):
            fixtures.ambient_tick(now)
            raise ValueError("Rollback")
        emit.assert_not_called()


class ActivationTests(WaveTwoFixture, EvenniaCommandTest):
    def test_wave_two_can_ship_dark_while_wave_one_remains_available(self):
        self.unlock()
        instrument = self.instrument()
        fixture = self.fixture()
        fixtures.install(self.char1, fixture, self.room1)
        with override_settings(RP_CRAFTING_WAVE_TWO_REVEALED=False):
            self.assertTrue(CmdCraft().access(self.char1))
            self.assertFalse(CmdFixture().access(self.char1))
            self.assertEqual(fixtures.layers(self.room1), [])
            self.assertEqual(fixtures.furnishing_caps(None, self.char1)["furnishing"]["money"], 0)
            self.assertEqual(self.book().read(self.char1), "A record of the road.")
            with self.assertRaises(CraftingError):
                activate(self.char1, instrument)
            before = self.held()
            with self.assertRaises(CraftingError):
                self.instrument()
            self.assertEqual(self.held(), before)
            output = self.call(CmdWorkshop(), "/catalog")
            self.assertNotIn("decoration:", output)
            self.assertNotIn("music:", output)
            self.char1.permissions.add("Builder")
            self.account.permissions.add("Builder")
            self.assertTrue(CmdFixture().access(self.char1))
            activate(self.char1, instrument)
        self.assertEqual(ActivationUse.objects.count(), 1)

    @skipUnless(apps.is_installed("evennia_rp_equipment"), "equipment absent")
    def test_playable_wearable_keeps_equipment_transfer_guards_and_combined_cost(self):
        from evennia_rp_equipment import services as equipment

        self.unlock("weaving")
        before = self.held()
        item = services.craft(
            self.char1,
            "weaving",
            "wearable",
            "a slung lute",
            "A lute on a strap.",
            {"worn_line": "a lute on a shoulder strap"},
            {"wood": 2},
            verbs=[
                {
                    "key": "activatable",
                    "niche": "music",
                    "configuration": {"modes": {"play": ["A string sings."]}},
                }
            ],
        )
        self.assertEqual(self.held(), before - 2)
        equipment.wear(self.char1, item)
        self.assertFalse(item.at_pre_give(self.char1, self.char2))
        activate(self.char1, item)
        self.assertTrue(ObjectDB.objects.filter(pk=item.pk).exists())

    def test_every_opened_fixture_and_carried_verb_set_uses_verified_dispatch(self):
        from .composition import invoke

        self.unlock()
        readable = {
            "key": "readable",
            "niche": "writing-0",
            "configuration": {"text": "A lantern legend."},
        }
        activation = {
            "key": "activatable",
            "niche": "music",
            "configuration": {"modes": {"play": ["A tune sounds."]}},
        }
        for verbs in ([], [readable], [activation], [readable, activation]):
            with self.subTest(verbs=[entry["key"] for entry in verbs]):
                item = services.craft(
                    self.char1,
                    "decoration",
                    "installable",
                    "a story lantern",
                    "A carved lantern.",
                    {"room_line": "A lantern hangs here."},
                    {"wood": 1 + len(verbs)},
                    verbs=verbs,
                )
                fixtures.install(self.char1, item, self.room1)
                if readable in verbs:
                    self.assertEqual(invoke(self.char2, item, "readable"), "A lantern legend.")
                if activation in verbs:
                    self.expire_event()
                    activate(self.char2, item)
        carried = services.craft(
            self.char1,
            "music",
            "carried",
            "a songbook",
            "A book of songs.",
            {},
            {"wood": 2},
            verbs=[readable, activation],
        )
        self.assertEqual(invoke(self.char1, carried, "readable"), "A lantern legend.")
        self.expire_event()
        activate(self.char1, carried)

    def test_item_cooldown_cannot_be_bypassed_by_moving_rooms(self):
        item = self.instrument()
        activate(self.char1, item)
        self.char1.move_to(self.room2, quiet=True)
        with self.assertRaisesMessage(CraftingError, "item was just used"):
            activate(self.char1, item)
        self.assertEqual(ActivationUse.objects.count(), 1)

    def test_reusable_modes_are_verified_and_rate_limited_without_spending_again(self):
        item = self.instrument()
        before = self.held()
        item.db.modes = {"play": ["Forged text."]}
        with patch.object(self.char2, "msg") as heard, self.captureOnCommitCallbacks(execute=True):
            result = activate(self.char1, item, "play")
        self.assertEqual(result.message, "<EVENT> A bright melody rings out.")
        heard.assert_called_once_with(
            (result.message, {"type": "crafting_event"}), from_obj=self.char1
        )
        with self.assertRaises(CraftingError):
            activate(self.char1, item, "play")
        self.assertEqual(self.held(), before)
        self.assertTrue(ObjectDB.objects.filter(pk=item.pk).exists())
        self.expire_event()
        activate(self.char1, item, "play")
        self.assertEqual(ActivationUse.objects.count(), 2)

    def test_possession_mode_and_use_lock_are_checked_before_reserving_output(self):
        item = self.instrument()
        with self.assertRaises(CraftingError):
            activate(self.char2, item)
        with self.assertRaises(CraftingError):
            activate(self.char1, item, "missing")
        item.locks.add("use:false()")
        with self.assertRaises(CraftingError):
            activate(self.char1, item)
        self.assertFalse(ActivationUse.objects.exists())
        self.assertFalse(EventRoomLimit.objects.exists())

    def test_interactive_fixture_visitors_can_use_but_cannot_remove(self):
        item = services.craft(
            self.char1,
            "decoration",
            "installable",
            "a music box",
            "A carved box.",
            {"room_line": "A small music box rests here."},
            {"wood": 2},
            verbs=[
                {
                    "key": "activatable",
                    "niche": "music",
                    "configuration": {"modes": {"play": ["The box plays a tune."]}},
                }
            ],
        )
        fixtures.install(self.char1, item, self.room1)
        activate(self.char2, item, "play")
        with self.assertRaises(CraftingError):
            fixtures.uninstall(self.char2, item)
        self.assertEqual(item.craft_record.furnishing_weeks, Decimal("0.4"))
        self.assertEqual(item.craft_record.contributors[1]["key"], "music")

    def test_random_readings_charge_each_authored_reading_and_do_not_grant_lore(self):
        item = self.instrument(
            configuration={"modes": {"read": ["Clouds gather.", "The road clears."]}},
            selected={"wood": 1, "spark": 1},
        )
        with patch("evennia_rp_crafting.wave_two.random.choice", return_value="The road clears."):
            self.assertEqual(activate(self.char1, item).message, "<EVENT> The road clears.")

    def test_draft_commands_and_use_mode(self):
        self.call(CmdCraft(), "/new music/activatable = a flute", "Craft draft saved: a flute.")
        self.call(CmdCraft(), "/desc A carved flute.")
        self.call(CmdCraft(), "/mode play = A high note carries.")
        self.call(CmdCraft(), "/resources 1 wood")
        self.call(CmdCraft(), "/finish", "You craft a flute.", receiver=self.char1)
        self.call(CmdUse(), "a flute = play", "You use a flute.")
        self.assertEqual(ActivationUse.objects.get().mode, "play")

    def test_room_commands_show_free_senses_before_fixture_lines(self):
        item = self.fixture(smell="Beeswax.", sound="A hum.")
        self.call(CmdFixture(), f"/install {item.key}", "Installed a brass lantern.")
        self.room1.attributes.add("room_smell", "Cool stone.")
        self.room1.attributes.add("room_sound", "A breeze.")
        self.call(CmdSense(), "", "Cool stone.\na brass lantern: Beeswax.")
        self.call(CmdListen(), "", "A breeze.\na brass lantern: A hum.")

    def test_fixture_numbers_report_usage_instead_of_parser_errors(self):
        self.fixture()
        self.call(CmdFixture(), "/clear first", "Usage: +fixture/clear <layer number>")
        self.call(
            CmdFixture(),
            "/decorate a brass lantern = soon",
            "Usage: +fixture/decorate <carried item> [= seconds]",
        )

    def test_missing_activation_cost_rules_report_a_crafting_error(self):
        costs = {**conf.DEFAULT_COSTS, "activatable": {"base": {"materials": 1}}}
        with (
            override_settings(RP_CRAFTING_COSTS=costs),
            self.assertRaisesMessage(CraftingError, "extra-mode"),
        ):
            services.craft_cost(
                self.char1, "music", "activatable", {"modes": {"play": ["One.", "Two."]}}
            )

    def test_freeze_hide_and_closed_production_do_not_rewrite_item_history(self):
        item = self.instrument()
        with override_settings(RP_CRAFTING_COMBINATIONS={}):
            activate(self.char1, item)
        self.expire_event()
        with override_settings(RP_CRAFTING_FROZEN=True), self.assertRaises(CraftingError):
            activate(self.char1, item)
        with override_settings(RP_CRAFTING_REVEALED=False), self.assertRaises(CraftingError):
            activate(self.char1, item)
