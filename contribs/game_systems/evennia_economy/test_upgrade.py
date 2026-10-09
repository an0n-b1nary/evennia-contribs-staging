# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""A populated 0.1 database upgrades without rewriting journal or income history."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class StallUpgradeTests(TransactionTestCase):
    def test_populated_m2_upgrade_preserves_balances_receipts_and_review_flags(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        old_target = [("evennia_economy", "0001_initial")]
        try:
            executor.migrate(old_target)
            old = executor.loader.project_state(old_target).apps
            character = old.get_model("objects", "ObjectDB").objects.create(
                db_key="Upgrade character"
            )
            old.get_model("evennia_economy", "Purse").objects.create(
                character_id=character.pk, balance=123
            )
            payment = old.get_model("evennia_economy", "UBIPayment").objects.create(
                character_id=character.pk, week="upgrade-week", amount=23
            )
            ledger = old.get_model("evennia_economy", "LedgerEntry")
            first = ledger.objects.create(
                kind="exchange",
                from_id=character.pk,
                from_name="Original snapshot",
                from_accounts=[12],
                assets=[{"kind": "money", "key": "", "quantity": 1}],
            )
            second = ledger.objects.create(
                kind="exchange",
                to_id=character.pk,
                to_accounts=[12],
                assets=[{"kind": "item", "key": "99", "quantity": 1}],
            )
            flag = old.get_model("evennia_economy", "ReviewFlag").objects.create(
                first_entry_id=first.pk,
                second_entry_id=second.pk,
                title="Existing review",
                description="Keep me",
                reviewed=True,
            )
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            new = executor.loader.project_state(latest).apps
            self.assertEqual(
                new.get_model("evennia_economy", "Purse")
                .objects.get(character_id=character.pk)
                .balance,
                123,
            )
            self.assertEqual(
                new.get_model("evennia_economy", "UBIPayment").objects.get(pk=payment.pk).week,
                "upgrade-week",
            )
            kept = new.get_model("evennia_economy", "ReviewFlag").objects.get(pk=flag.pk)
            self.assertEqual(
                (kept.kind, kept.title, kept.reviewed, kept.first_entry_id, kept.second_entry_id),
                ("round_trip", "Existing review", True, first.pk, second.pk),
            )
            self.assertIsNone(kept.event_key)
            self.assertEqual(
                new.get_model("evennia_economy", "LedgerEntry").objects.get(pk=first.pk).from_name,
                "Original snapshot",
            )
            self.assertFalse(new.get_model("evennia_economy", "Storefront").objects.exists())
        finally:
            MigrationExecutor(connection).migrate(latest)
