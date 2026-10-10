# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from copy import deepcopy
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import ValidationError
from django.test import override_settings
from evennia.objects.models import ObjectDB
from evennia.utils.ansi import strip_ansi
from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest
from evennia_rp_resources.models import ResourceDefinition, ResourceGrant, ResourceHolding
from evennia_rp_resources.services import grant

from evennia_links.runtime import cap_raise, get
from evennia_links.runtime import set as set_runtime

from . import conf, services
from .behaviours import behaviour
from .catalog import seed_catalog
from .commands import DRAFT_KEY, CmdCraft, CmdCrafting, CmdRead, CmdWorkshop
from .errors import CraftingError
from .models import CraftRecord, NicheDefinition, NicheUnlock, Workshop, WorkshopInvestment

HAS_ECONOMY = apps.is_installed("evennia_economy")
HAS_EQUIPMENT = apps.is_installed("evennia_rp_equipment")


def catalog():
    return [
        {
            "key": f"writing-{index}",
            "name": f"Scribe {index}",
            "description": "Written works.",
            "behaviours": ["readable"],
            "input_categories": ["materials"],
            "unlock_money": 100,
            "unlock_resources": {"materials": 3},
        }
        for index in range(7)
    ] + [
        {
            "key": "weaving",
            "name": "Weaver",
            "description": "Garments.",
            "behaviours": ["wearable"],
            "input_categories": ["materials", "essences"],
            "unlock_money": 100,
            "unlock_resources": {"materials": 3},
        }
    ]


TEST_SETTINGS = {
    "RP_CRAFTING_CATALOG": catalog,
    "RP_CRAFTING_REVEALED": True,
    "RP_CRAFTING_FROZEN": False,
    "RP_CRAFTING_NICHE_CAP": 5,
    "RP_CRAFTING_UNLOCK_STEP": 1,
    "RP_CRAFTING_MONEY_CAP_RAISE": 100,
    "RP_CRAFTING_RESOURCE_CAP_RAISE": 6,
    "RP_ECONOMY_FROZEN": False,
    "RP_ECONOMY_REVEALED": True,
    "RP_ECONOMY_FEE_CRAFT": 0,
    "RP_ECONOMY_FEE_POLICY": None,
    "RP_RESOURCES_CATEGORIES": [
        ("materials", "Materials"),
        ("essences", "Essences"),
        ("provisions", "Provisions"),
    ],
    "RP_CRAFTING_BEHAVIOURS": conf.DEFAULT_BEHAVIOURS,
    "RP_CRAFTING_COSTS": conf.DEFAULT_COSTS,
}


class CraftingFixture:
    def setUp(self):
        super().setUp()
        override = override_settings(**TEST_SETTINGS)
        override.enable()
        self.addCleanup(override.disable)
        for key, category in (
            ("wood", "materials"),
            ("ore", "materials"),
            ("grain", "provisions"),
            ("spark", "essences"),
        ):
            resource, _ = ResourceDefinition.objects.update_or_create(
                key=key, defaults={"name": key.title(), "category": category}
            )
            grant(self.char1, resource.key, 200, "staff")
        seed_catalog(update=True)
        self.char1.permissions.remove("Admin")
        self.char1.permissions.remove("Developer")
        self.account.permissions.remove("Developer")
        if HAS_ECONOMY:
            from evennia_economy.services import credit

            credit(self.char1, 10000)

    def held(self, key="wood"):
        return ResourceHolding.objects.get(character=self.char1, resource__key=key).quantity

    def unlock(self, key="writing-0"):
        workshop = Workshop.objects.filter(character=self.char1).first()
        count = services.active_unlocks(workshop).count() if workshop else 0
        return services.unlock(self.char1, key, {"wood": 3 * (count + 1)})

    def book(self, **overrides):
        params = {
            "actor": self.char1,
            "key": "writing-0",
            "behaviour_key": "readable",
            "name": "Field book",
            "description": "A bound notebook.",
            "configuration": {"text": "A record of the road."},
            "selected": {"wood": 1},
        }
        return services.craft(**(params | overrides))


