# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Identity, authorization, durable configuration and lifecycle contracts."""

from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone
from evennia.utils.test_resources import BaseEvenniaCommandTest, EvenniaTest

from evennia_links import runtime
from evennia_rp_rules.ruleset import get_ruleset

from . import services as svc
from .commands import CmdNPC, CmdNPCEmit, CmdNPCPose, CmdNPCSay, CmdNPCSemipose
from .models import (
    NPCBlueprint,
    NPCCombatProfile,
    NPCPermission,
    NPCPermissionRequest,
    NPCSpawnRecord,
)


@override_settings(
    NPCS_REVEALED=True,
    NPCS_FROZEN=False,
    NPCS_TYPECLASS="evennia_npcs.typeclasses.NPCCharacter",
    DEFAULT_HOME="#1",
)
class NPCTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.char1.permissions.clear()
        self.char2.permissions.clear()
        self.account.permissions.clear()
        self.account2.permissions.clear()
        self.account.db._quell = True
        self.account2.db._quell = True
        self.blueprint = svc.create_blueprint(self.char1, "Porter", "unique")

    def spawned(self, *, template=False):
        blueprint = (
            svc.create_blueprint(self.char1, "Extra", "template") if template else self.blueprint
        )
        return svc.spawn(self.char1, blueprint)

    def test_unique_permission_and_template_open_access(self):
        with self.assertRaisesMessage(svc.NPCError, "permission"):
            svc.spawn(self.char2, self.blueprint)
        template = svc.create_blueprint(self.char1, "Guard", "template")
        a, b = svc.spawn(self.char1, template), svc.spawn(self.char2, template)
        self.assertNotEqual(a.spawned_object_id, b.spawned_object_id)
        with self.assertRaises(svc.NPCError):
            svc.edit_blueprint(self.char2, template, description="Mine")

    def test_unique_spawn_database_constraint(self):
        first = self.spawned()
        with self.assertRaisesMessage(svc.NPCError, "already spawned"):
            svc.spawn(self.char1, self.blueprint)
        with self.assertRaises(IntegrityError), transaction.atomic():
            NPCSpawnRecord.objects.create(
                blueprint=self.blueprint,
                unique_blueprint=self.blueprint,
                last_active_at=timezone.now(),
            )
        self.assertEqual(self.blueprint.spawns.count(), 1)
        svc.despawn(self.char1, first)
        self.assertIsNotNone(svc.spawn(self.char1, self.blueprint).spawned_object_id)

    def test_case_insensitive_identity_and_database_constraint(self):
        with self.assertRaises(svc.NPCError):
            svc.create_blueprint(self.char2, "pOrTeR", "template")
        with self.assertRaises(IntegrityError), transaction.atomic():
            NPCBlueprint.objects.create(name="PORTER", kind="unique", creator_name="Someone")

    def test_object_or_npc_cannot_receive_player_permissions(self):
        record = self.spawned()
        for obj in (self.obj1, record.spawned_object):
            with self.subTest(obj=obj), self.assertRaises(svc.NPCError):
                svc.permit(self.char1, self.blueprint, obj)

    def test_stats_validated_against_host_ruleset(self):
        stat = next(iter(get_ruleset().stats.values()))
        rating = stat.scale.rungs[0].key
        svc.edit_blueprint(self.char1, self.blueprint, stat_block={stat.key: rating})
        npc = self.spawned().spawned_object
        self.assertEqual(npc.get_rating(stat.key).rung.key, rating)
        with self.assertRaises(svc.NPCError):
            svc.edit_blueprint(self.char1, self.blueprint, stat_block={"missing_stat": rating})
        with self.assertRaises(svc.NPCError):
            svc.edit_blueprint(self.char1, self.blueprint, stat_block={stat.key: "invalid grade"})

    def test_blueprint_changes_are_live_without_stale_stat_copies(self):
        npc = self.spawned().spawned_object
        stat = next(iter(get_ruleset().stats.values()))
        svc.edit_blueprint(
            self.char1,
            self.blueprint,
            description="New description",
            stat_block={stat.key: stat.scale.rungs[-1].key},
        )
        self.assertEqual(npc.db.desc, "New description")
        self.assertEqual(npc.get_rating(stat.key).rung.key, stat.scale.rungs[-1].key)

    def test_markup_and_control_characters_refused(self):
        for name in ("|rPorter", "<send>Porter", "Porter\nStaff", "Porter\x1b[31m"):
            with self.subTest(name=name), self.assertRaises(svc.NPCError):
                svc.create_blueprint(self.char1, name)

    def test_permission_request_owner_resolution(self):
        request = svc.request_permission(self.char2, self.blueprint, "A cameo")
        with self.assertRaises(svc.NPCError):
            svc.request_permission(self.char2, self.blueprint)
        with self.assertRaises(svc.NPCError):
            svc.resolve_request(self.char2, request.pk, approved=True)
        svc.resolve_request(self.char1, request.pk, approved=True)
        self.assertTrue(svc.can_play(self.char2, self.blueprint))
        with self.assertRaises(svc.NPCError):
            svc.resolve_request(self.char1, request.pk, approved=False)

    def test_denial_is_retained_and_can_be_requested_again(self):
        request = svc.request_permission(self.char2, self.blueprint)
        svc.resolve_request(self.char1, request.pk, approved=False)
        request.refresh_from_db()
        self.assertEqual(request.status, "denied")
        self.assertIsNotNone(request.resolved_at)
        self.assertEqual(svc.request_permission(self.char2, self.blueprint).status, "pending")

    def test_idle_owner_auto_approval_preserves_ownership(self):
        NPCPermission.objects.filter(blueprint=self.blueprint).update(
            granted_at=timezone.now() - timedelta(days=61)
        )
        request = svc.request_permission(self.char2, self.blueprint)
        self.assertEqual(request.status, "auto_approved")
        self.assertTrue(svc.can_play(self.char2, self.blueprint))
        self.assertFalse(svc.can_manage(self.char2, self.blueprint))

    @override_settings(NPCS_IDLE_OWNER_DAYS=None)
    def test_idle_approval_can_be_disabled(self):
        NPCPermission.objects.filter(blueprint=self.blueprint).update(
            granted_at=timezone.now() - timedelta(days=100)
        )
        self.assertEqual(svc.request_permission(self.char2, self.blueprint).status, "pending")

    def test_recent_owner_play_restarts_idle_window(self):
        NPCPermission.objects.filter(blueprint=self.blueprint).update(
            granted_at=timezone.now() - timedelta(days=100)
        )
        self.spawned()
        self.assertEqual(svc.request_permission(self.char2, self.blueprint).status, "pending")

    def test_deleted_owner_does_not_make_unique_open(self):
        self.char1.delete()
        self.assertFalse(svc.can_play(self.char2, self.blueprint))
        self.assertEqual(svc.request_permission(self.char2, self.blueprint).status, "pending")

    def test_transfer_changes_edit_rights_but_preserves_old_player(self):
        svc.transfer(self.char1, self.blueprint, self.char2)
        self.assertTrue(svc.can_manage(self.char2, self.blueprint))
        self.assertFalse(svc.can_manage(self.char1, self.blueprint))
        self.assertTrue(svc.can_play(self.char1, self.blueprint))

    def test_controller_exclusive_and_revoke_releases(self):
        record = self.spawned()
        svc.permit(self.char1, self.blueprint, self.char2)
        svc.control(self.char2, record)
        with self.assertRaises(svc.NPCError):
            svc.control(self.char1, record)
        svc.permit(self.char1, self.blueprint, self.char2, revoke=True)
        self.assertEqual(svc.controlled(self.char2), (None, self.char2))
        svc.control(self.char1, record)

    def test_one_virtual_npc_per_player(self):
        first, second = self.spawned(), self.spawned(template=True)
        svc.control(self.char1, first)
        svc.control(self.char1, second)
        first.refresh_from_db()
        self.assertIsNone(first.controller_id)
        self.assertEqual(svc.controlled(self.char1)[0], second.spawned_object)

    def test_movement_clears_portrayal_and_does_not_fallback_to_pc_pose(self):
        record = self.spawned()
        svc.control(self.char1, record)
        self.char1.location = self.room2
        with self.assertRaisesMessage(svc.NPCError, "location or permission changed"):
            svc.portray(self.char1, "waves")
        record.refresh_from_db()
        self.assertIsNone(record.controller_id)

    def test_remote_control_refused_even_with_play_permission(self):
        record = self.spawned()
        self.char1.location = self.room2
        with self.assertRaises(svc.NPCError):
            svc.control(self.char1, record)

    def test_portrayal_attributes_actor_and_skips_pc_pose_hook(self):
        record = self.spawned()
        svc.control(self.char1, record)
        with patch.object(self.char1, "record_pose", create=True) as record_pc:
            for kind in ("pose", "say", "emit", "semipose"):
                result = svc.portray(self.char1, "waves", pose_type=kind)
                self.assertIn(f"Porter (NPC, played by {self.char1.key})", result)
            record_pc.assert_not_called()

    def test_npc_marker_and_direct_puppeting_denied(self):
        npc = self.spawned().spawned_object
        self.assertTrue(npc.tags.has("npc", category="npc_system"))
        self.assertFalse(npc.access(self.account, "puppet"))
        with self.assertRaises(svc.NPCError):
            npc.at_pre_puppet(self.account, session=self.session)

    @override_settings(NPCS_ALLOW_FULL_PUPPET=False)
    def test_full_puppet_disabled_by_default(self):
        with self.assertRaisesMessage(svc.NPCError, "disabled"):
            svc.full_puppet(self.char1, self.spawned(), self.session)

    @override_settings(NPCS_ALLOW_FULL_PUPPET=True)
    def test_full_puppet_rejects_foreign_session(self):
        with (
            patch.object(self.session, "get_account", return_value=self.account2),
            self.assertRaises(svc.NPCError),
        ):
            svc.full_puppet(self.char1, self.spawned(), self.session)

    def test_single_use_token_checks_session_and_actor(self):
        record = self.spawned()
        npc = svc.control(self.char1, record)
        npc.ndb.npc_puppet_token = (self.account.pk, self.session.sessid + 1, self.char1.pk)
        self.assertFalse(svc.consume_full_puppet_token(npc, self.account, self.session))
        npc.ndb.npc_puppet_token = (self.account.pk, self.session.sessid, self.char1.pk)
        self.assertTrue(svc.consume_full_puppet_token(npc, self.account, self.session))
        self.assertFalse(svc.consume_full_puppet_token(npc, self.account, self.session))

    def test_freeze_and_hide_allow_release_and_despawn_only(self):
        record = self.spawned()
        svc.control(self.char1, record)
        runtime.set("NPCS_FROZEN", True)
        with self.assertRaises(svc.NPCError):
            svc.portray(self.char1, "waves")
        runtime.set("NPCS_REVEALED", False)
        svc.release(self.char1)
        self.assertEqual(
            svc.find_spawn(self.char1, f"#{record.spawned_object_id}", cleanup=True), record
        )
        svc.despawn(self.char1, record)
        with self.assertRaises(svc.NPCError):
            svc.create_blueprint(self.char1, "Hidden")

    def test_archive_despawns_but_preserves_records(self):
        record = self.spawned()
        svc.archive(self.char1, self.blueprint)
        record.refresh_from_db()
        self.assertIsNotNone(record.despawned_at)
        self.assertIsNone(record.spawned_object_id)
        self.assertFalse(svc.can_play(self.char1, svc.find_blueprint("Porter")))
        svc.archive(self.char1, self.blueprint, archived=False)
        svc.spawn(self.char1, self.blueprint)

    def test_direct_object_deletion_releases_unique_reservation(self):
        record = self.spawned()
        record.spawned_object.delete()
        record.refresh_from_db()
        self.assertIsNotNone(record.despawned_at)
        self.assertIsNone(record.unique_blueprint_id)
        svc.spawn(self.char1, self.blueprint)

    def test_failed_spawn_is_atomic(self):
        with (
            patch.object(
                NPCSpawnRecord.objects, "create", side_effect=RuntimeError("storage failed")
            ),
            self.assertRaises(RuntimeError),
        ):
            self.spawned()
        from evennia.objects.models import ObjectDB

        self.assertFalse(ObjectDB.objects.filter(db_key="Porter").exists())

    def test_despawn_by_unrelated_player_refused(self):
        with self.assertRaises(svc.NPCError):
            svc.despawn(self.char2, self.spawned())

    def test_expiry_preserves_history_and_allows_respawn(self):
        record = self.spawned()
        NPCSpawnRecord.objects.filter(pk=record.pk).update(
            last_active_at=timezone.now() - timedelta(days=2)
        )
        with patch.object(self.char1.sessions, "all", return_value=[]):
            self.assertEqual(svc.maintain(), 1)
        record.refresh_from_db()
        self.assertIsNotNone(record.despawned_at)
        self.assertIn("despawned", "\n".join(svc.history(self.char1, self.blueprint)))

    @override_settings(NPCS_SPAWN_IDLE_SECONDS=None)
    def test_expiry_can_be_disabled(self):
        record = self.spawned()
        NPCSpawnRecord.objects.filter(pk=record.pk).update(
            last_active_at=timezone.now() - timedelta(days=2)
        )
        self.assertEqual(svc.maintain(), 0)

    def test_profile_ships_dark_and_enforces_permission_and_types(self):
        self.assertTrue(NPCCombatProfile.objects.filter(blueprint=self.blueprint).exists())
        with self.assertRaises(svc.NPCError):
            svc.edit_profile(self.char1, self.blueprint, {"target_policy": "random"})
        runtime.set("NPCS_COMBAT_PROFILES_REVEALED", True)
        with self.assertRaises(svc.NPCError):
            svc.edit_profile(self.char2, self.blueprint, {"target_policy": "random"})
        for data in (
            {"action_weights": {"standard": True}},
            {"action_weights": {"standard": 0}},
            {"boss_check_schedule": [0]},
            {"reaction_policy": []},
            {"unknown": 1},
        ):
            with self.subTest(data=data), self.assertRaises(svc.NPCError):
                svc.edit_profile(self.char1, self.blueprint, data)
        profile = svc.edit_profile(
            self.char1,
            self.blueprint,
            {
                "target_policy": "lowest",
                "action_weights": {"standard": 2},
                "boss_check_schedule": [4, 2, 2],
            },
        )
        self.assertEqual(profile.boss_check_schedule, [2, 4])


