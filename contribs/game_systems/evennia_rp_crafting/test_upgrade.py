# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The additive composition migration preserves placeholder craft/use history."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class CompositionUpgradeTests(TransactionTestCase):
    def test_populated_upgrade_keeps_original_snapshots_and_consumption(self):
        old_target = [("evennia_rp_crafting", "0002_eventroomlimit_eventuse")]
        new_target = [("evennia_rp_crafting", "0003_composition")]
        executor = MigrationExecutor(connection)
        executor.migrate(old_target)
        try:
            old = executor.loader.project_state(old_target).apps
            niche = old.get_model("evennia_rp_crafting", "NicheDefinition").objects.create(
                key="upgrade-scribe",
                name="Original Scribe",
                behaviours=["readable"],
            )
            records = old.get_model("evennia_rp_crafting", "CraftRecord")
            ids = []
            for item_id, kind in enumerate(
                ("readable", "wearable", "consumable", "broadcast"), 800001
            ):
                row = records.objects.create(
                    crafter_id=800000,
                    crafter_name="Original maker",
                    niche=niche,
                    niche_name="Original Scribe",
                    behaviour=kind,
                    item_id=item_id,
                    resources_spent={"wood": 1},
                    hallmark="Made by Original maker",
                    prose={"configuration": {"text": "Old text.", "beats": ["Old beat."]}},
                )
                ids.append(row.pk)
            old.get_model("evennia_rp_crafting", "EventUse").objects.create(
                craft_id=ids[-1],
                actor_id=800000,
                actor_name="Original maker",
                room_id=800002,
            )
            before = list(records.objects.filter(pk__in=ids).values())
        finally:
            MigrationExecutor(connection).migrate(new_target)

        from .models import CraftRecord, EventUse

        for snapshot in before:
            current = CraftRecord.objects.filter(pk=snapshot["id"]).values().get()
            self.assertEqual(current.pop("verbs"), [])
            self.assertEqual(current.pop("contributors"), [])
            self.assertEqual(current, snapshot)
        self.assertTrue(EventUse.objects.filter(craft_id=ids[-1]).exists())
        readable = CraftRecord.objects.get(pk=ids[0])
        self.assertEqual(readable.lifecycle, "carried")
        self.assertEqual(readable.verb_data[0]["configuration"]["text"], "Old text.")
