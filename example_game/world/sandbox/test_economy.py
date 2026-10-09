# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Reference game command/start/login seams and real resource/equipment/jobs partners."""

from unittest.mock import patch

from django.test import override_settings
from evennia_economy.batch import run_weekly_batch
from evennia_economy.models import StipendPayment
from evennia_economy.partner_tests import EconomyPartnerTests
from evennia_economy.services import balance
from typeclasses.characters import Character


class EconomySeams(EconomyPartnerTests):
    character_typeclass = Character

    def test_cmdsets_register_atomic_give_and_economy_commands(self):
        from commands.default_cmdsets import CharacterCmdSet
        from evennia_economy.commands import CmdGive

        commands = CharacterCmdSet().commands
        self.assertTrue({"+balance", "+offer", "+accept", "+economy"} <= {c.key for c in commands})
        self.assertTrue(any(isinstance(c, CmdGive) for c in commands if c.key == "give"))

    def test_login_summary_and_stipends_once(self):
        run_weekly_batch("test", characters=[self.char2])
        before = balance(self.char2)
        with patch.object(self.char2, "msg") as msg:
            self.char2.at_post_puppet()
            self.char2.at_post_puppet()
        summaries = [
            c
            for c in msg.call_args_list
            if c.args and isinstance(c.args[0], str) and "Your latest income:" in c.args[0]
        ]
        self.assertEqual(len(summaries), 1)
        self.assertEqual(balance(self.char2), before)

    def test_hidden_login_accumulates_stipend_without_notification(self):
        with override_settings(RP_ECONOMY_REVEALED=False), patch.object(self.char2, "msg") as msg:
            self.char2.at_post_puppet()
        self.assertTrue(
            StipendPayment.objects.filter(character=self.char2, kind="starting").exists()
        )
        self.assertFalse(
            any(
                c.args and isinstance(c.args[0], str) and "purse is ready" in c.args[0]
                for c in msg.call_args_list
            )
        )

    def test_start_helper_idempotent(self):
        from evennia.scripts.models import ScriptDB
        from evennia_economy.scripts import ensure_economy_script_running

        ensure_economy_script_running()
        ensure_economy_script_running()
        self.assertEqual(ScriptDB.objects.filter(db_key="economy_batch").count(), 1)
