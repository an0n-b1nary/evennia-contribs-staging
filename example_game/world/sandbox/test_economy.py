# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Reference game command/start/login seams and real resource/equipment/jobs partners."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.conf import settings
from django.test import override_settings
from typeclasses.characters import Character

from evennia_economy import partner_tests
from evennia_economy.batch import run_weekly_batch
from evennia_economy.models import StipendPayment
from evennia_economy.services import balance


class EconomySeams(partner_tests.EconomyPartnerTests):
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

    def puppet(self):
        """A connected session puppeting char2 from its roster owner."""
        self.char2.account = self.account2
        return SimpleNamespace(
            logged_in=True,
            msg=Mock(),
            get_account=lambda: self.account2,
            get_puppet=lambda: self.char2,
        )

    def economy_items(self):
        from evennia_links.notices import NoticeContext
        from evennia_notices.services import project

        return project(NoticeContext(self.account2, self.char2), source="economy")

    def enter(self, session):
        """The puppet hook, then the Inbox's own puppet summary, with commits applied."""
        from evennia_notices.listeners import session_summary

        with self.captureOnCommitCallbacks(execute=True):
            self.char2.at_post_puppet()
            session_summary(self.char2, session=session)

    def test_login_summary_and_stipends_once(self):
        from evennia_economy import notices

        session = self.puppet()
        run_weekly_batch("test", characters=[self.char2])
        before = balance(self.char2)
        with (
            patch.object(notices, "_registered_sessions", return_value=[session]),
            patch.object(self.char2, "msg") as msg,
        ):
            self.enter(session)
            self.enter(session)
        kinds = sorted(item.events[0].event_id.rsplit("-", 1)[0] for item in self.economy_items())
        self.assertEqual(kinds, ["economy-income", "economy-stipend"])
        self.assertFalse(
            any(
                c.args and isinstance(c.args[0], str) and "Your latest income:" in c.args[0]
                for c in msg.call_args_list
            )
        )
        self.assertEqual(balance(self.char2), before)

    @override_settings(NOTICES_ENABLED=False)
    def test_login_summary_without_inbox_is_one_combined_line(self):
        from evennia_economy import notices

        session = self.puppet()
        run_weekly_batch("test", characters=[self.char2])
        before = balance(self.char2)
        with (
            patch.object(notices, "_registered_sessions", return_value=[session]),
            patch.object(self.char2, "msg") as msg,
            self.captureOnCommitCallbacks(execute=True),
        ):
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
        from evennia_economy import notices
        from evennia_economy.models import EconomyNoticeReceipt

        session = self.puppet()
        with patch.object(notices, "_registered_sessions", return_value=[session]):
            with (
                override_settings(RP_ECONOMY_REVEALED=False),
                patch.object(self.char2, "msg") as msg,
            ):
                self.enter(session)
                self.assertTrue(
                    StipendPayment.objects.filter(character=self.char2, kind="starting").exists()
                )
                self.assertFalse(EconomyNoticeReceipt.objects.exists())
                self.assertEqual(self.economy_items(), [])
            self.assertFalse(
                any(
                    c.args and isinstance(c.args[0], str) and "purse is ready" in c.args[0]
                    for c in msg.call_args_list
                )
            )
            from evennia_notices.listeners import session_summary

            with self.captureOnCommitCallbacks(execute=True):
                session_summary(self.char2, session=session)
        [item] = self.economy_items()
        self.assertEqual(item.events[0].event_id.rsplit("-", 1)[0], "economy-stipend")

    @override_settings(ROOT_URLCONF="world.sandbox.test_notices")
    def test_inbox_renders_income_for_only_the_selected_character(self):
        from django.test import RequestFactory

        from evennia_economy.models import EconomyNoticeReceipt
        from evennia_notices import views
        from evennia_notices.models import Notice

        with self.captureOnCommitCallbacks(execute=True):
            result = run_weekly_batch("sandbox-notice-test", characters=[self.char2])
        self.assertEqual(result["errors"], [])
        self.assertEqual(
            EconomyNoticeReceipt.objects.get(ubi__week="sandbox-notice-test").state, "transferred"
        )
        request = RequestFactory().get("/notices/")
        request.user = self.account2
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        self.assertNotContains(views.inbox(request).render(), "Weekly income")
        request.session["puppet"] = self.char2.pk
        self.assertContains(views.inbox(request).render(), "Weekly income")
        notice = Notice.objects.get(source="economy", events__event_id__startswith="economy-income")
        self.assertContains(views.detail(request, notice.public_ref).render(), "Weekly income")
        self.assertContains(views.preferences(request).render(), '<option value="economy">')
        with override_settings(RP_ECONOMY_REVEALED=False):
            self.assertNotContains(views.inbox(request).render(), "Weekly income")
            page = views.preferences(request).render()
            self.assertContains(page, ">Sandbox examples<")
            self.assertNotContains(page, '<option value="economy">')
            self.assertNotContains(page, ">Economy<")

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
        from typeclasses.rooms import Room

        from evennia_economy.models import Storefront
        from evennia_economy.stalls import claim

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
