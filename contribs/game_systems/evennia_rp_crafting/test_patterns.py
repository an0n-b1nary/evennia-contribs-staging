# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Pattern knowledge, gated combinations, forward-only stages, teaching and thread grants."""

from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.utils import timezone
from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaCommandTest

from . import conf, patterns
from .commands import DRAFT_KEY, CmdCraft, CmdPattern
from .errors import CraftingError
from .models import (
    CraftRecord,
    NicheDefinition,
    Pattern,
    PatternKnowledge,
    PatternOffer,
    PatternStageChange,
)
from .tests import CraftingFixture

HAS_SCENES = apps.is_installed("evennia_scenes")
HAS_PLOTS = apps.is_installed("evennia_plots")
# Readable + activatable is only open to crafts worked in the Pattern under test.
GATED = conf.DEFAULT_COMBINATIONS | {"carried": [["readable"], ["activatable"]]}
MODES = {"modes": {"play": ["A soft tune plays."]}}


class PatternFixture(CraftingFixture, EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.staff = create_object("evennia.objects.objects.DefaultCharacter", key="Keeper")
        self.staff.permissions.add("Builder")
        self.unlock()
        self.pattern = patterns.create(self.staff, "market-lettering", "Market Lettering")
        patterns.edit(self.staff, self.pattern, niches=["writing-0"])

    def learn(self, character=None, pattern=None):
        return patterns.grant(self.staff, pattern or self.pattern, character or self.char1)[0]

    def spreading(self, pattern=None):
        return patterns.advance(self.staff, pattern or self.pattern)


class PatternCraftTests(PatternFixture):
    def test_hallmark_snapshot_survives_rename_and_needs_knowledge(self):
        before = self.held()
        for problem in ("market-lettering", "unknown-pattern"):
            with self.subTest(problem=problem), self.assertRaises(CraftingError):
                self.book(pattern=problem)
        self.assertEqual(self.held(), before)
        self.learn()
        item = self.book(pattern="Market lettering")
        record = item.craft_record
        self.assertEqual(record.hallmark, "Worked in Market Lettering by Char (Scribe 0)")
        self.assertEqual(
            record.prose["pattern"], {"key": "market-lettering", "name": "Market Lettering"}
        )
        patterns.edit(self.staff, self.pattern, name="Old Market Lettering")
        record.refresh_from_db()
        self.assertEqual(
            item.get_display_provenance(), "Worked in Market Lettering by Char (Scribe 0)"
        )
        self.assertIn("Made by Char", self.book().craft_record.hallmark)
        self.assertEqual(self.held(), before - 2)

    def test_niche_and_archive_rules_refuse_without_spending(self):
        self.learn()
        self.unlock("writing-1")
        before = self.held()
        with self.assertRaises(CraftingError):
            self.book(key="writing-1", pattern="market-lettering")
        patterns.edit(self.staff, self.pattern, archived=True)
        with self.assertRaises(CraftingError):
            self.book(pattern="market-lettering")
        with self.assertRaises(CraftingError):
            patterns.grant(self.staff, self.pattern, self.char2)
        self.assertEqual(self.held(), before)
        self.assertEqual(CraftRecord.objects.count(), 0)

    @override_settings(RP_CRAFTING_COMBINATIONS=GATED)
    def test_gated_combination_opens_only_for_crafts_worked_in_the_pattern(self):
        NicheDefinition.objects.create(
            key="music",
            name="Musician",
            behaviours=["activatable"],
            input_categories=["materials", "essences"],
            unlock_resources={"materials": 3},
        )
        self.unlock("music")
        verbs = [{"key": "activatable", "niche": "music", "configuration": MODES}]
        params = {"verbs": verbs, "selected": {"wood": 2}}
        with self.assertRaisesMessage(CraftingError, "combination is unavailable"):
            self.book(**params)
        patterns.edit(
            self.staff, self.pattern, combinations={"carried": [["activatable", "readable"]]}
        )
        self.learn()
        with self.assertRaisesMessage(CraftingError, "combination is unavailable"):
            self.book(**params)
        item = self.book(pattern="market-lettering", **params)
        record = item.craft_record
        self.assertEqual(record.behaviour_keys, ["carried", "activatable", "readable"])
        self.assertEqual(record.hallmark, "Worked in Market Lettering by Char (Musician, Scribe 0)")
        self.assertEqual(item.read(self.char1), "A record of the road.")
        patterns.edit(self.staff, self.pattern, combinations={})
        self.assertEqual(
            CraftRecord.objects.get(pk=record.pk).behaviour_keys, record.behaviour_keys
        )

    def test_combinations_validate_complete_lifecycle_and_verb_sets(self):
        for value in (
            {"readable": [[]]},
            {"carried": ["readable"]},
            {"carried": [["readable", "readable"]]},
            {"carried": [["wearable"]]},
            {"nonsense": [[]]},
            [],
        ):
            with self.subTest(value=value), self.assertRaises(CraftingError):
                patterns.edit(self.staff, self.pattern, combinations=value)
        with self.assertRaises(CraftingError):
            patterns.edit(self.staff, self.pattern, niches=["no-such-niche"])
        self.assertEqual(
            patterns.validate_combinations({"carried": [["readable", "activatable"]]}),
            {"carried": [["activatable", "readable"]]},
        )

    def test_copies_never_inherit_the_source_pattern(self):
        from .readables import copy_book

        self.learn()
        source = self.book(pattern="market-lettering")
        copy = copy_book(self.char1, source, "writing-0", "Copy", "A copy.", {"wood": 1})
        self.assertNotIn("pattern", copy.craft_record.prose)
        self.assertIn("Made by Char", copy.craft_record.hallmark)

    @override_settings(RP_CRAFTING_COMBINATIONS=GATED)
    def test_draft_switches_preview_the_hallmark_and_gate_partial_verbs(self):
        NicheDefinition.objects.create(
            key="music",
            name="Musician",
            behaviours=["activatable"],
            input_categories=["materials", "essences"],
            unlock_resources={"materials": 3},
        )
        self.unlock("music")
        patterns.edit(
            self.staff, self.pattern, combinations={"carried": [["activatable", "readable"]]}
        )
        self.call(CmdCraft(), "/new writing-0/readable = Song book", "Craft draft saved")
        self.call(CmdCraft(), "/desc Songs.", "Craft draft saved")
        self.call(CmdCraft(), "/text Verses.", "Craft draft saved")
        self.call(CmdCraft(), "/pattern market-lettering", "You don't know that Pattern.")
        self.call(CmdCraft(), "/verb music/activatable", "That lifecycle and verb combination")
        self.learn()
        self.call(CmdCraft(), "/pattern Market Lettering", "Craft draft saved")
        self.call(CmdCraft(), "/verb music/activatable", "Craft draft saved")
        self.call(CmdCraft(), "/mode play = A soft tune plays.", "Craft draft saved")
        self.assertIn("Hallmark (OOC): Worked in Market Lettering", self.call(CmdCraft(), ""))
        self.call(CmdCraft(), "/unpattern", "Craft draft saved")
        self.call(CmdCraft(), "", "That lifecycle and verb combination")
        self.call(CmdCraft(), "/unpattern", "The draft names no Pattern.")
        self.call(CmdCraft(), "/pattern market-lettering", "Craft draft saved")
        self.call(CmdCraft(), "/resources 2 wood", "Craft draft saved")
        self.call(CmdCraft(), "/finish", "You craft Song book. Hallmark (OOC): Worked in")
        self.assertFalse(self.char1.attributes.has(DRAFT_KEY))


class PatternStageTests(PatternFixture):
    def test_staff_advance_is_logged_forward_only(self):
        with self.assertRaises(CraftingError):
            patterns.advance(self.char1, self.pattern)
        self.spreading()
        patterns.advance(self.staff, self.pattern, "Festival")
        with self.assertRaisesMessage(CraftingError, "already Common"):
            self.spreading()
        changes = list(PatternStageChange.objects.values_list("from_stage", "to_stage", "reason"))
        self.assertEqual(
            changes,
            [("recovered", "spreading", "Staff advance"), ("spreading", "common", "Festival")],
        )
        with self.assertRaises(ValidationError):
            PatternStageChange.objects.first().delete()

    def test_backstop_clock_reads_the_current_tuning(self):
        self.spreading()
        Pattern.objects.filter(pk=self.pattern.pk).update(
            stage_changed_at=timezone.now() - timedelta(days=10)
        )
        self.pattern.refresh_from_db()
        with override_settings(RP_CRAFTING_PATTERN_COMMON_DAYS=42):
            self.assertEqual(patterns.current_stage(self.pattern), "spreading")
        with override_settings(RP_CRAFTING_PATTERN_COMMON_DAYS=7):
            self.assertEqual(patterns.current_stage(self.pattern), "common")
        with override_settings(RP_CRAFTING_PATTERN_COMMON_DAYS=42):
            self.assertEqual(patterns.current_stage(self.pattern), "common")
        self.assertEqual(PatternStageChange.objects.last().reason, "Backstop clock (7 days)")
        for value in (0, 3651, True, "42"):
            self.assertFalse(conf.days(value))


@skipUnless(HAS_SCENES, "Optional Scenes is absent")
class PatternTeachingTests(PatternFixture):
    def setUp(self):
        super().setUp()
        self.learn()

    def scene(self, *posers, observers=(), status="active", ended=None):
        from evennia_scenes.models import Scene, SceneParticipant

        scene = Scene.objects.create(room=self.room1, creator=self.char1, title="Lesson")
        Scene.objects.filter(pk=scene.pk).update(status=status, ended_at=ended)
        for character in posers:
            SceneParticipant.objects.create(
                scene=scene, character=character, character_name=character.key, pose_count=2
            )
        for character in observers:
            SceneParticipant.objects.create(
                scene=scene,
                character=character,
                character_name=character.key,
                role="observer",
            )
        return scene

    def test_teaching_needs_a_shared_posing_scene_and_acceptance(self):
        self.spreading()
        with self.assertRaisesMessage(CraftingError, "logged scene you both posed in"):
            patterns.offer(self.char1, self.char2, self.pattern)
        self.scene(self.char1, observers=[self.char2])
        with self.assertRaises(CraftingError):
            patterns.offer(self.char1, self.char2, self.pattern)
        old = self.scene(
            self.char1, self.char2, status="closed", ended=timezone.now() - timedelta(days=8)
        )
        with self.assertRaises(CraftingError):
            patterns.offer(self.char1, self.char2, self.pattern)
        with override_settings(RP_CRAFTING_PATTERN_TEACH_DAYS=9):
            patterns.offer(self.char1, self.char2, self.pattern)
            with self.assertRaisesMessage(CraftingError, "already offered"):
                patterns.offer(self.char1, self.char2, self.pattern)
        self.assertFalse(PatternKnowledge.objects.filter(character=self.char2).exists())
        with self.assertRaises(CraftingError):
            patterns.accept(self.char2, self.pattern)
        recent = self.scene(self.char1, self.char2)
        row = patterns.accept(self.char2, self.pattern)
        self.assertEqual((row.learned_via, row.taught_by_id), ("taught", self.char1.pk))
        self.assertEqual(row.teaching_scene_id, recent.pk)
        self.assertNotEqual(old.pk, recent.pk)
        self.assertFalse(PatternOffer.objects.exists())
        self.assertEqual(
            patterns.lineage(row),
            [
                f"Char2: taught by Char in scene #{recent.pk}",
                "Char: granted by staff",
            ],
        )

    def test_recovered_same_account_guest_and_archived_patterns_are_refused(self):
        self.scene(self.char1, self.char2)
        with self.assertRaisesMessage(CraftingError, "Recovered"):
            patterns.offer(self.char1, self.char2, self.pattern)
        self.spreading()
        self.account.characters.add(self.char2)
        with self.assertRaisesMessage(CraftingError, "same account"):
            patterns.offer(self.char1, self.char2, self.pattern)
        self.account.characters.remove(self.char2)
        patterns.offer(self.char1, self.char2, self.pattern)
        patterns.edit(self.staff, self.pattern, archived=True)
        with self.assertRaisesMessage(CraftingError, "archived"):
            patterns.accept(self.char2, self.pattern)
        patterns.edit(self.staff, self.pattern, archived=False)
        patterns.decline(self.char2, self.pattern)
        with self.assertRaises(CraftingError):
            patterns.decline(self.char2, self.pattern)
        self.assertFalse(PatternKnowledge.objects.filter(character=self.char2).exists())

    def test_commands_teach_accept_and_show_own_lineage_only(self):
        self.spreading()
        self.scene(self.char1, self.char2)
        count = PatternOffer.objects.count()
        self.call(CmdPattern(), "/teach Char2=market-lettering")
        self.assertEqual(PatternOffer.objects.count(), count)
        self.call(CmdPattern(), "/teach market-lettering = Char2", "You offer to teach Char2")
        self.assertIn(
            "Char offers to teach you Market Lettering",
            self.call(CmdPattern(), "", caller=self.char2),
        )
        with patch.object(self.char1, "msg") as told:
            self.call(
                CmdPattern(),
                "/accept market-lettering",
                "You learn Market Lettering from Char.",
                caller=self.char2,
            )
        told.assert_called_once_with("Char2 learns Market Lettering from you.")
        info = self.call(CmdPattern(), "/info market-lettering", caller=self.char2)
        self.assertIn("Known by 2 crafter(s).", info)
        self.assertIn("Your lineage: Char2: taught by Char", info)
        self.assertNotIn(
            "lineage", self.call(CmdPattern(), "/info market-lettering", caller=self.staff)
        )
        self.call(CmdPattern(), "/roster market-lettering", "Only staff", caller=self.char2)
        self.assertIn(
            "taught by Char", self.call(CmdPattern(), "/roster market-lettering", caller=self.staff)
        )

    def test_without_scenes_teaching_is_unavailable(self):
        self.spreading()
        with (
            patch.object(patterns.apps, "is_installed", return_value=False),
            self.assertRaisesMessage(CraftingError, "needs evennia-scenes"),
        ):
            patterns.offer(self.char1, self.char2, self.pattern)


@skipUnless(HAS_PLOTS, "Optional Plots is absent")
class PatternThreadTests(PatternFixture):
    def setUp(self):
        super().setUp()
        from evennia_plots.models import PlotParticipant, PlotThread

        self.thread = PlotThread.create_thread("The old hall", self.char2)
        for character, active in ((self.char1, True), (self.char2, False)):
            PlotParticipant.objects.create(
                thread=self.thread,
                character=character,
                character_name=character.key,
                is_active=active,
            )

    def test_conclusion_grants_active_participants_and_leaves_recovered_once(self):
        with self.assertRaises(CraftingError):
            patterns.attach(self.char1, self.pattern, self.thread.pk)
        patterns.attach(self.staff, self.pattern, self.thread.pk)
        with self.assertRaisesMessage(CraftingError, "already grants"):
            patterns.attach(self.staff, self.pattern, self.thread.pk)
        self.pattern.refresh_from_db()
        self.assertEqual(self.pattern.origin_thread_id, self.thread.pk)
        self.thread.conclude(concluded_by=self.char2)
        self.pattern.refresh_from_db()
        self.assertEqual(self.pattern.stage, "spreading")
        row = PatternKnowledge.objects.get(pattern=self.pattern)
        self.assertEqual((row.character_id, row.learned_via), (self.char1.pk, "thread"))
        self.assertEqual(patterns.describe_source(row), "recovered in The old hall")
        patterns.on_concluded(None, self.thread)
        self.assertEqual(PatternKnowledge.objects.count(), 1)
        self.assertEqual(PatternStageChange.objects.count(), 1)
        with self.assertRaises(CraftingError):
            patterns.attach(self.staff, self.pattern, self.thread.pk + 1000)

    def test_later_thread_grants_do_not_reset_the_stage(self):
        from evennia_plots.models import PlotThread

        first = PlotThread.create_thread("An earlier find", self.char2)
        patterns.attach(self.staff, self.pattern, first.pk)
        first.conclude()
        patterns.advance(self.staff, self.pattern)
        patterns.attach(self.staff, self.pattern, self.thread.pk)
        self.thread.conclude()
        self.pattern.refresh_from_db()
        self.assertEqual(self.pattern.stage, "common")
        self.assertTrue(PatternKnowledge.objects.filter(character=self.char1).exists())


class PatternVisibilityTests(PatternFixture):
    def test_unknown_patterns_stay_hidden_and_the_reveal_switch_applies(self):
        self.call(CmdPattern(), "/all", "No Patterns are known yet.")
        self.call(CmdPattern(), "/info market-lettering", "Unknown Pattern.")
        self.assertIn("Market Lettering", self.call(CmdPattern(), "/all", caller=self.staff))
        self.call(CmdPattern(), "/create x = X", "Only staff may manage Patterns.")
        self.learn(self.char2)
        self.assertIn("known by 1", self.call(CmdPattern(), "/all"))
        self.learn()
        with override_settings(RP_CRAFTING_PATTERNS_REVEALED=False):
            self.assertFalse(CmdPattern().access(self.char1))
            with self.assertRaisesMessage(CraftingError, "Patterns are unavailable"):
                self.book(pattern="market-lettering")
            self.assertTrue(CmdPattern().access(self.staff))

    def test_one_verb_edits_reject_old_syntax_and_preserve_stored_alternatives(self):
        original = dict(self.pattern.combinations)
        for args in (
            "/combo market-lettering=carried:readable+activatable",
            "/combo/nope market-lettering/carried=readable",
            "/combo market-lettering/carried=readable+activatable",
        ):
            self.call(CmdPattern(), args, caller=self.staff)
            self.pattern.refresh_from_db()
            self.assertEqual(self.pattern.combinations, original)
        self.call(CmdPattern(), "/CoMb market-lettering/carried=readable", caller=self.staff)
        self.call(CmdPattern(), "/combo market-lettering/carried=activatable", caller=self.staff)
        self.pattern.refresh_from_db()
        self.assertEqual(self.pattern.combinations, {"carried": [["activatable", "readable"]]})
        self.call(CmdPattern(), "/uncombo market-lettering/carried=readable", caller=self.staff)
        self.pattern.refresh_from_db()
        self.assertEqual(self.pattern.combinations, {"carried": [["activatable"]]})
        alternatives = {"carried": [["readable"], ["activatable"]]}
        patterns.edit(self.staff, self.pattern, combinations=alternatives)
        self.call(
            CmdPattern(),
            "/combo market-lettering/carried=readable",
            "This lifecycle has multiple",
            caller=self.staff,
        )
        self.pattern.refresh_from_db()
        self.assertEqual(self.pattern.combinations, alternatives)

    def test_staff_commands_curate_patterns(self):
        staff = {"caller": self.staff}
        self.call(CmdPattern(), "/create Deep-Tuning = Deep Tuning", "Pattern Deep Tuning", **staff)
        self.call(CmdPattern(), "/create deep-tuning = Again", "That Pattern key is taken", **staff)
        self.assertIn(
            "Niches: writing-0, weaving.",
            self.call(CmdPattern(), "/niches deep-tuning = writing-0, weaving", **staff),
        )
        self.call(
            CmdPattern(),
            "/combo deep-tuning/carried = readable",
            "Deep Tuning",
            **staff,
        )
        self.call(CmdPattern(), "/combo deep-tuning/carried = activatable", "Deep Tuning", **staff)
        self.assertIn(
            "carried + activatable + readable",
            self.call(CmdPattern(), "/info deep-tuning", **staff),
        )
        self.call(CmdPattern(), "/uncombo deep-tuning/carried = readable", "Deep Tuning", **staff)
        self.assertIn(
            "hallmark only",
            self.call(CmdPattern(), "/uncombo deep-tuning/carried = activatable", **staff),
        )
        self.call(CmdPattern(), "/grant deep-tuning = Char", "Char learns Deep Tuning.", **staff)
        self.call(CmdPattern(), "/grant deep-tuning = Char", "Char already knows", **staff)
        self.call(
            CmdPattern(),
            "/advance deep-tuning = Festival",
            "Deep Tuning is now Spreading.",
            **staff,
        )
        self.assertIn("[archived]", self.call(CmdPattern(), "/archive deep-tuning", **staff))
        self.call(CmdPattern(), "", "Deep Tuning (deep-tuning)")