@override_settings(
    NPCS_REVEALED=True,
    NPCS_FROZEN=False,
    NPCS_TYPECLASS="evennia_npcs.typeclasses.NPCCharacter",
    DEFAULT_HOME="#1",
)
class NPCCommandTests(BaseEvenniaCommandTest):
    def test_create_spawn_control_and_release(self):
        self.call(CmdNPC(), "/create Cameo=template", "Created NPC blueprint")
        blueprint = svc.find_blueprint("Cameo")
        self.call(CmdNPC(), "/spawn Cameo", "Spawned Cameo")
        record = blueprint.spawns.get()
        self.call(CmdNPC(), f"/puppet #{record.spawned_object_id}", "Now portraying Cameo")
        self.call(CmdNPCPose(), "waves.", f"Cameo (NPC, played by {self.char1.key}) waves.")
        self.call(CmdNPCSay(), "Hello", f'Cameo (NPC, played by {self.char1.key}) says, "Hello"')
        self.call(
            CmdNPCEmit(), "A bell rings.", f"Cameo (NPC, played by {self.char1.key}): A bell rings."
        )
        self.call(
            CmdNPCSemipose(),
            "'s eyes narrow.",
            f"Cameo (NPC, played by {self.char1.key})'s eyes narrow.",
        )
        self.call(CmdNPC(), "/unpuppet", "NPC portrayal released.")

    def test_invalid_switch_and_json_report_refusal(self):
        svc.create_blueprint(self.char1, "Porter")
        self.call(CmdNPC(), "/unknown Porter", "Unknown NPC switch")
        self.call(CmdNPC(), "/profile Porter={", "Expecting property name")

    def test_plain_pc_pose_and_say_still_work(self):
        self.call(CmdNPCPose(), "waves.", f"{self.char1.key} waves.")
        self.call(CmdNPCSay(), "Hello", 'You say, "Hello"')
