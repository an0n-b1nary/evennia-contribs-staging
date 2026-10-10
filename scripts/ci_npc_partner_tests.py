# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Copied into a disposable host by ci_run_npc_tests.py."""

from unittest import skipUnless

from django.apps import apps
from django.test import override_settings
from evennia.utils.test_resources import BaseEvenniaCommandTest
from evennia_npcs import services as svc
from evennia_npcs.commands import CmdNPCPose, NPCCmdSet
from evennia_npcs.models import NPCSceneAppearance, PlotNPCLink

from evennia_rp_rules.ruleset import get_ruleset


@override_settings(
    NPCS_REVEALED=True,
    NPCS_FROZEN=False,
    NPCS_TYPECLASS="evennia_npcs.typeclasses.NPCCharacter",
    DEFAULT_HOME="#1",
)
class NPCPartnerSeams(BaseEvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.stat = next(iter(get_ruleset().stats.values()))
        self.rating = self.stat.scale.rungs[0].key
        self.blueprint = svc.create_blueprint(
            self.char1, "Guest", "template", stat_block={self.stat.key: self.rating}
        )
        self.record = svc.spawn(self.char1, self.blueprint)
        self.npc = svc.control(self.char1, self.record)

    def test_command_import_and_attributed_portrayal_in_every_profile(self):
        self.assertTrue(NPCCmdSet().get("+npc"))
        self.call(CmdNPCPose(), "bows.", f"Guest (NPC, played by {self.char1.key}) bows.")
        self.assertEqual(self.npc.get_rating(self.stat.key).rung.key, self.rating)

    @skipUnless(apps.is_installed("evennia_scenes"), "scenes absent")
    def test_real_scene_capture_survives_object_deletion(self):
        from evennia_scenes.models import LogEntry, Scene

        scene = Scene.objects.create(title="Cameo", creator=self.char1, room=self.room1)
        self.room1.active_scene_id = scene.pk
        svc.portray(self.char1, "bows")
        self.assertIn("played by", LogEntry.objects.get(scene=scene).content)
        svc.despawn(self.char1, self.record)
        self.assertTrue(
            NPCSceneAppearance.objects.filter(spawn=self.record, scene_id=scene.pk).exists()
        )

    @skipUnless(not apps.is_installed("evennia_scenes"), "scenes present")
    def test_scene_absence_keeps_portrayal_and_history(self):
        svc.portray(self.char1, "bows")
        svc.despawn(self.char1, self.record)
        self.assertTrue(svc.history(self.char1, self.blueprint))

    @skipUnless(apps.is_installed("evennia_plots"), "plots absent")
    def test_real_plot_content_and_cleanup(self):
        from evennia_plots.models import PlotThread

        thread = PlotThread.objects.create(
            plot_number=1, name="Cameo", creator=self.char1, status="active"
        )
        svc.link_plot(self.char1, self.blueprint, thread.pk)
        self.assertEqual(thread._compute_bonus_xp(), 1)
        thread.delete()
        self.assertFalse(PlotNPCLink.objects.exists())

    @skipUnless(not apps.is_installed("evennia_plots"), "plots present")
    def test_plot_absence_refuses_linking_only(self):
        with self.assertRaises(svc.NPCError):
            svc.link_plot(self.char1, self.blueprint, 1)
        svc.portray(self.char1, "bows")

    @skipUnless(apps.is_installed("evennia_rp_contest"), "contest absent")
    def test_real_contest_command_uses_npc_identity_and_stats(self):
        from evennia_npcs.commands import contest_command
        from evennia_rp_contest.models import CheckRecord

        self.call(
            contest_command()(), self.stat.key, f"Guest (NPC, played by {self.char1.key}) tests"
        )
        self.assertEqual(CheckRecord.objects.latest("pk").character_id, self.npc.pk)

    @skipUnless(not apps.is_installed("evennia_rp_contest"), "contest present")
    def test_contest_absence_does_not_import_or_register_command(self):
        self.assertIsNone(NPCCmdSet().get("+test"))
