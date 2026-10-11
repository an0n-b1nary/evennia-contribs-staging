"""Real NPC seams under the reference game's installed partner registry."""

from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.core.management import call_command
from django.test import override_settings
from evennia.utils.test_resources import BaseEvenniaCommandTest, EvenniaTest
from evennia_npcs import services as svc
from evennia_npcs.models import NPCSceneAppearance, PlotNPCLink
from typeclasses.characters import Character
from typeclasses.npcs import NPC
from typeclasses.rooms import Room


@override_settings(NPCS_REVEALED=True, NPCS_FROZEN=False)
class NPCSeams(EvenniaTest):
    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        self.blueprint = svc.create_blueprint(
            self.char1, "Visiting NPC", "template", stat_block={"presence": "B"}
        )
        self.spawn = svc.spawn(self.char1, self.blueprint)
        self.npc = self.spawn.spawned_object
        svc.control(self.char1, self.spawn)

    def test_host_mro_and_npc_has_real_rules_subject(self):
        from evennia_rp_rules.subjects import get_subject

        self.assertIsInstance(self.npc, NPC)
        self.assertEqual(get_subject(self.npc).get_rating("presence").display(), "B")

    def test_host_npc_login_skips_economy_and_xp_hooks(self):
        with patch.object(Character, "at_post_puppet") as pc_login:
            self.npc.at_post_puppet()
        pc_login.assert_not_called()

    @skipUnless(apps.is_installed("evennia_rptracker"), "tracker absent")
    def test_real_tracker_excludes_npc_as_owner_and_partner(self):
        import time

        from evennia_rptracker import tracker

        tracker._active_sessions.clear()
        self.npc.last_pose_time = time.time()
        tracker.record_rp_activity(self.npc, self.room1)
        self.assertIsNone(tracker.get_session_state(self.npc.pk))
        self.assertNotIn(
            self.npc.pk, tracker._get_active_partner_ids(self.char1, self.room1, time.time())
        )

    @skipUnless(apps.is_installed("evennia_scenes"), "scenes absent")
    def test_scene_history_survives_despawn_and_honors_current_privacy(self):
        from evennia_scenes.models import LogEntry, Scene, SceneParticipant

        scene = Scene.objects.create(
            title="A private cameo", creator=self.char1, room=self.room1, privacy="public"
        )
        self.room1.active_scene_id = scene.pk
        svc.portray(self.char1, "bows")
        self.assertEqual(LogEntry.objects.filter(scene=scene).count(), 1)
        self.assertIn(f"played by {self.char1.key}", LogEntry.objects.get(scene=scene).content)
        self.assertTrue(
            NPCSceneAppearance.objects.filter(spawn=self.spawn, scene_id=scene.pk).exists()
        )
        svc.despawn(self.char1, self.spawn)
        self.assertIn(scene.title, "\n".join(svc.history(self.char2, self.blueprint)))
        scene.privacy = "view_private"
        scene.save(update_fields=["privacy"])
        with patch.object(svc, "is_staff", return_value=False):
            self.assertNotIn(scene.title, "\n".join(svc.history(self.char2, self.blueprint)))
            SceneParticipant.objects.create(
                scene=scene, character=self.char2, character_name=self.char2.key, is_invited=True
            )
            self.assertIn(scene.title, "\n".join(svc.history(self.char2, self.blueprint)))
        scene.delete()
        self.assertFalse(NPCSceneAppearance.objects.filter(spawn=self.spawn).exists())

    @skipUnless(apps.is_installed("evennia_scenes"), "scenes absent")
    def test_npc_cannot_bypass_scene_invitation(self):
        from evennia_scenes.models import Scene, SceneParticipant

        scene = Scene.objects.create(
            title="Invite-only", creator=self.char2, room=self.room1, privacy="pose_private"
        )
        self.room1.active_scene_id = scene.pk
        with patch.object(svc, "is_staff", return_value=False):
            with self.assertRaisesMessage(svc.NPCError, "invite your character"):
                svc.portray(self.char1, "interrupts")
            SceneParticipant.objects.create(scene=scene, character=self.char1, is_invited=True)
            svc.portray(self.char1, "bows")

    @skipUnless(apps.is_installed("evennia_plots"), "plots absent")
    def test_plot_npc_is_creative_content_without_duplicate_bonus(self):
        from evennia_plots.models import PlotBoardLink, PlotThread

        thread = PlotThread.objects.create(
            plot_number=101,
            name="A visitor arrives",
            creator=self.char1,
            status="active",
            privacy="public",
        )
        svc.link_plot(self.char1, self.blueprint, thread.plot_number)
        self.assertEqual(thread._compute_bonus_xp(), 1)
        PlotBoardLink.objects.create(thread=thread, post_id=999, is_ic_post=True)
        self.assertEqual(thread._compute_bonus_xp(), 1)
        thread.delete()
        self.assertFalse(PlotNPCLink.objects.filter(blueprint=self.blueprint).exists())

    @skipUnless(apps.is_installed("evennia_plots"), "plots absent")
    def test_private_plot_and_npc_permissions_both_checked(self):
        from evennia_plots.models import PlotThread

        thread = PlotThread.objects.create(
            plot_number=101,
            name="Hidden thread",
            creator=self.char2,
            status="active",
            privacy="private",
        )
        with (
            patch("evennia_plots.models.is_plot_staff", return_value=False),
            self.assertRaises(svc.NPCError),
        ):
            svc.link_plot(self.char1, self.blueprint, thread.plot_number)

    @skipUnless(not apps.is_installed("evennia_plots"), "plots present")
    def test_absent_plots_refuses_linking_but_not_portrayal(self):
        with self.assertRaisesMessage(svc.NPCError, "not installed"):
            svc.link_plot(self.char1, self.blueprint, 1)
        self.assertIn("played by", svc.portray(self.char1, "waves"))

    @skipUnless(not apps.is_installed("evennia_scenes"), "scenes present")
    def test_absent_scenes_portrayal_and_history_still_work(self):
        self.assertIn("played by", svc.portray(self.char1, "waves"))
        svc.despawn(self.char1, self.spawn)
        self.assertIn("despawned", "\n".join(svc.history(self.char1, self.blueprint)))


