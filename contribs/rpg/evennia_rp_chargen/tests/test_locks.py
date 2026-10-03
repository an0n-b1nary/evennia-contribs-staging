# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Build locks: the state machine, announcements, TTL, checks and session end."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from evennia_rp_chargen import locks
from evennia_rp_chargen.integrations import rptracker
from evennia_rp_rules.checks import Check, resolve_check

from .base import ChargenTest


class LockStateTests(ChargenTest):
    def setUp(self):
        super().setUp()
        self.make_sheet(self.char1)

    def messages(self, obj):
        texts = []
        for call in obj.call_args_list:
            text = call.args[0] if call.args else call.kwargs.get("text")
            texts.append(str(text[0] if isinstance(text, tuple) else text))
        return " | ".join(texts)

    def test_pose_locks_and_tells_only_the_character(self):
        with patch.object(self.char1, "msg") as own, patch.object(self.char2, "msg") as other:
            locks.note_ic_action(self.char1)
        self.assertTrue(locks.is_locked(self.char1))
        self.assertEqual(locks.state(self.char1).reason, locks.POSE)
        self.assertIn("now locked for the scene", self.messages(own))
        other.assert_not_called()

    def test_manual_lock_and_unlock_are_announced(self):
        with patch.object(self.char2, "msg") as other:
            self.assertTrue(locks.lock(self.char1))
            self.assertFalse(locks.lock(self.char1))
            self.assertTrue(locks.unlock(self.char1))
            self.assertFalse(locks.unlock(self.char1))
        text = self.messages(other)
        self.assertIn("Char locks their edge and loadout.", text)
        self.assertIn("Char unlocks their edge and loadout.", text)

    def test_pose_while_unlocked_relocks(self):
        locks.note_ic_action(self.char1)
        locks.unlock(self.char1)
        locks.note_ic_action(self.char1)
        self.assertTrue(locks.is_locked(self.char1))

    def test_drafts_and_sheetless_characters_never_lock(self):
        locks.note_ic_action(self.char2)
        self.assertFalse(locks.is_locked(self.char2))
        self.assertIsNone(self.char2.attributes.get(locks.ATTR_KEY, category=locks.ATTR_CATEGORY))
        self.make_sheet(self.char2, finalize=False)
        locks.note_ic_action(self.char2)
        self.assertFalse(locks.is_locked(self.char2))

    @override_settings(RP_CHARGEN_LOCK_TTL=3600)
    def test_ttl_counts_from_the_last_ic_action(self):
        start = timezone.now()
        with patch("evennia_rp_chargen.locks.timezone.now", return_value=start):
            locks.note_ic_action(self.char1)
        later = start + timedelta(minutes=50)
        with patch("evennia_rp_chargen.locks.timezone.now", return_value=later):
            locks.note_ic_action(self.char1)  # restarts the clock
        with patch(
            "evennia_rp_chargen.locks.timezone.now", return_value=start + timedelta(minutes=90)
        ):
            self.assertTrue(locks.is_locked(self.char1))
        with (
            patch("evennia_rp_chargen.locks.timezone.now", return_value=later + timedelta(hours=1)),
            patch.object(self.char1, "msg") as own,
        ):
            self.assertFalse(locks.is_locked(self.char1))
        self.assertIn("no IC activity", self.messages(own))

    @override_settings(RP_CHARGEN_LOCK_TTL=None)
    def test_no_ttl(self):
        locks.lock(self.char1)
        far = timezone.now() + timedelta(days=30)
        with patch("evennia_rp_chargen.locks.timezone.now", return_value=far):
            self.assertTrue(locks.is_locked(self.char1))

    @override_settings(RP_CHARGEN_LOCK_SCOPES=("pips",), RP_CHARGEN_PIP_NOUN="Edge")
    def test_scopes_and_nouns(self):
        locks.lock(self.char1)
        self.assertTrue(locks.scope_locked(self.char1, "pips"))
        self.assertFalse(locks.scope_locked(self.char1, "loadout"))
        with patch.object(self.char1, "msg") as own:
            locks.unlock(self.char1)
        self.assertIn("You unlock your Edge.", self.messages(own))

    def test_release_is_quiet_to_the_room(self):
        locks.lock(self.char1)
        with patch.object(self.char2, "msg") as other, patch.object(self.char1, "msg") as own:
            self.assertTrue(locks.release(self.char1, locks.SESSION_END))
            self.assertFalse(locks.release(self.char1, locks.SESSION_END))
        other.assert_not_called()
        self.assertIn("your RP session ended", self.messages(own))


class LockTriggerTests(ChargenTest):
    @override_settings(RP_RULES_SUBJECT_ADAPTER="evennia_rp_chargen.subject.subject_adapter")
    def test_a_resolved_check_locks_its_actor(self):
        self.make_sheet(self.char1)
        resolve_check(Check("test", self.char1, "brawn", difficulty="Mid"), roller=self.scripted(0))
        self.assertTrue(locks.is_locked(self.char1))
        self.assertEqual(locks.state(self.char1).reason, locks.CHECK)

    def test_stat_block_actors_are_ignored(self):
        resolve_check(
            Check("test", {"brawn": "Mid"}, "brawn", difficulty="Mid"), roller=self.scripted(0)
        )

    def test_session_end_releases(self):
        self.make_sheet(self.char1)
        locks.lock(self.char1)

        class Session:
            character = self.char1

        rptracker.on_session_ended(sender=None, session=Session())
        self.assertFalse(locks.is_locked(self.char1))
        rptracker.on_session_ended(sender=None, session=None)

    def test_rptracker_signal_is_connected_when_installed(self):
        from django.apps import apps

        if not any(cfg.label == "evennia_rptracker" for cfg in apps.get_app_configs()):
            self.skipTest("evennia_rptracker isn't installed")
        from evennia_rptracker.signals import rp_session_ended

        self.make_sheet(self.char1)
        locks.lock(self.char1)

        class Session:
            character = self.char1

        rp_session_ended.send(sender=None, session=Session())
        self.assertFalse(locks.is_locked(self.char1))
