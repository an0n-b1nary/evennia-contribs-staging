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
        self.assertTrue(
            {"+balance", "+offer", "+accept", "+economy", "+stall", "+browse", "+buy", "+market"}
            <= {c.key for c in commands}
        )
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

    def test_room_roster_login_activity_and_seeded_market(self):
        from datetime import timedelta

        from django.utils import timezone
        from evennia.utils.create import create_object
        from evennia_economy.models import Storefront
        from evennia_economy.stalls import claim
        from typeclasses.rooms import Room

        room = create_object(Room, key="Test market")
        room.tags.add("market", category="rp_economy")
        self.char2.location = room
        store = claim(self.char2, name="Visible stockist")
        room.db.desc = "Preserve this description"
        with patch.object(self.char2, "msg"):
            self.assertFalse(self.char2.delete())
        self.assertIn(self.char2, self.account2.characters.all())
        self.assertFalse(room.delete())
        self.assertEqual(room.db.desc, "Preserve this description")
        self.assertIn("Visible stockist", room.return_appearance(self.char2))
        with override_settings(RP_ECONOMY_REVEALED=False):
            self.assertNotIn("Visible stockist", room.return_appearance(self.char2))
        old = timezone.now() - timedelta(weeks=6)
        Storefront.objects.filter(pk=store.pk).update(last_active=old)
        with patch.object(self.char2, "msg"):
            self.char2.at_post_puppet()
        store.refresh_from_db()
        self.assertGreater(store.last_active, old)

    def test_seed_market_is_populated_and_reseed_recovers_stock(self):
        from django.core.management import call_command
        from evennia_economy.models import Storefront

        from world.sandbox import content

        for _ in range(2):
            with self.captureOnCommitCallbacks(execute=True):
                call_command("seed_sandbox", verbosity=0)
            store = Storefront.objects.get(status="open", name=content.MARKET_STALL_NAME)
            self.assertEqual(store.room.db.sandbox_slug, "market")
            self.assertGreater(store.listings.filter(status="active").count(), 0)
