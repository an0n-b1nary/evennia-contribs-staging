# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The shared boundary refuses bad switches before any inherited hook runs."""

from unittest import TestCase
from unittest.mock import Mock

from .command_syntax import StrictSwitchMixin, whole_number


class Parent:
    def msg(self, text):
        self.output(text)

    def at_pre_cmd(self):
        self.parent_hook()
        return False


class Command(StrictSwitchMixin, Parent):
    key = "+example"
    switch_options = ("open", "close", "clear")


class CommandSyntaxTests(TestCase):
    def command(self, args):
        cmd = Command()
        cmd.args, cmd.output, cmd.parent_hook = args, Mock(), Mock()
        return cmd

    def test_bad_switches_stop_before_the_inherited_hook(self):
        for args in ("/", "/unknown", "/cl", "/open/close", "/open/", "//open"):
            with self.subTest(args=args):
                cmd = self.command(args)
                self.assertTrue(cmd.at_pre_cmd())
                cmd.parent_hook.assert_not_called()
                self.assertIn("usage", str(cmd.output.call_args))

    def test_exact_and_unique_prefixes_preserve_argument_case(self):
        for args, normalized in (
            ("/OPEN A=B # Keep CASE", "/open A=B # Keep CASE"),
            ("/o A/B=Value", "/open A/B=Value"),
            ("ordinary / text", "ordinary / text"),
        ):
            with self.subTest(args=args):
                cmd = self.command(args)
                self.assertFalse(cmd.at_pre_cmd())
                self.assertEqual(cmd.args, normalized)
                cmd.parent_hook.assert_called_once()
                cmd.output.assert_not_called()

    def test_exact_match_wins_over_longer_options(self):
        cmd = self.command("/open")
        cmd.switch_options = ("open", "opened")
        self.assertFalse(cmd.at_pre_cmd())

    def test_retired_spelling_cannot_become_a_unique_prefix(self):
        cmd = self.command("/open")
        cmd.switch_options = ("opened",)
        cmd.retired_switches = ("open",)
        self.assertTrue(cmd.at_pre_cmd())
        cmd.parent_hook.assert_not_called()
        cmd.args = "/ope"
        self.assertFalse(cmd.at_pre_cmd())

    def test_no_switch_command_refuses_every_switch(self):
        cmd = self.command("/open")
        cmd.switch_options = ()
        self.assertTrue(cmd.at_pre_cmd())
        cmd.parent_hook.assert_not_called()

    def test_refusal_bypasses_message_routing_that_might_look_up_subjects(self):
        cmd = self.command("/unknown")
        cmd.msg = Mock(side_effect=AssertionError("Looked up a subject"))
        self.assertTrue(cmd.at_pre_cmd())
        cmd.msg.assert_not_called()
        self.assertIn("usage", str(cmd.output.call_args))

    def test_numbers_have_readable_errors_and_signed_values_are_retained(self):
        self.assertEqual(whole_number("-2"), -2)
        for text in ("", "bad", "4=x", None):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "Give a whole number"):
                whole_number(text)
