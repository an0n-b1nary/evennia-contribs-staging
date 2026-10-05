# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Actual optional partner seams, also runnable in fresh absent-partner hosts."""

from unittest import skipUnless

from django.apps import apps
from django.test import override_settings

from evennia_rp_contest import expiry, services
from evennia_rp_contest.parsing import parse_challenge, parse_test

from .base import ContestTest

HAS_SCENES = apps.is_installed("evennia_scenes")
HAS_TRACKER = apps.is_installed("evennia_rptracker")
HAS_CHARGEN = apps.is_installed("evennia_rp_chargen")


class PublicHookTests(ContestTest):
    def test_public_expiry_hooks_are_scoped(self):
        first = services.open_challenge(self.char2, parse_challenge("Mid~One"))
        other = services.open_challenge(self.char1, parse_challenge("Mid~Two"))
        self.assertEqual(expiry.close_for_setter(self.char2), 1)
        other.refresh_from_db()
        self.assertEqual(other.status, "open")
        other.scene_id = 99
        other.save(update_fields=["scene_id"])
        self.assertEqual(expiry.close_for_scene(99), 1)
        self.assertEqual(expiry.close_for_scene(99), 0)
        first.refresh_from_db()
        self.assertEqual(first.closed_reason, "session_end")

    def test_no_active_scene_means_no_scene_id(self):
        record = services.perform_test(
            self.char2, parse_test("brawn/fire"), roller=self.scripted(0)
        )
        self.assertIsNone(record.scene_id)


@skipUnless(HAS_SCENES, "scenes is absent")
class ScenesTests(ContestTest):
    def setUp(self):
        super().setUp()
        from evennia_scenes.models import Scene

        self.scene = Scene.objects.create(
            room=self.room1, room_name=self.room1.key, creator=self.char2
        )
        self.room1.active_scene_id = self.scene.pk

    def test_real_system_log_and_close_signal(self):
        from evennia_scenes.models import LogEntry
        from evennia_scenes.signals import scene_closed

        challenge = services.open_challenge(self.char2, parse_challenge("Mid~Prompt"))
        record = services.perform_test(
            self.char2, parse_test("brains/fire"), roller=self.scripted(0)
        )
        self.assertEqual(record.scene_id, self.scene.pk)
        log = LogEntry.objects.get(scene=self.scene)
        self.assertEqual(log.log_type, "system")
        self.assertIn("Char2 tests Brains (Fire)", log.content)
        self.assertNotIn("Mid", log.content)
        self.assertNotIn("roll", log.content)
        services.void_attempt(self.char2, challenge, record.pk, reason="OOC agreement")
        self.assertEqual(LogEntry.objects.filter(scene=self.scene).count(), 2)
        scene_closed.send(sender=type(self.scene), scene=self.scene, closer=self.char2)
        challenge.refresh_from_db()
        self.assertEqual(challenge.closed_reason, "scene_closed")

    def test_hard_delete_detaches_without_losing_audit(self):
        challenge = services.open_challenge(self.char2, parse_challenge("Mid~Prompt"))
        record = services.perform_test(self.char2, parse_test("brawn"), roller=self.scripted(0))
        self.scene.delete()
        challenge.refresh_from_db()
        record.refresh_from_db()
        self.assertIsNone(challenge.scene_id)
        self.assertIsNone(record.scene_id)
        self.assertEqual(challenge.status, "closed")
        self.assertTrue(record.detail)

    def test_closed_or_stale_scene_id_is_ignored(self):
        self.scene.status = "closed"
        self.scene.save()
        self.assertIsNone(services.scene_id_for(self.char2))
        self.room1.active_scene_id = 9999999
        self.assertIsNone(services.scene_id_for(self.char2))


@skipUnless(HAS_TRACKER, "rptracker is absent")
class TrackerTests(ContestTest):
    def test_actual_session_signal_closes_setters_challenges(self):
        from evennia_rptracker.models import RPSession
        from evennia_rptracker.signals import rp_session_ended

        challenge = services.open_challenge(self.char2, parse_challenge("Mid~Prompt"))
        other = services.open_challenge(self.char1, parse_challenge("Mid~Other"))
        session = RPSession.objects.create(character=self.char2, room=self.room1)
        rp_session_ended.send(sender=RPSession, session=session)
        challenge.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(challenge.closed_reason, "session_end")
        self.assertEqual(other.status, "open")


@skipUnless(HAS_CHARGEN, "chargen is absent")
class ChargenTests(ContestTest):
    @override_settings(RP_RULES_SUBJECT_ADAPTER="evennia_rp_chargen.subject.subject_adapter")
    def test_equipped_element_bonus_and_test_lock(self):
        from evennia_rp_chargen import abilities, locks
        from evennia_rp_chargen.models import AbilityDefinition, CharacterBuild, TagDefinition
        from evennia_rp_chargen.services import finalize
        from evennia_rp_chargen.stats import StatHandler

        CharacterBuild.objects.create(character=self.char2)
        stats = StatHandler(self.char2)
        for key in self.ruleset.stats:
            stats.set(key, self.ruleset.parse_rating("Mid"))
        with override_settings(
            RP_CHARGEN_ALLOCATION={
                "path": "evennia_rp_chargen.allocation.PointBuyAllocation",
                "params": {"costs": {"low": 0, "mid": 1, "high": 3}, "budget": 4},
            }
        ):
            finalize(self.char2)
        TagDefinition.objects.create(key="fire", name="Fire", kind="element")
        ability = AbilityDefinition.objects.create(
            key="focus",
            name="Focus",
            acquisition="staff",
            budget_cost=0,
            effects=[{"kind": "tag_bonus", "tags": ["fire"], "score": 5}],
        )
        owned = abilities.grant(self.char2, ability.key, by=self.char1)
        owned.equipped = True
        owned.save(update_fields=["equipped"])
        record = services.perform_test(
            self.char2, parse_test("brains/fire"), roller=self.scripted(0)
        )
        self.assertEqual(record.outcome_key, "great")
        self.assertTrue(locks.state(self.char2).locked)