class WorkshopTests(CraftingFixture, EvenniaTest):
    def test_unlock_costs_escalate_and_history_survives_abandonment(self):
        first = self.unlock()
        second = self.unlock("writing-1")
        self.assertEqual((first.position, second.position), (1, 2))
        self.assertEqual((first.resources_paid, second.resources_paid), ({"wood": 3}, {"wood": 6}))
        self.assertEqual(self.held(), 191)
        raises = (cap_raise(self.char1, "money"), cap_raise(self.char1, "resources"))
        services.abandon(self.char1, "writing-0")
        self.assertEqual(self.held(), 191)
        self.assertLess(cap_raise(self.char1, "resources"), raises[1])
        if HAS_ECONOMY:
            self.assertLess(cap_raise(self.char1, "money"), raises[0])
        repeated = self.unlock()
        self.assertEqual(repeated.position, 2)
        self.assertEqual(NicheUnlock.objects.filter(workshop__character=self.char1).count(), 3)
        self.assertEqual(
            WorkshopInvestment.objects.get(
                workshop__character=self.char1, resource_key="wood"
            ).quantity,
            15,
        )

    def test_active_niche_cap_is_mandatory_and_rechecked(self):
        with override_settings(RP_CRAFTING_NICHE_CAP=1):
            self.unlock()
            with self.assertRaisesMessage(CraftingError, "niche cap"):
                self.unlock("writing-1")
            services.abandon(self.char1, "writing-0")
            self.unlock("writing-1")
        with self.assertRaises(ValueError):
            set_runtime("RP_CRAFTING_NICHE_CAP", 0)
        with self.assertRaises(ValueError):
            set_runtime("RP_CRAFTING_NICHE_CAP", True)

    def test_duplicate_unlock_does_not_spend(self):
        self.unlock()
        before = self.held()
        with self.assertRaisesMessage(CraftingError, "already hold"):
            services.unlock(self.char1, "writing-0", {"wood": 6})
        self.assertEqual(self.held(), before)

    def test_exact_categories_and_active_resources_are_required(self):
        for selected in ({"grain": 3}, {"wood": 2}, {"wood": -3}, {"wood": True}, {"unknown": 3}):
            with self.assertRaises(CraftingError):
                services.unlock(self.char1, "writing-0", selected)
        ResourceDefinition.objects.filter(key="wood").update(archived=True)
        with self.assertRaisesMessage(CraftingError, "archived"):
            services.unlock(self.char1, "writing-0", {"wood": 3})
        self.assertFalse(Workshop.objects.exists())

    def test_split_resources_are_valid_and_shortfall_rolls_back_every_log(self):
        before = ResourceGrant.objects.count()
        ResourceHolding.objects.filter(character=self.char1, resource__key="wood").update(
            quantity=1
        )
        with self.assertRaises(CraftingError):
            services.unlock(self.char1, "writing-0", {"ore": 1, "wood": 2})
        self.assertEqual(ResourceGrant.objects.count(), before)
        self.assertEqual(self.held("ore"), 200)
        self.assertFalse(Workshop.objects.exists())
        services.unlock(self.char1, "writing-0", {"ore": 2, "wood": 1})

    def test_archiving_prevents_new_work_but_preserves_owned_slot_and_hallmark(self):
        self.unlock()
        book = self.book()
        definition = NicheDefinition.objects.get(key="writing-0")
        definition.archived = True
        definition.save()
        with self.assertRaises(CraftingError):
            self.book()
        self.assertEqual(cap_raise(self.char1, "resources"), 6)
        self.assertIn("Scribe 0", book.get_display_provenance())
        services.abandon(self.char1, "writing-0")
        self.assertEqual(cap_raise(self.char1, "resources"), 0)

    def test_catalogue_update_does_not_delete_omitted_keys_and_keys_cannot_change(self):
        original = NicheDefinition.objects.get(key="writing-0")
        with override_settings(RP_CRAFTING_CATALOG=lambda: []):
            seed_catalog(update=True)
        self.assertTrue(NicheDefinition.objects.filter(pk=original.pk).exists())
        original.key = "renamed"
        with self.assertRaises(ValidationError):
            original.save()

    def test_invalid_or_duplicate_catalogue_rolls_back(self):
        entries = catalog()
        entries[0]["key"] = "new"
        entries[1]["behaviours"] = ["unregistered"]
        with override_settings(RP_CRAFTING_CATALOG=lambda: entries), self.assertRaises(ValueError):
            seed_catalog(update=True)
        self.assertFalse(NicheDefinition.objects.filter(key="new").exists())
        with (
            override_settings(RP_CRAFTING_CATALOG=lambda: [catalog()[0], catalog()[0]]),
            self.assertRaises(ValueError),
        ):
            seed_catalog(update=True)

    def test_runtime_freeze_and_hide_are_enforced_by_services(self):
        for setting in ("RP_CRAFTING_FROZEN", "RP_CRAFTING_REVEALED"):
            with (
                override_settings(**{setting: setting.endswith("FROZEN")}),
                self.assertRaises(CraftingError),
            ):
                self.unlock()

    @skipUnless(HAS_ECONOMY, "economy absent")
    def test_money_shortfall_and_economy_freeze_roll_back_unlock(self):
        from evennia_economy.models import LedgerEntry, Purse

        Purse.objects.filter(character=self.char1).update(balance=10)
        before = LedgerEntry.objects.count()
        with self.assertRaises(CraftingError):
            self.unlock()
        self.assertEqual(self.held(), 200)
        self.assertEqual(LedgerEntry.objects.count(), before)
        with override_settings(RP_ECONOMY_FROZEN=True), self.assertRaises(CraftingError):
            self.unlock()

    @skipUnless(HAS_ECONOMY, "economy absent")
    @override_settings(RP_ECONOMY_WEEKLY_AMOUNT=10, RP_ECONOMY_BASE_CAP_WEEKS=5)
    def test_money_cap_covers_next_unlock_including_while_at_cap(self):
        from evennia_economy.batch import money_cap

        for index in range(5):
            self.unlock(f"writing-{index}")
            self.assertGreaterEqual(money_cap(self.char1), 100 * (index + 2))
        before = money_cap(self.char1)
        services.abandon(self.char1, "writing-0")
        self.assertLess(money_cap(self.char1), before)

    @override_settings(RP_RESOURCES_BASE_CAP=5)
    def test_resource_cap_covers_next_unlock_under_retuned_costs(self):
        from evennia_rp_resources.batch import holdings_cap

        self.unlock()
        NicheDefinition.objects.filter(key="writing-1").update(unlock_resources={"materials": 30})
        self.assertGreaterEqual(holdings_cap(self.char1), 60)


