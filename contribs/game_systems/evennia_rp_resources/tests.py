# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Ledger safety, passive income, terrain selection, visibility and commands."""

from datetime import UTC, datetime
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import override_settings
from evennia.utils.test_resources import BaseEvenniaCommandTest, EvenniaTest

from evennia_links import runtime
from evennia_links.commands import CmdRuntime

from . import batch, gathering
from .catalog import seed_catalog
from .commands import CmdGather, CmdResources
from .models import ResourceDefinition, ResourceGrant, ResourceHolding
from .profile import gathering_field
from .services import ResourceError, grant, spend, total_held
from .summary import notify_resource_summary


def catalog():
    return [
        {
            "key": "wood",
            "name": "Wood",
            "category": "materials",
            "terrains": ["forest"],
            "weight": 2,
        },
        {"key": "grain", "name": "Grain", "category": "provisions", "terrains": []},
        {"key": "ore", "name": "Ore", "category": "materials", "terrains": ["mine"]},
        {"key": "rare", "name": "Rare crystal", "category": "essences", "in_trickle": False},
    ]


@override_settings(
    RP_RESOURCES_CATALOG="evennia_rp_resources.tests.catalog",
    RP_RESOURCES_CATEGORIES=[
        ("materials", "Materials"),
        ("provisions", "Provisions"),
        ("essences", "Essences"),
    ],
    RP_RESOURCES_OPEN_TERRAINS=["forest"],
    RP_RESOURCES_WEEKLY_QUANTITY=6,
    RP_RESOURCES_BASE_CAP=30,
    RP_RESOURCES_TAPER_FRACTION=0.8,
    RP_RESOURCES_REVEALED=True,
    RP_ECONOMY_ELIGIBLE=None,
)
class ResourceTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        seed_catalog(update=True)

    def run_batch(self, week="2026-W40", **kwargs):
        result = batch.run_weekly_batch(week, characters=[self.char2], **kwargs)
        self.assertEqual(result["errors"], [])
        return result

    def test_grant_and_spend_log_signed_amounts(self):
        grant(self.char2, "wood", 5, "staff", by=self.char1, note="Test stock")
        spend(self.char2, "wood", 2, "Test craft")
        self.assertEqual(total_held(self.char2), 3)
        self.assertEqual(list(ResourceGrant.objects.values_list("quantity", flat=True)), [5, -2])
        self.assertEqual(ResourceGrant.objects.first().by_id, self.char1.pk)

    def test_archived_reserved_stock_can_be_refunded_without_reopening_grants(self):
        grant(self.char2, "wood", 3)
        spend(self.char2, "wood", 3, "Reserved listing", source="exchange")
        ResourceDefinition.objects.filter(key="wood").update(archived=True)
        with self.assertRaises(ResourceError):
            grant(self.char2, "wood", 3)
        grant(self.char2, "wood", 3, "exchange", allow_archived=True, note="Listing returned")
        self.assertEqual(total_held(self.char2), 3)
        self.assertEqual(ResourceGrant.objects.last().source, "exchange")
        self.assertTrue(ResourceDefinition.objects.get(key="wood").archived)

    def test_shortfall_does_not_change_balance_or_log(self):
        grant(self.char2, "wood", 2)
        with self.assertRaises(ResourceError):
            spend(self.char2, "wood", 3, "Too much")
        self.assertEqual(total_held(self.char2), 2)
        self.assertEqual(ResourceGrant.objects.count(), 1)

    def test_caller_transaction_rolls_back_balance_and_log(self):
        with self.assertRaises(RuntimeError), transaction.atomic():
            grant(self.char2, "wood", 4, "exchange", exchange_id=123)
            raise RuntimeError("Partner transaction failed")
        self.assertEqual(total_held(self.char2), 0)
        self.assertFalse(ResourceGrant.objects.exists())

    def test_invalid_log_write_rolls_back_counter(self):
        with (
            patch.object(ResourceGrant.objects, "create", side_effect=RuntimeError("Ledger down")),
            self.assertRaises(RuntimeError),
        ):
            grant(self.char2, "wood", 4)
        self.assertEqual(total_held(self.char2), 0)

    def test_positive_whole_quantities_only(self):
        for quantity in (0, -1, True, 1.5, "2"):
            with self.subTest(quantity=quantity), self.assertRaises(ResourceError):
                grant(self.char2, "wood", quantity)
        self.assertFalse(ResourceGrant.objects.exists())

    def test_unknown_source_and_key_fail_without_writes(self):
        with self.assertRaises(ResourceError):
            grant(self.char2, "wood", 1, "typo")
        with self.assertRaises(ResourceError):
            grant(self.char2, "missing", 1)
        self.assertFalse(ResourceGrant.objects.exists())

    def test_archived_stock_remains_spendable(self):
        grant(self.char2, "wood", 2)
        ResourceDefinition.objects.filter(key="wood").update(archived=True)
        with self.assertRaises(ResourceError):
            grant(self.char2, "wood", 1)
        spend(self.char2, "wood", 2, "Retire stock")
        self.assertEqual(total_held(self.char2), 0)

    def test_database_rejects_negative_holding_and_duplicate_counter(self):
        grant(self.char2, "wood", 2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ResourceHolding.objects.filter(character=self.char2).update(quantity=-1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ResourceHolding.objects.create(
                character=self.char2, resource=ResourceDefinition.objects.get(key="wood")
            )

    def test_seed_updates_labels_without_deleting_holdings(self):
        grant(self.char2, "wood", 2)
        ResourceDefinition.objects.filter(key="wood").update(name="Old label")
        seed_catalog(update=True)
        self.assertEqual(ResourceDefinition.objects.get(key="wood").name, "Wood")
        self.assertEqual(ResourceHolding.objects.get(character=self.char2).quantity, 2)

    def test_seeding_is_idempotent(self):
        seed_catalog(update=True)
        self.assertEqual(ResourceDefinition.objects.count(), 4)

    def test_resource_key_cannot_be_renamed(self):
        resource = ResourceDefinition.objects.get(key="wood")
        resource.key = "renamed-wood"
        with self.assertRaises(ValidationError):
            resource.save()
        self.assertTrue(ResourceDefinition.objects.filter(key="wood").exists())

    def test_open_common_and_payout_only_pools(self):
        self.assertEqual({resource.key for resource in gathering.pool()}, {"wood", "grain"})

    def test_no_open_terrains_still_yields_common_pool(self):
        with override_settings(RP_RESOURCES_OPEN_TERRAINS=[]):
            self.assertEqual([resource.key for resource in gathering.pool()], ["grain"])

    def test_tag_fallback_without_maps(self):
        self.room1.tags.add("forest", category="terrain")
        with patch("evennia_rp_resources.gathering.apps.is_installed", return_value=False):
            self.assertEqual(gathering.terrain_for(self.room1), "forest")

    def test_host_terrain_and_open_terrain_callables(self):
        with override_settings(
            RP_RESOURCES_TERRAIN_PROVIDER=lambda room: "mine",
            RP_RESOURCES_OPEN_TERRAINS=lambda: ["mine"],
        ):
            self.assertEqual(gathering.terrain_for(self.room1), "mine")
            self.assertEqual({resource.key for resource in gathering.pool()}, {"ore", "grain"})

    def test_persistent_resource_and_category_lean(self):
        gathering.set_lean(self.char2, "Wood")
        self.assertEqual(gathering.lean(self.char2), {"type": "resource", "key": "wood"})
        gathering.set_lean(self.char2, "Materials")
        self.assertEqual(gathering.lean(self.char2), {"type": "category", "key": "materials"})

    def test_closed_and_payout_only_lean_refused(self):
        for value in ("ore", "rare", "essences"):
            with self.assertRaises(ResourceError):
                gathering.set_lean(self.char2, value)

    def test_existing_lean_reports_when_terrain_closes(self):
        gathering.set_lean(self.char2, "wood")
        with override_settings(RP_RESOURCES_OPEN_TERRAINS=[]):
            self.assertIn("currently yields nothing", gathering.lean_description(self.char2))

    def test_preview_is_read_only_and_matches_seeded_payout(self):
        preview = self.run_batch(dry_run=True)
        self.assertFalse(ResourceGrant.objects.exists())
        self.assertFalse(ResourceHolding.objects.exists())
        paid = self.run_batch()
        self.assertEqual(preview, paid)
        self.assertEqual(total_held(self.char2), 6)

    def test_repeat_does_not_pay_again_even_after_spend(self):
        self.run_batch()
        holding = ResourceHolding.objects.filter(character=self.char2, quantity__gt=0).first()
        spend(self.char2, holding.resource.key, 1, "Use stock")
        self.assertEqual(self.run_batch()["characters"], {})
        self.assertEqual(total_held(self.char2), 5)

    def test_full_batch_records_zero_once_and_never_decays(self):
        grant(self.char2, "wood", 40)
        self.run_batch()
        self.assertEqual(total_held(self.char2), 40)
        receipt = ResourceGrant.objects.get(source="trickle", resource__isnull=True)
        self.assertTrue(receipt.details["tapered"])
        self.assertEqual(self.run_batch()["characters"], {})

    def test_linear_taper_and_nontrickle_grants_ignore_cap(self):
        self.assertEqual(
            [batch.accrual_quantity(held, 30) for held in (0, 24, 27, 29, 30, 40)],
            [6, 6, 3, 1, 0, 0],
        )
        grant(self.char2, "wood", 29)
        self.run_batch()
        self.assertEqual(total_held(self.char2), 30)
        grant(self.char2, "rare", 8, "payout", thread_id=1)
        self.assertEqual(total_held(self.char2), 38)

    def test_cap_contributions_are_provider_scoped_and_optional(self):
        def workshops(**kwargs):
            return {"workshop": {"resources": 12, "money": 50}}

        runtime.cap_contributions.connect(workshops, weak=False)
        try:
            self.assertEqual(batch.holdings_cap(self.char2), 42)
        finally:
            runtime.cap_contributions.disconnect(workshops)
        self.assertEqual(batch.holdings_cap(self.char2), 30)

    def test_lean_changes_weights_never_quantity(self):
        gathering.set_lean(self.char2, "wood")
        self.run_batch()
        receipt = ResourceGrant.objects.get(resource__isnull=True)
        self.assertEqual(
            dict(zip(receipt.details["pool"], receipt.details["weights"], strict=True)),
            {"grain": 1, "wood": 4},
        )
        self.assertEqual(total_held(self.char2), 6)

    def test_empty_pool_still_records_receipt(self):
        ResourceDefinition.objects.update(in_trickle=False)
        self.run_batch()
        self.assertEqual(total_held(self.char2), 0)
        self.assertEqual(self.run_batch()["characters"], {})

    def test_failed_character_can_retry_without_partial_grants(self):
        with patch("evennia_rp_resources.batch.grant", side_effect=RuntimeError("Failed credit")):
            result = batch.run_weekly_batch("2026-W40", characters=[self.char2])
        self.assertEqual(len(result["errors"]), 1)
        self.assertFalse(ResourceGrant.objects.exists())
        self.run_batch()
        self.assertEqual(total_held(self.char2), 6)

    def test_offline_playable_characters_accrue_without_rp(self):
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        result = batch.run_weekly_batch("2026-W40")
        self.assertEqual(result["errors"], [])
        self.assertEqual(total_held(self.char1), 6)
        self.assertEqual(total_held(self.char2), 6)
        self.assertNotIn(self.obj1.pk, result["characters"])

    def test_shared_eligibility_predicate(self):
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        with override_settings(RP_ECONOMY_ELIGIBLE=lambda character: character.pk == self.char2.pk):
            result = batch.run_weekly_batch("2026-W40")
        self.assertEqual(set(result["characters"]), {self.char2.pk})

    def test_week_boundary_and_shortened_runtime_period(self):
        self.assertEqual(batch.period_key(datetime(2026, 10, 5, tzinfo=UTC)), "2026-W40")
        with override_settings(RP_RESOURCES_PERIOD_SECONDS=86400):
            self.assertEqual(
                batch.period_key(datetime(2026, 10, 5, 12, tzinfo=UTC)),
                "86400s:2026-10-05T00:00:00+00:00",
            )

    def test_dark_accrual_summary_waits_until_reveal(self):
        with override_settings(RP_RESOURCES_REVEALED=False):
            self.run_batch()
            with patch.object(self.char2, "msg") as msg:
                self.assertFalse(notify_resource_summary(self.char2))
                msg.assert_not_called()
            self.assertIsNone(self.char2.attributes.get("last_resource_summary_week"))
        with patch.object(self.char2, "msg") as msg:
            self.assertTrue(notify_resource_summary(self.char2))
            self.assertFalse(notify_resource_summary(self.char2))
            msg.assert_called_once()

    def test_full_stores_notification_is_one_quiet_line(self):
        grant(self.char2, "wood", 30)
        self.run_batch()
        with patch.object(self.char2, "msg") as msg:
            notify_resource_summary(self.char2)
        self.assertIn("Your stores are full", msg.call_args.args[0])

    def test_full_stores_are_mentioned_once_not_weekly(self):
        grant(self.char2, "wood", 30)
        sent = []
        for week in ("2026-W40", "2026-W41", "2026-W42"):
            self.run_batch(week)
            with patch.object(self.char2, "msg") as msg:
                notify_resource_summary(self.char2)
            sent.append([call.args[0] for call in msg.call_args_list])
        self.assertEqual(len(sent[0]), 1)
        self.assertIn("Your stores are full", sent[0][0])
        self.assertEqual(sent[1:], [[], []])
        spend(self.char2, "wood", 20, "Room again")
        self.run_batch("2026-W43")
        with patch.object(self.char2, "msg") as msg:
            notify_resource_summary(self.char2)
        self.assertNotIn("full", msg.call_args.args[0])

    def batch_script(self):
        from evennia.utils.create import create_script

        return create_script(
            "evennia_rp_resources.scripts.ResourceBatchScript",
            key="rp_resources_batch",
            autostart=False,
        )

    def test_scheduler_retries_only_failures_with_backoff(self):
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        script = self.batch_script()
        real_grant = batch.grant
        attempts = []

        def flaky(character, *args, **kwargs):
            attempts.append(character.pk)
            if character.pk == self.char2.pk:
                raise RuntimeError("Grant failed")
            return real_grant(character, *args, **kwargs)

        with (
            patch("evennia_rp_resources.batch.period_key", return_value="2026-W40"),
            patch("evennia_rp_resources.batch.grant", side_effect=flaky),
            self.assertLogs("evennia", level="ERROR"),
        ):
            script.at_repeat()
            before = len(attempts)
            script.at_repeat()  # within the backoff: no per-minute rerun
        self.assertEqual(len(attempts), before)
        pending = script.db.batch_state["pending"]
        self.assertEqual([entry["ids"] for entry in pending], [[self.char2.pk]])
        with (
            patch("evennia_rp_resources.batch.period_key", return_value="2026-W40"),
            patch("evennia_links.periodic.time.time", return_value=pending[0]["due"]),
        ):
            script.at_repeat()
        self.assertEqual((total_held(self.char1), total_held(self.char2)), (6, 6))
        self.assertEqual(script.db.batch_state["pending"], [])

    def test_scripts_from_before_the_queue_keep_their_last_period(self):
        self.account2.characters.add(self.char2)
        script = self.batch_script()
        script.db.last_batch_week = "2026-W40"
        with patch("evennia_rp_resources.batch.period_key", return_value="2026-W40"):
            script.at_repeat()
        self.assertEqual(total_held(self.char2), 0)

    def test_profile_field_skips_the_open_terrain_scan(self):
        gathering.set_lean(self.char2, "wood")
        with patch("evennia_rp_resources.gathering.pool") as scan:
            self.assertEqual(gathering_field(self.char1, self.char2), {"Gathering": "Wood"})
        scan.assert_not_called()

    def test_hidden_notifications_are_suppressed_for_staff_too(self):
        batch.run_weekly_batch("2026-W40", characters=[self.char1])
        with override_settings(RP_RESOURCES_REVEALED=False), patch.object(self.char1, "msg") as msg:
            self.assertFalse(notify_resource_summary(self.char1))
            msg.assert_not_called()

    def test_reveal_hides_commands_help_and_profile_from_players(self):
        with override_settings(RP_RESOURCES_REVEALED=False):
            self.assertFalse(CmdGather().access(self.char2))
            self.assertFalse(CmdResources().access(self.char2))
            self.assertTrue(CmdGather().access(self.char1))
            self.assertEqual(gathering_field(self.char2, self.char1), {})
            self.assertIn("Gathering", gathering_field(self.char1, self.char2))


class ResourceCommandTests(BaseEvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.controls = override_settings(
            RP_RESOURCES_OPEN_TERRAINS=["forest"],
            RP_RESOURCES_CATALOG="evennia_rp_resources.tests.catalog",
            RP_RESOURCES_REVEALED=True,
        )
        self.controls.enable()
        self.addCleanup(self.controls.disable)
        seed_catalog(update=True)

    def test_gather_set_show_clear(self):
        self.call(CmdGather(), "wood", "Gathering lean: Wood.")
        self.assertIn("Wood", self.call(CmdGather(), ""))
        self.call(CmdGather(), "/clear", "Gathering lean cleared.")
        self.assertIsNone(gathering.lean(self.char1))

    def test_staff_grant_spend_and_audit(self):
        self.call(CmdResources(), "/grant Char2=wood,4,Test")
        self.assertEqual(total_held(self.char2), 4)
        self.call(CmdResources(), "/spend Char2=wood,2,Test")
        self.assertEqual(total_held(self.char2), 2)
        self.assertIn("staff", self.call(CmdResources(), "/audit Char2"))

    def test_player_cannot_run_batch_or_grant(self):
        self.call(CmdResources(), "/run", "Only staff may use this switch.", caller=self.char2)
        self.call(
            CmdResources(),
            "/grant Char2=wood,3",
            "Only staff may use this switch.",
            caller=self.char2,
        )
        self.assertFalse(ResourceGrant.objects.exists())

    def test_runtime_controls_reject_unknown_and_bad_values(self):
        self.assertIn("not registered", self.call(CmdRuntime(), "SECRET_KEY=4"))
        self.assertIn("Invalid value", self.call(CmdRuntime(), "RP_RESOURCES_BASE_CAP=-4"))
        self.call(CmdRuntime(), "RP_RESOURCES_BASE_CAP=40", "RP_RESOURCES_BASE_CAP = 40")
        self.assertEqual(runtime.get("RP_RESOURCES_BASE_CAP"), 40)
        self.call(CmdRuntime(), "/reset RP_RESOURCES_BASE_CAP")
        self.assertEqual(runtime.get("RP_RESOURCES_BASE_CAP"), 30)
