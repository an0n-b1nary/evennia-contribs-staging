# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Persistent service drafts preserve exact consent and defer all spending."""

from unittest import skipUnless

from django.apps import apps
from evennia.utils.dbserialize import deserialize
from evennia.utils.test_resources import EvenniaCommandTest

from . import modifiers
from .models import ModificationLayer, ModificationOffer
from .test_wave_three import WaveThreeFixture
from .wave_three_commands import CmdModify

DRAFT_KEY = "rp_crafting_modify_draft"


@skipUnless(not apps.is_installed("evennia_economy"), "Economy present")
class ModifierDraftWithoutEconomyTests(WaveThreeFixture, EvenniaCommandTest):
    def test_services_refuse_without_economy_and_keep_an_existing_draft(self):
        self.call(
            CmdModify(),
            f"/new {self.char2.key}/{self.item.key}=layers/modifier_aura",
            "That crafting behaviour is unavailable.",
        )
        self.assertIsNone(self.char1.attributes.get(DRAFT_KEY))
        draft = {
            "customer_id": self.char2.pk,
            "target_id": self.item.pk,
            "niche": "layers",
            "modifier": "modifier_aura",
            "configuration": {"line": "A silver shimmer."},
            "selected": {"spark": 1},
            "commission": 0,
        }
        self.char1.attributes.add(DRAFT_KEY, draft)
        self.call(CmdModify(), "", "Your recent services:")
        self.call(CmdModify(), "/proof", "Service draft:")
        self.call(CmdModify(), "/offer", "Modifier services require Economy")
        self.assertEqual(deserialize(self.char1.attributes.get(DRAFT_KEY)), draft)
        self.assertFalse(ModificationOffer.objects.exists())