class CraftTests(CraftingFixture, EvenniaTest):
    def setUp(self):
        super().setUp()
        self.unlock()

    def test_readable_is_paid_once_with_snapshot_and_protected_hallmark(self):
        before = self.held()
        item = self.book()
        self.assertEqual(self.held(), before - 1)
        self.assertEqual(item.read(self.char2), "A record of the road.")
        self.assertEqual(CraftRecord.objects.count(), 1)
        record = item.craft_record
        item.db.hallmark = "Made by someone else"
        item.db.crafting_text = "tampered"
        self.char1.key = "Renamed maker"
        NicheDefinition.objects.filter(key="writing-0").update(name="Renamed niche")
        self.assertEqual(item.get_display_provenance(), record.hallmark)
        self.assertIn("Craft hallmark:", strip_ansi(item.return_appearance(self.char2)))
        self.assertEqual(record.prose["description"], "A bound notebook.")
        self.assertEqual(record.resources_spent, {"wood": 1})
        self.assertIsNotNone(Workshop.objects.get(character=self.char1).last_craft)

    def test_record_survives_item_and_crafter_deletion(self):
        item = self.book()
        record = item.craft_record
        item.delete()
        self.char1.delete()
        kept = CraftRecord.objects.get(pk=record.pk)
        self.assertEqual(kept.hallmark, record.hallmark)
        with self.assertRaises(ValidationError):
            kept.save()
        with self.assertRaises(ValidationError):
            kept.delete()

    def test_failed_creation_or_record_write_rolls_back_item_costs_and_logs(self):
        for target in (
            "evennia_rp_crafting.behaviours.create_object",
            "evennia_rp_crafting.models.CraftRecord.objects.create",
        ):
            before = (ObjectDB.objects.count(), ResourceGrant.objects.count(), self.held())
            with (
                patch(target, side_effect=RuntimeError("creation failed")),
                self.assertRaises(RuntimeError),
            ):
                self.book()
            self.assertEqual(
                (ObjectDB.objects.count(), ResourceGrant.objects.count(), self.held()), before
            )
        self.assertIsNone(Workshop.objects.get(character=self.char1).last_craft)

    def test_unowned_niche_unknown_features_and_length_limits_do_not_spend(self):
        for overrides in (
            {"key": "writing-1"},
            {"configuration": {"text": "ok", "unknown": "x"}},
            {"configuration": {"text": ""}},
            {"description": "x" * 4001},
            {"name": "x" * 81},
            {"behaviour_key": "wearable"},
            {"selected": {"spark": 1}},
        ):
            with self.assertRaises(CraftingError):
                self.book(**overrides)
        self.assertEqual(self.held(), 197)

    def test_read_lock_is_respected(self):
        item = self.book()
        item.locks.add("read:false()")
        with self.assertRaises(CraftingError):
            item.read(self.char2)

    @skipUnless(HAS_ECONOMY, "economy absent")
    def test_nonzero_craft_fee_is_journaled_once_and_failed_record_refunds_it(self):
        from evennia_economy.models import LedgerEntry
        from evennia_economy.services import balance

        def policy(kind, actor, context):
            return 7 if kind == "craft" else 0

        with override_settings(RP_ECONOMY_FEE_POLICY=policy):
            before = balance(self.char1)
            item = self.book()
            self.assertEqual(item.craft_record.money_spent, 7)
            self.assertEqual(balance(self.char1), before - 7)
            self.assertEqual(LedgerEntry.objects.filter(fee_kind="craft", fee=7).count(), 1)
            with (
                patch(
                    "evennia_rp_crafting.models.CraftRecord.objects.create",
                    side_effect=RuntimeError,
                ),
                self.assertRaises(RuntimeError),
            ):
                self.book()
            self.assertEqual(balance(self.char1), before - 7)
            self.assertEqual(LedgerEntry.objects.filter(fee_kind="craft", fee=7).count(), 1)


