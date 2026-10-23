# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Patterns through seeded examples, real poses in a logged scene and a concluded thread."""

from unittest import skipUnless

from django.apps import apps
from django.core.management import call_command
from evennia.objects.models import ObjectDB
from evennia.utils.test_resources import EvenniaCommandTest
from evennia_rp_crafting.composition import specifications
from evennia_rp_crafting.errors import CraftingError
from evennia_rp_crafting.models import CraftRecord, Pattern, PatternKnowledge
from typeclasses.characters import Character
from typeclasses.rooms import Room

from world.sandbox import crafting
from world.sandbox.seeding import SeededSandboxMixin


class PatternSeams(SeededSandboxMixin, EvenniaCommandTest):
    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        self.owner = PatternKnowledge.objects.get(pattern__key="market-lettering").character
        self.account2.characters.add(self.char2)
        self.char1.permissions.add("Builder")

    def commands(self):
        from commands.default_cmdsets import CharacterCmdSet

        return {row.key: type(row) for row in CharacterCmdSet().commands}

    def test_seeded_patterns_stamp_hallmarks_and_gate_the_host_allow_list(self):
        self.assertIn("+pattern", self.commands())
        placard = ObjectDB.objects.get(db_key=crafting.PLACARD_NAME)
        record = placard.craft_record
        self.assertEqual(
            record.hallmark, f"Worked in Market Lettering by {self.owner.key} (Scribe)"
        )
        self.assertEqual(record.prose["pattern"]["key"], "market-lettering")
        verbs = [{"key": "readable", "niche": "writing", "configuration": {"text": "Verse."}}]
        if apps.is_installed("evennia_rp_equipment"):
            with self.assertRaisesMessage(CraftingError, "combination is unavailable"):
                specifications("weaving", "wearable", {}, verbs)
            pattern = Pattern.objects.get(key="verse-embroidery")
            specifications("weaving", "wearable", {}, verbs, extra=pattern.combinations)
            scarf = ObjectDB.objects.get(db_key=crafting.SCARF_NAME)
            self.char1.move_to(scarf.location, quiet=True)
            self.assertIn(
                crafting.SCARF_TEXT, self.call(self.commands()["read"](), crafting.SCARF_NAME)
            )
            self.assertIn("Worked in Verse Embroidery", scarf.craft_record.hallmark)
        call_command("seed_sandbox", verbosity=0)
        self.assertEqual(Pattern.objects.filter(key__in=crafting.PATTERNS).count(), 2)
        self.assertTrue(CraftRecord.objects.filter(pk=record.pk).exists())

    @skipUnless(apps.is_installed("evennia_scenes"), "Optional Scenes is absent")
    def test_real_poses_in_a_logged_scene_let_a_student_accept_teaching(self):
        from evennia_scenes.models import Scene, SceneParticipant

        command = self.commands()["+pattern"]
        for character in (self.owner, self.char2):
            character.move_to(self.room1, quiet=True)
        self.call(
            command(),
            "/teach market-lettering = Char2",
            "Teaching needs a logged scene",
            caller=self.owner,
        )
        scene = Scene.objects.create(
            room=self.room1, creator=self.owner, title="A lettering lesson"
        )
        self.room1.active_scene_id = scene.pk
        self.owner.record_pose("traces each stroke of the sign-writer's hand.")
        self.char2.record_pose("copies the letters carefully.")
        self.assertEqual(SceneParticipant.objects.filter(scene=scene, pose_count__gte=1).count(), 2)
        self.call(command(), "/teach market-lettering = Char2", "You offer", caller=self.owner)
        self.call(
            command(),
            "/accept market-lettering",
            f"You learn Market Lettering from {self.owner.key}.",
            caller=self.char2,
        )
        row = PatternKnowledge.objects.get(pattern__key="market-lettering", character=self.char2)
        self.assertEqual((row.taught_by_id, row.teaching_scene_id), (self.owner.pk, scene.pk))
        self.assertIn(
            f"Your lineage: Char2: taught by {self.owner.key} in scene #{scene.pk}",
            self.call(command(), "/info market-lettering", caller=self.char2),
        )

    @skipUnless(apps.is_installed("evennia_plots"), "Optional Plots is absent")
    def test_staff_attached_thread_grants_participants_and_leaves_recovered(self):
        from evennia_plots.models import PlotParticipant, PlotThread

        command = self.commands()["+pattern"]
        self.call(command(), "/create guild-knots = Guild Knots", "Pattern Guild Knots")
        self.call(command(), "/niches guild-knots = weaving", "Guild Knots")
        thread = PlotThread.create_thread("The guild hall", self.char1)
        PlotParticipant.objects.create(
            thread=thread, character=self.char2, character_name=self.char2.key
        )
        self.call(command(), f"/thread guild-knots = {thread.pk}", "Active participants learn")
        self.call(command(), "/info guild-knots", "Unknown Pattern.", caller=self.char2)
        thread.conclude(concluded_by=self.char1)
        pattern = Pattern.objects.get(key="guild-knots")
        self.assertEqual(pattern.stage, "spreading")
        self.assertIn(
            "Your lineage: Char2: recovered in The guild hall",
            self.call(command(), "/info guild-knots", caller=self.char2),
        )

    @skipUnless(apps.is_installed("evennia_jobs"), "Optional Jobs is absent")
    def test_a_player_proposal_through_the_host_form_becomes_a_known_pattern(self):
        from evennia_jobs.models import Job

        request, jobs, pattern = (self.commands()[key] for key in ("+request", "+jobs", "+pattern"))
        self.call(
            request(),
            "/form pattern=Knotted cords",
            "Propose a Pattern: Knotted cords",
            caller=self.char2,
        )
        for answer in (
            "name=Knotted Cords",
            "description=Cords knotted in counting patterns.",
            "origin=Market traders tally with them.",
            "niches=Weaver",
            "recognisable=A run of tally knots.",
            "combination=",
            "reuse=yes",
        ):
            self.call(request(), f"/answer {answer}", None, caller=self.char2)
        self.call(request(), "/submit", None, caller=self.char2)
        job = Job.objects.get(title="Knotted cords")
        self.assertIn(
            "Knotted Cords (knotted-cords), Spreading", self.call(jobs(), str(job.job_number))
        )
        self.call(
            jobs(),
            f"/approve {job.job_number}.1 # Welcome to the market.",
            f"Ticket #{job.job_number}: Approved (revision 1).",
        )
        known = PatternKnowledge.objects.get(pattern__key="knotted-cords")
        self.assertEqual((known.character, known.learned_via), (self.char2, "proposal"))
        self.assertIn(
            "Your lineage: Char2: proposed it.",
            self.call(pattern(), "/info knotted-cords", caller=self.char2),
        )
