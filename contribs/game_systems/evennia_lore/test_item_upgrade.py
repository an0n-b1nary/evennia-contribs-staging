# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""A populated lore database gains item records without rewriting knowledge."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from evennia.utils.test_resources import EvenniaTestMixin


class ItemUpgradeTests(EvenniaTestMixin, TransactionTestCase):
    def test_populated_lore_upgrade_preserves_acquisition_and_entry_layers(self):
        old_target = [("evennia_lore", "0004_affirm_reviewed_entries")]
        executor = MigrationExecutor(connection)
        target = executor.loader.graph.leaf_nodes("evennia_lore")
        executor.migrate(old_target)
        try:
            old = executor.loader.project_state(old_target).apps
            lore = old.get_model("evennia_lore", "LoreEntry").objects.create(
                entry_number=91000,
                title="Existing legend",
                body="Old IC account.",
                kind="legend",
                accuracy="open",
                sealed_notes="Existing sealed explanation.",
                author_id=self.char1.pk,
                author_name=self.char1.key,
                status="published",
            )
            row = old.get_model("evennia_lore", "LoreAcquisition").objects.create(
                entry=lore,
                character_id=self.char2.pk,
                character_name=self.char2.key,
                source="shared",
            )
            before = (
                old.get_model("evennia_lore", "LoreEntry").objects.filter(pk=lore.pk).values().get()
            )
        finally:
            MigrationExecutor(connection).migrate(target)
        from .models import LoreAcquisition, LoreEntry, LoreTomeRecord

        self.assertEqual(LoreEntry.objects.filter(pk=lore.pk).values().get(), before)
        self.assertEqual(LoreAcquisition.objects.get(pk=row.pk).source, "shared")
        self.assertFalse(LoreTomeRecord.objects.exists())
