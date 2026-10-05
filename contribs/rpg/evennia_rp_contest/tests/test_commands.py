# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real commands and msg_contents exercise privacy and template safety."""

from unittest.mock import patch

from django.test import override_settings

from evennia_rp_contest import services
from evennia_rp_contest.commands import CmdTest, ContestCmdSet
from evennia_rp_contest.models import Challenge, CheckRecord
from evennia_rp_contest.parsing import parse_challenge, parse_test
from evennia_rp_rules.dice import ScriptedRoller
from evennia_rp_rules.modifiers import ScoreBonus
from evennia_rp_rules.subjects import DictStatSource

from .base import ContestCommandTest


def hidden_adapter(obj):
    return DictStatSource(
        {"brawn": "Mid"},
        modifiers=[ScoreBonus(1, key="secret", label="Secret", visibility="hidden")],
    )


class CommandTests(ContestCommandTest):
    def test_player_sets_plain_and_suggested_challenges(self):
        self.call(
            CmdTest(),
            "/set Mid~Cross the chasm",
            "Char2 sets challenge #1 (Mid): Cross the chasm",
            caller=self.char2,
        )
        self.call(
            CmdTest(),
            "/set/once High=brawn/climbing~Climb",
            "Char2 sets challenge #2 (High) (once): Climb",
            caller=self.char2,
        )
        self.assertEqual(Challenge.objects.count(), 2)
        self.call(CmdTest(), "/list", "Open challenges:", caller=self.char2)

    def test_edit_void_close_once_and_history(self):
        challenge = services.open_challenge(self.char2, parse_challenge("Mid=brawn/climbing~Climb"))
        record = services.perform_test(
            self.char2, parse_test("brawn/climbing"), roller=self.scripted(0)
        )
        self.call(
            CmdTest(),
            "/edit #1=High=brains/fire~Read flames",
            "Char2 edits challenge #1 (High): Read flames",
            caller=self.char2,
        )
        self.call(
            CmdTest(), "/once #1", "Char2 marks once challenge #1 (High) (once)", caller=self.char2
        )
        self.call(
            CmdTest(),
            f"/void #1/{record.pk}~Agreed",
            f"Char2 voids attempt {record.pk} on #1. Agreed",
            caller=self.char2,
        )
        self.call(CmdTest(), "/history #1", f"Attempt {record.pk}:", caller=self.char2)
        output = self.call(CmdTest(), "/history #1", caller=self.char2)
        self.assertIn("[VOID: Agreed]", output)
        output = self.call(CmdTest(), "/review #1", caller=self.char1)
        self.assertIn("[VOID: Agreed]", output)
        self.assertIn('"resolver"', output)
        self.call(CmdTest(), "/close #1", "Char2 closes challenge #1", caller=self.char2)
        challenge.refresh_from_db()
        self.assertEqual(challenge.status, "closed")

    def test_setter_and_staff_only_management(self):
        challenge = services.open_challenge(self.char1, parse_challenge("Mid~Prompt"))
        record = services.perform_test(self.char2, parse_test("brawn"), roller=self.scripted(0))
        for text in ("/edit #1=High~Changed", f"/void #1/{record.pk}", "/close #1", "/once #1"):
            self.call(CmdTest(), text, "Only the setter or staff", caller=self.char2)
        self.call(CmdTest(), "/review", "Only staff", caller=self.char2)
        challenge.refresh_from_db()
        self.assertEqual(challenge.description, "Prompt")

    @override_settings(
        RP_RULES_SUBJECT_ADAPTER="evennia_rp_contest.tests.test_commands.hidden_adapter"
    )
    def test_hidden_breakdown_never_reaches_history_or_room(self):
        self.char2.key = "Ana"
        with patch.object(self.char1, "msg") as witness:
            record = services.perform_test(self.char2, parse_test("brawn"), roller=self.scripted(0))
        room_line = witness.call_args.kwargs["text"][0]
        self.assertEqual(room_line, "Ana tests Brawn: Good.")
        self.assertNotIn("Mid", room_line)
        self.assertNotRegex(room_line, r"\d")
        self.assertIn("secret", str(record.detail))
        history = self.call(CmdTest(), "/history", caller=self.char2)
        self.assertNotIn("secret", history)
        review = self.call(CmdTest(), "/review", caller=self.char1)
        self.assertIn("secret", review)
        self.assertIn('"roll"', review)

    def test_real_msg_contents_keeps_mapping_text_literal(self):
        comment = "{braces} $You() |r"
        with patch.object(self.char1, "msg") as witness, patch.object(self.char2, "msg") as tester:
            services.perform_test(
                self.char2, parse_test(f"brawn~{comment}"), roller=self.scripted(0)
            )
        message = witness.call_args.kwargs["text"]
        self.assertIn(comment, message[0])
        self.assertEqual(message[1], {"type": "rp_test"})
        private = tester.call_args.args[0]
        self.assertIn("Mid vs Mid", private[0])
        self.assertNotIn("roll", private[0])

    def test_prompt_name_and_void_reason_are_mapping_values(self):
        self.char2.key = "{actor} $You() |r"
        with patch.object(self.char1, "msg") as witness:
            services.open_challenge(self.char2, parse_challenge("Mid~{prompt} $You() |r"))
        message = witness.call_args.kwargs["text"][0]
        self.assertIn(self.char2.key, message)
        self.assertIn("{prompt} $You() |r", message)

    def test_retry_and_alternative_are_announced(self):
        services.open_challenge(self.char2, parse_challenge("Mid=brawn/climbing~Climb"))
        with patch.object(self.char1, "msg") as witness:
            services.perform_test(self.char2, parse_test("#1=brains/fire"), roller=self.scripted(0))
            services.perform_test(self.char2, parse_test("#1=brains/fire"), roller=self.scripted(0))
        self.assertIn("(alternative approach) (attempt 2)", witness.call_args.kwargs["text"][0])

    def test_base_command_uses_kernel_roller(self):
        with patch("evennia_rp_rules.pipeline.default_roller", return_value=ScriptedRoller([0])):
            self.call(CmdTest(), "brawn/fire", "Char2 tests Brawn (Fire): Good.", caller=self.char2)
        self.assertEqual(CheckRecord.objects.get().tag, "fire")

    def test_empty_usage_and_bad_switch_combination(self):
        self.call(CmdTest(), "", "Usage: +test", caller=self.char2)
        self.call(CmdTest(), "/edit", "Usage: +test/edit", caller=self.char2)
        self.call(CmdTest(), "/void #1", "Usage: +test/void", caller=self.char2)
        self.call(CmdTest(), "/set/close Mid~Prompt", "Use one switch", caller=self.char2)
        self.call(CmdTest(), "/history", "No tests", caller=self.char2)
        self.call(CmdTest(), "/list", "No open", caller=self.char2)

    def test_cmdset(self):
        self.assertTrue(any(cmd.key == "+test" for cmd in ContestCmdSet().commands))
