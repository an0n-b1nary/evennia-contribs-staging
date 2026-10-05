# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Outcomes, challenge lifecycle, audit privacy and transactional failures."""

from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from evennia_rp_contest import expiry, services, signals
from evennia_rp_contest.models import Challenge, CheckRecord
from evennia_rp_contest.parsing import ContestError, parse_challenge, parse_test

from .base import ContestTest


class ServiceTests(ContestTest):
    def open(self, text="Mid=brawn/climbing~Climb", **kwargs):
        return services.open_challenge(self.char2, parse_challenge(text, **kwargs))

    def test_every_band_and_audit(self):
        cases = (("Low", "awful"), ("Mid", "good"), ("High", "great"))
        for rating, key in cases:
            self.char2.attributes.add("contest_test_stats", {"brawn": rating})
            record = services.perform_test(self.char2, parse_test("brawn"), roller=self.scripted(0))
            self.assertEqual(record.outcome_key, key)
            self.assertEqual(record.detail["ruleset"]["digest"], self.ruleset.digest)
            self.assertIn("roll", record.detail["resolution"])
            self.assertIn("resolver", record.detail["resolution"])
        self.char2.attributes.add("contest_test_stats", {"brawn": "Mid"})
        record = services.perform_test(self.char2, parse_test("brawn"), roller=self.scripted(-1))
        self.assertEqual(record.outcome_key, "bad")

    def test_numbering_survives_close_archive_and_is_per_room(self):
        first = self.open()
        services.close_challenge(first, caller=self.char2)
        first.archive(self.char2)
        self.assertEqual(self.open().number, 2)
        self.char2.location = self.room2
        self.assertEqual(self.open().number, 1)

    def test_automatic_binding_and_prompt_only(self):
        suggested = self.open()
        record = services.perform_test(
            self.char2, parse_test("brawn/climbing"), roller=self.scripted(0)
        )
        self.assertEqual(record.challenge, suggested)
        self.assertFalse(record.alternative)
        record = services.perform_test(
            self.char2, parse_test("brains/fire"), roller=self.scripted(0)
        )
        self.assertIsNone(record.challenge)
        plain = self.open("High~Cross the chasm")
        record = services.perform_test(
            self.char2, parse_test("brains/fire"), roller=self.scripted(0)
        )
        self.assertEqual(record.challenge, plain)
        self.assertFalse(record.alternative)
        # Both now match; ambiguity uses ad-hoc default.
        record = services.perform_test(
            self.char2, parse_test("brawn/climbing"), roller=self.scripted(0)
        )
        self.assertIsNone(record.challenge)
        self.assertEqual(record.difficulty, "Mid")

    def test_alternative_stat_tag_and_missing_tag(self):
        challenge = self.open()
        for text in ("brains/climbing", "brawn/fire", "brawn"):
            record = services.perform_test(
                self.char2, parse_test(f"#{challenge.number}={text}"), roller=self.scripted(0)
            )
            self.assertTrue(record.alternative)
        self.assertEqual(record.attempt_no, 3)

    def test_once_void_and_retry_keep_history(self):
        challenge = self.open(once=True)
        first = services.perform_test(
            self.char2, parse_test("brawn/climbing"), roller=self.scripted(0)
        )
        with self.assertRaisesRegex(ContestError, "only one"):
            services.perform_test(self.char2, parse_test("brawn/climbing"), roller=self.scripted(0))
        services.void_attempt(self.char2, challenge, first.pk, reason="Agreed OOC")
        first.refresh_from_db()
        self.assertTrue(first.voided)
        second = services.perform_test(
            self.char2, parse_test("brawn/climbing"), roller=self.scripted(0)
        )
        self.assertEqual(second.attempt_no, 2)
        self.assertEqual(CheckRecord.objects.count(), 2)

    def test_unauthorized_management_and_cross_room_lookup(self):
        challenge = services.open_challenge(self.char1, parse_challenge("Mid~Prompt"))
        for operation in (
            lambda: services.edit_challenge(self.char2, challenge, parse_challenge("High~Changed")),
            lambda: services.close_challenge(challenge, caller=self.char2),
            lambda: services.set_once(self.char2, challenge),
            lambda: services.void_attempt(self.char2, challenge, 1),
        ):
            with self.assertRaisesRegex(ContestError, "Only the setter"):
                operation()
        self.char2.location = self.room2
        with self.assertRaisesRegex(ContestError, "No challenge"):
            services.find_challenge(self.char2, challenge.number)

    @override_settings(RP_CONTEST_CAN_SET_CHALLENGE="cmd:perm(Builder)")
    def test_set_permission_is_a_service_guard(self):
        with self.assertRaisesRegex(ContestError, "may not set"):
            self.open()

    def test_edit_preserves_previous_record_and_once(self):
        challenge = self.open(once=True)
        record = services.perform_test(
            self.char2, parse_test("brawn/climbing"), roller=self.scripted(0)
        )
        services.edit_challenge(self.char1, challenge, parse_challenge("High=brains/fire~Changed"))
        record.refresh_from_db()
        self.assertEqual(record.difficulty, "Mid")
        self.assertEqual(challenge.difficulty, "High")
        self.assertTrue(challenge.once)
        self.assertEqual(challenge.edited_by, self.char1)

    def test_missing_stats_do_not_record_or_refresh_idle(self):
        challenge = self.open()
        before = challenge.last_activity
        self.char2.attributes.add("contest_test_stats", {})
        with self.assertRaises(ContestError):
            services.perform_test(self.char2, parse_test("brawn/climbing"), roller=self.scripted(0))
        challenge.refresh_from_db()
        self.assertEqual(challenge.last_activity, before)
        self.assertFalse(CheckRecord.objects.exists())

    def test_signal_failure_rolls_back_record(self):
        challenge = self.open()
        before = challenge.last_activity

        def fail(sender, **kwargs):
            raise RuntimeError("listener failed")

        signals.check_recorded.connect(fail)
        try:
            with self.assertRaisesRegex(RuntimeError, "listener failed"):
                services.perform_test(
                    self.char2, parse_test("brawn/climbing"), roller=self.scripted(0)
                )
        finally:
            signals.check_recorded.disconnect(fail)
        challenge.refresh_from_db()
        self.assertEqual(challenge.last_activity, before)
        self.assertFalse(CheckRecord.objects.exists())

    def test_closed_expired_and_missing_challenges(self):
        challenge = self.open()
        Challenge.objects.filter(pk=challenge.pk).update(
            last_activity=timezone.now() - timedelta(hours=4)
        )
        with self.assertRaisesRegex(ContestError, "closed"):
            services.perform_test(self.char2, parse_test("#1=brawn"), roller=self.scripted(0))
        challenge.refresh_from_db()
        self.assertEqual(challenge.closed_reason, "idle")
        with self.assertRaisesRegex(ContestError, "No challenge"):
            services.perform_test(self.char2, parse_test("#99=brawn"), roller=self.scripted(0))

    def test_test_refreshes_idle_and_sweep_is_idempotent(self):
        challenge = self.open()
        old = timezone.now() - timedelta(hours=2)
        Challenge.objects.filter(pk=challenge.pk).update(last_activity=old)
        services.perform_test(self.char2, parse_test("brawn/climbing"), roller=self.scripted(0))
        challenge.refresh_from_db()
        self.assertGreater(challenge.last_activity, old)
        future = timezone.now() + timedelta(hours=4)
        self.assertEqual(expiry.sweep_idle(now=future), 1)
        self.assertEqual(expiry.sweep_idle(now=future), 0)

    def test_idle_close_rechecks_activity_after_sweep_snapshot(self):
        challenge = self.open()
        old = timezone.now() - timedelta(hours=4)
        Challenge.objects.filter(pk=challenge.pk).update(last_activity=old)
        challenge.refresh_from_db()
        Challenge.objects.filter(pk=challenge.pk).update(last_activity=timezone.now())
        self.assertFalse(
            services.close_challenge(
                challenge, reason="idle", idle_before=timezone.now() - timedelta(hours=3)
            )
        )
        challenge.refresh_from_db()
        self.assertEqual(challenge.status, "open")

    def test_void_id_disambiguates_different_actors_first_attempts(self):
        challenge = self.open()
        first = services.perform_test(
            self.char1, parse_test("brawn/climbing"), roller=self.scripted(0)
        )
        second = services.perform_test(
            self.char2, parse_test("brawn/climbing"), roller=self.scripted(0)
        )
        self.assertEqual((first.attempt_no, second.attempt_no), (1, 1))
        services.void_attempt(self.char2, challenge, second.pk)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.voided)
        self.assertTrue(second.voided)

    @override_settings(RP_CONTEST_CHALLENGE_IDLE_TTL=None)
    def test_idle_disabled(self):
        self.open()
        self.assertEqual(expiry.sweep_idle(now=timezone.now() + timedelta(days=10)), 0)

    def test_no_location(self):
        self.char2.location = None
        with self.assertRaisesRegex(ContestError, "room"):
            self.open()

    def test_deleted_character_and_room_keep_audit(self):
        challenge = self.open()
        record = services.perform_test(
            self.char2, parse_test("brawn/climbing"), roller=self.scripted(0)
        )
        name = self.char2.key
        self.char2.delete()
        record.refresh_from_db()
        challenge.refresh_from_db()
        self.assertEqual(record.actor_name, name)
        self.assertIsNone(record.character)
        self.assertIsNone(challenge.set_by)

    @override_settings(
        RP_CONTEST_SCENE_ID_RESOLVER="evennia_rp_contest.tests.test_services.custom_scene_id"
    )
    def test_custom_scene_resolver(self):
        self.assertEqual(services.scene_id_for(self.char2), 4242)


def custom_scene_id(caller):
    return 4242
