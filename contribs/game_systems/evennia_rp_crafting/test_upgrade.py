# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The additive composition migration preserves placeholder craft/use history."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class CompositionUpgradeTests(TransactionTestCase):
    def test_wave_two_populated_upgrade_keeps_fixture_placement_and_value(self):
        old_target = [("evennia_rp_crafting", "0004_wave_two")]
        executor = MigrationExecutor(connection)
        new_target = executor.loader.graph.leaf_nodes("evennia_rp_crafting")
        executor.migrate(old_target)
        try:
            old = executor.loader.project_state(old_target).apps
            niche = old.get_model("evennia_rp_crafting", "NicheDefinition").objects.create(
                key="upgrade-fixtures", name="Fixture maker", behaviours=["installable"]
            )
            record = old.get_model("evennia_rp_crafting", "CraftRecord").objects.create(
                crafter_id=810000,
                crafter_name="Original fixture maker",
                niche=niche,
                niche_name=niche.name,
                behaviour="installable",
                item_id=810001,
                resources_spent={"wood": 2},
                furnishing_weeks="0.4",
                hallmark="Original hallmark",
                prose={"configuration": {"room_line": "Original room line."}},
            )
            placement = old.get_model("evennia_rp_crafting", "FixtureInstallation").objects.create(
                craft_id=record.pk, room_id=810002, installer_id=810000
            )
            before = (
                old.get_model("evennia_rp_crafting", "CraftRecord")
                .objects.filter(pk=record.pk)
                .values()
                .get()
            )
        finally:
            MigrationExecutor(connection).migrate(new_target)
        from .models import CraftRecord, FixtureInstallation, ModificationLayer

        self.assertEqual(CraftRecord.objects.filter(pk=record.pk).values().get(), before)
        self.assertTrue(FixtureInstallation.objects.get(pk=placement.pk).active)
        self.assertFalse(ModificationLayer.objects.filter(target_id=810001).exists())

    def test_populated_upgrade_keeps_original_snapshots_and_consumption(self):
        old_target = [("evennia_rp_crafting", "0002_eventroomlimit_eventuse")]
        executor = MigrationExecutor(connection)
        new_target = executor.loader.graph.leaf_nodes("evennia_rp_crafting")
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
            self.assertEqual(current.pop("furnishing_weeks"), 0)
            self.assertEqual(current, snapshot)
        self.assertTrue(EventUse.objects.filter(craft_id=ids[-1]).exists())
        readable = CraftRecord.objects.get(pk=ids[0])
        self.assertEqual(readable.lifecycle, "carried")
        self.assertEqual(readable.verb_data[0]["configuration"]["text"], "Old text.")

    def test_populated_page_upgrade_preserves_printed_pages_without_creating_authorship(self):
        old_target = [
            ("evennia_rp_crafting", "0005_companionstate_modificationoffer_modificationlayer")
        ]
        executor = MigrationExecutor(connection)
        new_target = executor.loader.graph.leaf_nodes("evennia_rp_crafting")
        executor.migrate(old_target)
        try:
            old = executor.loader.project_state(old_target).apps
            niche = old.get_model("evennia_rp_crafting", "NicheDefinition").objects.create(
                key="upgrade-pages", name="Scribe", behaviours=["readable"]
            )
            record = old.get_model("evennia_rp_crafting", "CraftRecord").objects.create(
                crafter_id=820000,
                crafter_name="Original writer",
                niche=niche,
                niche_name=niche.name,
                behaviour="carried",
                item_id=820001,
                hallmark="Original hallmark",
                verbs=[
                    {
                        "key": "readable",
                        "niche": niche.key,
                        "configuration": {"pages": [{"title": "One", "text": "Original page."}]},
                    }
                ],
            )
            before = (
                old.get_model("evennia_rp_crafting", "CraftRecord")
                .objects.filter(pk=record.pk)
                .values()
                .get()
            )
        finally:
            MigrationExecutor(connection).migrate(new_target)
        from .models import CraftRecord, JournalRevision, ReadableEdition

        self.assertEqual(CraftRecord.objects.filter(pk=record.pk).values().get(), before)
        self.assertFalse(JournalRevision.objects.exists())
        self.assertFalse(ReadableEdition.objects.exists())

    def test_pattern_upgrade_keeps_letters_and_records_without_inventing_knowledge(self):
        old_target = [("evennia_rp_crafting", "0007_letterstate")]
        executor = MigrationExecutor(connection)
        new_target = executor.loader.graph.leaf_nodes("evennia_rp_crafting")
        executor.migrate(old_target)
        try:
            old = executor.loader.project_state(old_target).apps
            niche = old.get_model("evennia_rp_crafting", "NicheDefinition").objects.create(
                key="upgrade-letters", name="Letter writer", behaviours=["readable"]
            )
            record = old.get_model("evennia_rp_crafting", "CraftRecord").objects.create(
                crafter_id=820000,
                crafter_name="Original writer",
                niche=niche,
                niche_name=niche.name,
                behaviour="carried",
                item_id=820001,
                resources_spent={"wood": 1},
                hallmark="Made by Original writer (Letter writer)",
                prose={"configuration": {}, "facets": {"letter": {"addressee": "Keeper"}}},
            )
            letter = old.get_model("evennia_rp_crafting", "LetterState").objects.create(
                craft_id=record.pk, addressee="Keeper", seal_number=1
            )
            before = (
                old.get_model("evennia_rp_crafting", "CraftRecord")
                .objects.filter(pk=record.pk)
                .values()
                .get()
            )
        finally:
            MigrationExecutor(connection).migrate(new_target)
        from .models import CraftRecord, LetterState, Pattern, PatternKnowledge

        self.assertEqual(CraftRecord.objects.filter(pk=record.pk).values().get(), before)
        self.assertEqual(LetterState.objects.get(pk=letter.pk).seal_number, 1)
        self.assertFalse(Pattern.objects.exists() or PatternKnowledge.objects.exists())

    def test_proposal_upgrade_keeps_patterns_and_lineage_unproposed(self):
        old_target = [("evennia_rp_crafting", "0008_patterns")]
        executor = MigrationExecutor(connection)
        new_target = executor.loader.graph.leaf_nodes("evennia_rp_crafting")
        executor.migrate(old_target)
        try:
            from django.utils import timezone
            from evennia.utils.create import create_object

            character = create_object("evennia.objects.objects.DefaultCharacter", key="Knower")
            old = executor.loader.project_state(old_target).apps
            pattern = old.get_model("evennia_rp_crafting", "Pattern").objects.create(
                key="old-pattern",
                name="Old Pattern",
                niches=["upgrade-letters"],
                stage="spreading",
                stage_changed_at=timezone.now(),
            )
            row = old.get_model("evennia_rp_crafting", "PatternKnowledge").objects.create(
                pattern=pattern,
                character_id=character.pk,
                character_name=character.key,
                learned_via="staff",
            )
        finally:
            MigrationExecutor(connection).migrate(new_target)
        from .models import Pattern, PatternKnowledge

        upgraded = Pattern.objects.get(pk=pattern.pk)
        self.assertEqual((upgraded.stage, upgraded.proposal_submission_id), ("spreading", None))
        self.assertEqual(PatternKnowledge.objects.get(pk=row.pk).learned_via, "staff")