class CommandTests(CraftingFixture, EvenniaCommandTest):
    def test_persistent_draft_finish_and_second_finish_do_not_duplicate(self):
        self.call(CmdWorkshop(), "/unlock writing-0 = wood:3", "Unlocked Scribe 0")
        self.call(CmdCraft(), "/new writing-0/readable = travel journal", "Craft draft saved")
        self.call(CmdCraft(), "/desc = A travel journal.", "Craft draft saved")
        self.call(CmdCraft(), "/text = The road goes north.", "Craft draft saved")
        self.call(CmdCraft(), "/resources = wood:1", "Craft draft saved")
        self.call(CmdCraft(), "", "Draft: travel journal")
        self.assertEqual(self.held(), 197)
        self.call(CmdCraft(), "/finish", "You craft travel journal")
        self.assertFalse(self.char1.attributes.has(DRAFT_KEY))
        self.call(CmdCraft(), "/finish", "Start a draft")
        self.call(CmdRead(), "travel journal", "travel journal\nThe road goes north.")
        self.assertEqual(CraftRecord.objects.count(), 1)

    def test_failed_finish_preserves_draft_and_catalogue_shows_current_costs(self):
        self.unlock()
        self.call(CmdCraft(), "/new writing-0/readable = book", "Craft draft saved")
        self.call(CmdCraft(), "/finish", "Readable text must contain")
        self.assertTrue(self.char1.attributes.has(DRAFT_KEY))
        self.call(CmdWorkshop(), "/catalog", "Niches — next unlock position 2")
        self.call(CmdWorkshop(), "", "Your Workshop: 1/5 active niches.")
        self.call(CmdCraft(), "/cancel", "Craft draft discarded")

    def test_catalogue_and_drafts_survive_a_behaviour_removed_from_the_registry(self):
        self.call(CmdCraft(), "/new writing-0/readable = book", "Craft draft saved")
        with override_settings(
            RP_CRAFTING_BEHAVIOURS={"wearable": conf.DEFAULT_BEHAVIOURS["wearable"]}
        ):
            output = self.call(CmdWorkshop(), "/catalog", "Niches — next unlock position 1")
            self.assertIn("writing-0: Scribe 0 [unavailable] — unavailable", output)
            self.call(CmdCraft(), "/text = Lost words.", "That crafting behaviour is unavailable")

    def test_staff_review_contains_full_snapshot_and_refuses_players(self):
        self.unlock()
        item = self.book()
        self.call(CmdCrafting(), f"/review {item.craft_record.pk}", "Staff only.")
        self.char1.permissions.add("Builder")
        self.account.permissions.add("Builder")
        self.call(
            CmdCrafting(), f"/review {item.craft_record.pk}", f"Craft #{item.craft_record.pk}"
        )
        self.call(CmdCrafting(), "/review", "Recent crafts:")

    def test_hidden_commands_are_inaccessible_to_players(self):
        with override_settings(RP_CRAFTING_REVEALED=False):
            self.assertFalse(CmdCraft().access(self.char1))
            self.char1.permissions.add("Builder")
            self.account.permissions.add("Builder")
            self.assertTrue(CmdCraft().access(self.char1))

    def test_bad_resource_syntax_and_wrong_behaviour_field_leave_draft_untouched(self):
        self.call(CmdCraft(), "/new writing-0/readable = book", "Craft draft saved")
        original = deepcopy(dict(self.char1.attributes.get(DRAFT_KEY)))
        self.call(CmdCraft(), "/resources = wood:1,wood:1", "Select resources as")
        self.call(CmdCraft(), "/aura = shining", "That field isn't available")
        self.assertEqual(dict(self.char1.attributes.get(DRAFT_KEY)), original)