@override_settings(NPCS_REVEALED=True, NPCS_FROZEN=False)
class NPCCommandSeams(BaseEvenniaCommandTest):
    character_typeclass = Character
    room_typeclass = Room

    @skipUnless(apps.is_installed("evennia_rp_contest"), "contest absent")
    def test_contest_uses_npc_stats_without_pc_sheet_or_rewards(self):
        from evennia_npcs.commands import contest_command
        from evennia_rp_contest.models import CheckRecord

        blueprint = svc.create_blueprint(
            self.char1, "Test visitor", "template", stat_block={"presence": "A"}
        )
        spawn = svc.spawn(self.char1, blueprint)
        svc.control(self.char1, spawn)
        with patch("world.sandbox.glue.on_pose_recorded") as pc_pose:
            self.call(
                contest_command()(),
                "presence",
                f"Test visitor (NPC, played by {self.char1.key}) tests Presence",
                caller=self.char1,
            )
        pc_pose.assert_not_called()
        check = CheckRecord.objects.latest("pk")
        self.assertEqual(check.character_id, spawn.spawned_object_id)
        self.assertEqual(check.rating_display, "A")

    @override_settings(NPCS_ALLOW_FULL_PUPPET=True)
    def test_full_puppet_real_session_round_trip_and_revocation(self):
        self.account.puppet_object(self.session, self.char1)
        blueprint = svc.create_blueprint(self.char1, "Full visitor", "unique")
        spawn = svc.spawn(self.char1, blueprint)
        npc = svc.full_puppet(self.char1, spawn, self.session)
        self.assertEqual(self.session.puppet, npc)
        self.assertEqual(self.char1.location, self.room1)
        self.assertIsNone(npc.ndb.npc_puppet_token)
        self.assertFalse(npc.access(self.account, "puppet"))
        with self.settings(NPCS_REVEALED=False, NPCS_FROZEN=True):
            svc.return_from_full(npc, self.session)
        self.assertEqual(self.session.puppet, self.char1)
        self.assertEqual(npc.location, self.room1)
        svc.release(self.char1)
        svc.permit(self.char1, blueprint, self.char2)
        svc.control(self.char2, spawn)

    def test_reference_seed_populates_npcs_idempotently(self):
        from evennia_npcs.models import NPCBlueprint, NPCSpawnRecord

        from world.sandbox import content

        for _ in range(2):
            call_command("seed_sandbox", verbosity=0)
        self.assertEqual(
            NPCBlueprint.objects.filter(name__in=[spec["name"] for spec in content.NPCS]).count(), 2
        )
        self.assertEqual(
            NPCSpawnRecord.objects.filter(
                blueprint__name__in=[spec["name"] for spec in content.NPCS], despawned_at=None
            ).count(),
            2,
        )

    @override_settings(NPCS_ALLOW_FULL_PUPPET=True)
    def test_revoke_returns_full_puppet_to_original_character(self):
        self.account.puppet_object(self.session, self.char1)
        blueprint = svc.create_blueprint(self.char2, "Shared full visitor", "unique")
        svc.permit(self.char2, blueprint, self.char1)
        spawn = svc.spawn(self.char1, blueprint)
        svc.full_puppet(self.char1, spawn, self.session)
        svc.permit(self.char2, blueprint, self.char1, revoke=True)
        self.assertEqual(self.session.puppet, self.char1)

    @override_settings(NPCS_ALLOW_FULL_PUPPET=True)
    def test_direct_npc_deletion_returns_full_puppet(self):
        self.account.puppet_object(self.session, self.char1)
        blueprint = svc.create_blueprint(self.char1, "Deleted full visitor", "unique")
        npc = svc.full_puppet(self.char1, svc.spawn(self.char1, blueprint), self.session)
        npc.delete()
        self.assertEqual(self.session.puppet, self.char1)

    @override_settings(NPCS_ALLOW_FULL_PUPPET=True)
    def test_deleted_original_character_returns_to_ooc(self):
        self.account.puppet_object(self.session, self.char1)
        blueprint = svc.create_blueprint(self.char1, "Orphan full visitor", "unique")
        npc = svc.full_puppet(self.char1, svc.spawn(self.char1, blueprint), self.session)
        self.char1.delete()
        svc.return_from_full(npc, self.session)
        self.assertIsNone(self.session.puppet)

    def test_npc_cmdset_excludes_pc_build_and_economy_commands(self):
        blueprint = svc.create_blueprint(self.char1, "Restricted visitor", "template")
        npc = svc.spawn(self.char1, blueprint).spawned_object
        npc.cmdset.update()
        for name in ("+balance", "+spend", "+craft", "+resources", "+sheet", "get", "give"):
            self.assertIsNone(npc.cmdset.current.get(name), name)
        self.assertIsNotNone(npc.cmdset.current.get("+npc"))

    def test_refused_direct_ic_keeps_real_login_character(self):
        from evennia_npcs.commands import CmdNPCIC

        self.account.characters.add(self.char1)
        self.char1.permissions.clear()
        self.account.permissions.clear()
        self.account.db._quell = True
        self.char1.locks.add(f"puppet:pid({self.account.pk})")
        self.account.puppet_object(self.session, self.char1)
        blueprint = svc.create_blueprint(self.char1, "Refused visitor", "template")
        npc = svc.spawn(self.char1, blueprint).spawned_object
        self.call(CmdNPCIC(), f"#{npc.pk}", "You don't have permission", caller=self.account)
        self.assertEqual(self.session.puppet, self.char1)
        self.assertEqual(self.account.db._last_puppet, self.char1)
        svc.despawn(self.char1, svc.record_for(npc))
        self.assertEqual(self.account.db._last_puppet, self.char1)

    @override_settings(NPCS_ALLOW_FULL_PUPPET=True)
    def test_full_puppet_ooc_keeps_real_login_character(self):
        from evennia.commands.default.account import CmdOOC

        self.account.characters.add(self.char1)
        self.account.puppet_object(self.session, self.char1)
        blueprint = svc.create_blueprint(self.char1, "OOC visitor", "template")
        npc = svc.full_puppet(self.char1, svc.spawn(self.char1, blueprint), self.session)
        self.call(CmdOOC(), "", "You go OOC.", caller=self.account)
        self.assertIsNone(self.session.puppet)
        self.assertEqual(self.account.db._last_puppet, self.char1)
        self.assertEqual(npc.location, self.room1)

    @skipUnless(apps.is_installed("evennia_guides"), "guides absent")
    def test_npc_guide_renders_and_runtime_hide_returns_404(self):
        from django.test import Client

        from evennia_links import runtime

        response = Client().get("/guide/npcs/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Playing NPCs")
        self.assertContains(response, "+npc/puppet")
        runtime.set("NPCS_REVEALED", False)
        self.assertEqual(Client().get("/guide/npcs/").status_code, 404)
