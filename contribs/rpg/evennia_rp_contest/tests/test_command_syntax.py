# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Hard-break syntax and challenge edits exercise persisted behavior."""

from unittest.mock import patch

from evennia_rp_contest import services
from evennia_rp_contest.commands import CmdTest, ContestCmdSet
from evennia_rp_contest.models import Challenge, CheckRecord
from evennia_rp_contest.parsing import ChallengeRequest, parse_test

from .base import ContestCommandTest


class CommandSyntaxTests(ContestCommandTest):
    def challenge_command(self, args, caller=None):
        from evennia_rp_contest.commands import CmdChallenge

        return self.call(CmdChallenge(), args, caller=caller or self.char2)

    def test_companion_registered_and_field_edits_preserve_other_fields(self):
        self.assertIn("+challenge", {cmd.key for cmd in ContestCmdSet().commands})
        self.challenge_command("/Ne Mid=Cross #12 = the chasm ~ carefully")
        challenge = Challenge.objects.get()
        self.assertEqual(challenge.description, "Cross #12 = the chasm ~ carefully")
        self.challenge_command("/Su #1=brawn/climbing")
        self.challenge_command("/once #1")
        self.challenge_command("/edit #1=Read #7 = the flames")
        self.challenge_command("/Di #1=High")
        challenge.refresh_from_db()
        self.assertEqual((challenge.stat_key, challenge.tag), ("brawn", "climbing"))
        self.assertEqual(challenge.description, "Read #7 = the flames")
        self.assertEqual(challenge.difficulty, "High")
        self.assertTrue(challenge.once)
        self.assertEqual(challenge.edited_by, self.char2)
        self.assertIn("Read #7 = the flames", self.challenge_command(""))

    def test_unnumbered_test_stays_free_and_comment_preserves_references(self):
        challenge = services.open_challenge(
            self.char2, ChallengeRequest("High", "Climb", "brawn", "climbing", True)
        )
        request = parse_test("brawn/climbing # At #12 ~ = {actor} $You() # later")
        with patch.object(self.char1, "msg") as witness:
            record = services.perform_test(self.char2, request, roller=self.scripted(0))
        self.assertIsNone(record.challenge_id)
        self.assertEqual(record.difficulty, "Mid")
        self.assertEqual(record.comment, "At #12 ~ = {actor} $You() # later")
        self.assertIn(record.comment, witness.call_args.kwargs["text"][0])
        record = services.perform_test(
            self.char2, parse_test("#1=brawn/climbing # Climb"), roller=self.scripted(0)
        )
        self.assertEqual(record.challenge_id, challenge.pk)
        self.assertEqual(record.difficulty, "High")

    def test_addressed_void_keeps_audit_and_allows_once_retry(self):
        services.open_challenge(self.char2, ChallengeRequest("Mid", "Prompt", once=True))
        record = services.perform_test(self.char2, parse_test("#1=brawn"), roller=self.scripted(0))
        before = CheckRecord.objects.count()
        self.assertIn("only one attempt", self.call(CmdTest(), "#1=brawn", caller=self.char2))
        self.assertEqual(CheckRecord.objects.count(), before)
        services.open_challenge(self.char2, ChallengeRequest("Mid", "Other challenge"))
        self.assertIn("No such attempt", self.challenge_command(f"/void #2.{record.pk}"))
        record.refresh_from_db()
        self.assertFalse(record.voided)
        self.challenge_command(f"/Vo #1.{record.pk} # Agreed #12 ~ = reason")
        record.refresh_from_db()
        self.assertTrue(record.voided)
        self.assertEqual(record.void_reason, "Agreed #12 ~ = reason")
        history = self.challenge_command("/history #1")
        self.assertIn(f"Attempt {record.pk}:", history)
        self.assertIn("[VOID: Agreed #12 ~ = reason]", history)
        retry = services.perform_test(self.char2, parse_test("#1=brawn"), roller=self.scripted(0))
        self.assertEqual(retry.attempt_no, 2)
        self.assertIn("Only staff", self.challenge_command("/review"))
        self.assertIn('"resolver"', self.challenge_command("/review #1", self.char1))

    def test_retired_and_stacked_test_switches_cannot_roll_or_create(self):
        for args in (
            "/set Mid~Prompt",
            "/set/once Mid~Prompt",
            "/list brawn",
            "/bogus brawn",
            "/history brawn",
            "/edit #1=High~Prompt",
        ):
            with self.subTest(args=args):
                self.call(CmdTest(), args, caller=self.char2)
                self.assertFalse(Challenge.objects.exists())
                self.assertFalse(CheckRecord.objects.exists())
        self.call(CmdTest(), "brawn~retired comment", caller=self.char2)
        self.assertFalse(CheckRecord.objects.exists())

    def test_permissions_invalid_inputs_closed_and_cross_room_guards(self):
        self.challenge_command("/new Mid=Prompt")
        for args in (
            "/suggest #1=brains/fire",
            "/edit #1=Changed",
            "/difficulty #1=High",
            "/once #1",
            "/close #1",
        ):
            self.assertIn(
                "Only the setter or staff", self.challenge_command(args, self.char1_other)
            )
        for args in (
            "/new High~Old",
            "/difficulty #1=not-a-grade",
            "/suggest #1=no-stat",
            "/edit #1=",
            "/new/once High=Prompt",
            "/unknown brawn",
            "/list",
            "/void #1/1~Old",
        ):
            self.challenge_command(args)
        challenge = Challenge.objects.get()
        self.assertEqual(
            (challenge.difficulty, challenge.description, challenge.stat_key),
            ("Mid", "Prompt", None),
        )
        self.assertIn("closes", self.challenge_command("/close #1", self.char1))
        self.assertIn("closed", self.challenge_command("/suggest #1=brawn"))
        self.char2.location = self.room2
        self.assertIn("No challenge #1", self.challenge_command("/edit #1=Changed"))

    @property
    def char1_other(self):
        # char1 is the staff fixture; temporarily use an ordinary third character.
        if not hasattr(self, "_other"):
            from evennia.utils.create import create_object

            self._other = create_object(self.char2.typeclass_path, key="Other", location=self.room1)
            self.addCleanup(self._other.delete)
        return self._other