class PartnerAvailabilityTests(CraftingFixture, EvenniaTest):
    def test_persisted_wearable_keeps_verified_hallmark_when_equipment_is_absent(self):
        if HAS_EQUIPMENT:
            self.skipTest("requires physically absent equipment")
        item = create_object(
            "evennia_rp_crafting.wearables.Wearable", key="old cloak", location=self.char1
        )
        item.db.desc = "An old woven cloak."
        item.db.worn_line = "an old cloak"
        CraftRecord.objects.create(
            crafter_id=self.char1.pk,
            crafter_name=self.char1.key,
            niche=NicheDefinition.objects.get(key="weaving"),
            niche_name="Weaver",
            behaviour="wearable",
            item_id=item.pk,
            prose={"configuration": {"aura_line": "soft sparks"}},
            hallmark="Made by Char (Weaver)",
        )
        self.assertIn("Made by Char (Weaver)", strip_ansi(item.return_appearance(self.char2)))
        self.assertIn("soft sparks", item.get_worn_line(self.char2))

    def test_readable_available_and_money_cost_matches_installed_partners(self):
        self.assertTrue(behaviour("readable").available())
        self.unlock()
        self.assertEqual(NicheUnlock.objects.get().money_paid, 100 if HAS_ECONOMY else 0)
        self.assertTrue(self.book().read(self.char1))

    def test_wearable_fails_cleanly_without_equipment(self):
        if HAS_EQUIPMENT:
            self.assertTrue(behaviour("wearable").available())
        else:
            with self.assertRaises(CraftingError):
                behaviour("wearable")
            with self.assertRaisesMessage(CraftingError, "unavailable"):
                services.unlock(self.char1, "weaving", {"wood": 3})
            self.assertEqual(self.held(), 200)