@skipUnless(apps.is_installed("evennia_economy"), "Economy absent")
class ModifierDraftTests(WaveThreeFixture, EvenniaCommandTest):
    def draft(self):
        self.char1.attributes.reset_cache()
        return deserialize(self.char1.attributes.get(DRAFT_KEY))

    def start(self, *, target=None, kind="modifier_aura", switch="new"):
        self.call(
            CmdModify(),
            f"/{switch} {self.char2.key}/{(target or self.item).key}=layers"
            + (f"/{kind}" if switch == "new" else ""),
            "Service draft",
        )

    def ready(self):
        self.start()
        self.call(CmdModify(), "/line A shimmer; motes drift: gold = silver.")
        self.call(CmdModify(), "/resources 1 spark")
        self.call(CmdModify(), "/price 30")

    def test_recent_services_has_only_a_short_named_draft_reminder(self):
        row = self.offer()
        self.ready()
        saved = self.draft()
        output = self.call(CmdModify(), "")
        self.assertTrue(output.startswith("Your recent services:"))
        self.assertIn(f"service #{row.pk}", output)
        self.assertIn(f"Service draft: {self.item.key}.", output)
        self.assertIn("+modify/proof", output)
        self.assertNotIn(saved["configuration"]["line"], output)
        self.assertNotIn("Maker resources:", output)
        self.assertEqual(self.draft(), saved)

    def test_proof_is_an_explicit_read_only_view_of_only_the_callers_draft(self):
        self.call(CmdModify(), "/proof", "Start a service draft")
        self.ready()
        saved = self.draft()
        for switch in ("proof", "PRO"):
            output = self.call(CmdModify(), f"/{switch}")
            for text in (
                "modifier_aura",
                self.item.key,
                saved["configuration"]["line"],
                "1 spark",
                "commission: 30",
                "Nothing reserved",
            ):
                self.assertIn(text, output)
            self.assertNotIn("Your recent services:", output)
        self.call(CmdModify(), "/proof", "Start a service draft", caller=self.char2)
        for args, message in (
            ("/proof unexpected", "Usage: +modify/proof"),
            ("/proof =", "Usage: +modify/proof"),
            ("/proof/price", "Use one switch"),
            ("/pr", "Unknown or ambiguous"),
        ):
            self.call(CmdModify(), args, message)
        self.assertEqual(self.draft(), saved)
        self.assertFalse(ModificationOffer.objects.exists())
        self.assertFalse(ModificationLayer.objects.exists())

    def test_draft_acknowledgements_keep_long_target_names_short(self):
        self.item.key = "|g" + "A very long cloak name " * 8 + "|n"
        output = self.call(
            CmdModify(), f"/new #{self.char2.pk}/#{self.item.pk}=layers/modifier_aura"
        )
        self.assertIn("A very long cloak", output)
        self.assertIn("+modify/proof", output)
        self.assertLessEqual(len(output), 80)
        output = self.call(CmdModify(), "/line A private draft line.")
        self.assertNotIn("A private draft line.", output)
        self.assertLessEqual(len(output), 80)
        reminder = self.call(CmdModify(), "").splitlines()[-1]
        self.assertIn("A very long cloak", reminder)
        self.assertLessEqual(len(reminder), 80)

    def test_draft_and_proof_persist_without_spending_or_creating_an_offer(self):
        from evennia_economy.models import Offer
        from evennia_economy.services import balance

        before = (balance(self.char1), balance(self.char2), self.held("spark"))
        self.ready()
        output = self.call(CmdModify(), "/proof")
        for text in ("Service draft", "modifier_aura", "1 spark", "30", "Nothing reserved"):
            self.assertIn(text, output)
        self.assertEqual(
            self.draft()["configuration"]["line"], "A shimmer; motes drift: gold = silver."
        )
        self.assertEqual(self.draft()["selected"], {"spark": 1})
        self.assertEqual((balance(self.char1), balance(self.char2), self.held("spark")), before)
        self.assertFalse(ModificationOffer.objects.exists())
        self.assertFalse(Offer.objects.exists())
        self.assertFalse(ModificationLayer.objects.exists())
        self.assertNotIn("Service draft", self.call(CmdModify(), "", caller=self.char2))

    def test_offer_clears_only_maker_draft_then_customer_accepts_exact_terms_once(self):
        from evennia_economy.services import balance

        self.ready()
        before = (balance(self.char1), balance(self.char2), self.held("spark"))
        self.call(CmdModify(), "/offer", "service #")
        row = ModificationOffer.objects.get()
        self.assertEqual(row.configuration["line"], "A shimmer; motes drift: gold = silver.")
        self.assertEqual(row.resources, {"spark": 1})
        self.assertEqual(row.commission, 30)
        self.assertIsNone(self.draft())
        self.assertEqual((balance(self.char1), balance(self.char2), self.held("spark")), before)
        self.call(CmdModify(), "/offer", "Start a service draft")
        self.assertEqual(ModificationOffer.objects.count(), 1)
        self.call(CmdModify(), f"/accept {row.pk}", "Service #", caller=self.char2)
        self.assertEqual(
            (balance(self.char1), balance(self.char2), self.held("spark")),
            (before[0] + 30, before[1] - 30, before[2] - 1),
        )
        self.assertEqual(ModificationLayer.objects.get().text, row.configuration["line"])
        self.assertEqual(self.item.db.desc, "Original description.")

    def test_resource_selection_replaces_and_removes_one_key(self):
        self.start()
        self.call(CmdModify(), "/resources 1 spark")
        self.call(CmdModify(), "/resources 2 spark")
        self.call(CmdModify(), "/resources 1 wood")
        self.assertEqual(self.draft()["selected"], {"spark": 2, "wood": 1})
        self.call(CmdModify(), "/unresource wood")
        self.assertEqual(self.draft()["selected"], {"spark": 2})
        saved = self.draft()
        for value in ("spark:1", "1 spark, 2 wood", "0 spark", "-1 spark", "1 missing", "=1 spark"):
            with self.subTest(value=value):
                self.call(CmdModify(), f"/resources {value}")
                self.assertEqual(self.draft(), saved)
        self.call(CmdModify(), "/unresource missing", "That resource is not selected")

    def test_player_can_address_customer_and_target_by_dbref(self):
        self.account.is_superuser = False
        self.account.save(update_fields=["is_superuser"])
        self.account.permissions.clear()
        self.char1.permissions.clear()
        self.assertFalse(self.char1.permissions.check("Builder"))
        self.call(
            CmdModify(),
            f"/new #{self.char2.pk}/#{self.item.pk}=layers/modifier_aura",
            "Service draft",
        )
        self.assertEqual(self.draft()["customer_id"], self.char2.pk)
        self.assertEqual(self.draft()["target_id"], self.item.pk)

    def test_invalid_field_edits_preserve_draft(self):
        self.ready()
        saved = self.draft()
        for switch, values in (
            ("price", ("abc", "-1", "1.5", str(2**63), "=30", "30 ; 1")),
            ("replace", ("abc", "0", "-1", str(2**63), "=1")),
            ("line", ("=prose", "")),
        ):
            for value in values:
                with self.subTest(switch=switch, value=value):
                    self.call(CmdModify(), f"/{switch} {value}")
                    self.assertEqual(self.draft(), saved)
        self.assertFalse(ModificationOffer.objects.exists())

    def test_replacement_requires_explicit_layer_and_keeps_history(self):
        first = self.offer()
        modifiers.accept(self.char2, first.pk)
        layer = ModificationLayer.objects.get(service=first)
        self.ready()
        self.call(CmdModify(), "/offer", "Name the existing layer")
        self.assertIsNotNone(self.draft())
        self.call(CmdModify(), f"/replace #{layer.pk}")
        self.call(CmdModify(), "/replace")
        self.assertNotIn("layer_id", self.draft()["configuration"])
        self.call(CmdModify(), f"/replace {layer.pk}")
        self.call(CmdModify(), "/offer", "service #")
        second = ModificationOffer.objects.latest("pk")
        self.assertEqual(second.configuration["layer_id"], layer.pk)
        modifiers.accept(self.char2, second.pk)
        layer.refresh_from_db()
        self.assertEqual(layer.removed_by_id, second.pk)
        self.assertEqual(ModificationLayer.objects.count(), 2)

    def test_undo_draft_requires_layer_and_refuses_prose(self):
        first = self.offer()
        modifiers.accept(self.char2, first.pk)
        layer = ModificationLayer.objects.get(service=first)
        self.start(switch="undo")
        self.call(CmdModify(), "/resources 1 spark")
        self.call(CmdModify(), "/offer", "Undoing needs one selected layer")
        self.assertIsNotNone(self.draft())
        self.call(CmdModify(), "/line unwanted prose", "Undo drafts have no replacement prose")
        self.call(CmdModify(), f"/replace {layer.pk}")
        self.call(CmdModify(), "/offer", "service #")
        undo = ModificationOffer.objects.latest("pk")
        self.assertEqual(undo.configuration, {"layer_id": layer.pk})
        modifiers.accept(self.char2, undo.pk)
        layer.refresh_from_db()
        self.assertEqual(layer.removed_by_id, undo.pk)

    def test_failed_offer_retains_draft_for_correction_and_rechecks_owner(self):
        self.ready()
        self.call(CmdModify(), "/resources 2 spark")
        self.call(CmdModify(), "/offer")
        self.assertIsNotNone(self.draft())
        self.assertFalse(ModificationOffer.objects.exists())
        self.call(CmdModify(), "/resources 1 spark")
        self.item.location = self.char1
        self.call(CmdModify(), "/offer", "The consenting customer must currently own")
        self.assertIsNotNone(self.draft())
        self.item.location = self.char2
        self.call(CmdModify(), "/offer", "service #")

    def test_draft_uses_stable_ids_and_handles_deleted_targets(self):
        self.ready()
        self.item.key = "a renamed keepsake"
        self.call(CmdModify(), "/offer", "service #")
        self.assertEqual(ModificationOffer.objects.get().target_id, self.item.pk)
        self.start()
        self.item.delete()
        self.assertIn("unavailable", self.call(CmdModify(), ""))
        self.call(CmdModify(), "/offer", "The customer or target no longer exists")
        self.assertIsNotNone(self.draft())

    def test_cancel_draft_does_not_cancel_an_existing_offer(self):
        row = self.offer()
        self.ready()
        self.call(CmdModify(), "/cancel", "Service draft discarded")
        self.assertIsNone(self.draft())
        row.refresh_from_db()
        self.assertIsNone(row.cancelled_at)
        self.call(CmdModify(), f"/cancel {row.pk}", f"Service #{row.pk} cancelled")

    def test_old_forms_and_invalid_switches_cannot_mutate_a_draft(self):
        self.ready()
        saved = self.draft()
        for command in (
            f"/offer {self.char2.key}/{self.item.key}=layers/modifier_aura ; line ; spark:1 ; 30",
            f"/undo {self.char2.key}/{self.item.key}=layers ; 1 ; spark:1 ; 30",
            "/offer/new",
            "/bogus",
            "/r 1 spark",
            "/offer unexpected",
            "/cancel =1",
        ):
            with self.subTest(command=command):
                self.call(CmdModify(), command)
                self.assertEqual(self.draft(), saved)
                self.assertFalse(ModificationOffer.objects.exists())
        self.call(CmdModify(), "/PRICE 0")
        self.call(CmdModify(), "/off", "service #")

    def test_invalid_new_draft_preserves_existing_draft(self):
        self.ready()
        saved = self.draft()
        for args in (
            "",
            "missing",
            f"{self.char2.key}/{self.item.key}=layers/companion",
            f"{self.char2.key}/{self.item.key}=layers/missing",
            f"{self.char2.key}/{self.item.key}=missing/modifier_aura",
            f"{self.char2.key}/{self.item.key}=layers/modifier_undo",
        ):
            with self.subTest(args=args):
                self.call(CmdModify(), f"/new {args}")
                self.assertEqual(self.draft(), saved)

    def test_self_service_still_requires_acceptance_and_zero_price(self):
        self.call(CmdModify(), f"/new {self.char1.key}/{self.char1.key}=layers/modifier_mark")
        self.call(CmdModify(), "/line A silver mark.")
        self.call(CmdModify(), "/resources 1 spark")
        self.call(CmdModify(), "/price 1")
        self.call(
            CmdModify(), "/offer", "Use a nonnegative commission; self services have no commission."
        )
        self.assertIsNotNone(self.draft())
        self.call(CmdModify(), "/price 0")
        self.call(CmdModify(), "/offer", "service #")
        self.assertFalse(ModificationLayer.objects.exists())
        row = ModificationOffer.objects.get()
        self.call(CmdModify(), f"/accept {row.pk}", "Service #")
        self.assertEqual(ModificationLayer.objects.get().target_id, self.char1.pk)
