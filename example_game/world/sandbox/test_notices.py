# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real reference source, explicit opt-in, commands, web and single-admin fixtures."""

from importlib import import_module
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.test import RequestFactory, override_settings
from django.urls import include, path
from evennia.accounts.models import AccountDB
from evennia.objects.models import ObjectDB
from evennia.utils.test_resources import EvenniaTest

from evennia_notices.context import from_web
from evennia_notices.models import DeliveryReceipt, Notice, NoticeEvent
from evennia_notices.services import mutate, project
from world.sandbox.notices_seed import emit_demo_notices, resolve_demo_offer, seed_subject_templates

urlpatterns = [path("", include("web.urls"))]


@override_settings(ROOT_URLCONF=__name__)
class NoticeSeams(EvenniaTest):
    """Foundation examples never silently enlist real accounts or characters."""

    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)

    def test_seed_without_recipient_creates_no_account_or_notice(self):
        before = AccountDB.objects.count()
        seed_subject_templates()
        seed_subject_templates()
        self.assertEqual(AccountDB.objects.count(), before)
        self.assertFalse(Notice.objects.exists())

    def test_explicit_self_opt_in_is_idempotent_and_scoped(self):
        emit_demo_notices(self.account, self.char1)
        rows = list(NoticeEvent.objects.values_list("pk", "read_at"))
        emit_demo_notices(self.account, self.char1)
        self.assertEqual(list(NoticeEvent.objects.values_list("pk", "read_at")), rows)
        self.assertEqual(len(rows), 4)
        from evennia_links.notices import NoticeContext

        self.assertEqual(project(NoticeContext(self.account2, self.char2)), [])
        self.assertEqual(len(project(NoticeContext(self.account))), 1)

    def test_simulated_offer_is_owned_and_read_does_not_resolve_it(self):
        emit_demo_notices(self.account, self.char1)
        from evennia_links.notices import NoticeContext

        context = NoticeContext(self.account, self.char1)
        offer = project(context, "pending")[0]
        token = offer.events[0].subject["key"]
        mutate(context, offer.notice.public_ref, "read")
        with self.assertRaises(ValueError):
            mutate(context, offer.notice.public_ref, "clear")
        with self.assertRaises(ValueError):
            resolve_demo_offer(self.account2, self.char2, token, True)
        self.assertEqual(resolve_demo_offer(self.account, self.char1, token, True), "confirmed")
        self.assertEqual(resolve_demo_offer(self.account, self.char1, token, True), "confirmed")
        self.assertEqual(project(context, "pending"), [])

    def test_demo_reset_generation_preserves_real_rosters_and_receipts(self):
        emit_demo_notices(self.account, self.char1)
        roster = list(self.account.characters.all())
        receipts = set(DeliveryReceipt.objects.values_list("pk", flat=True))
        seed_subject_templates(reset=True)
        emit_demo_notices(self.account, self.char1)
        self.assertEqual(list(self.account.characters.all()), roster)
        self.assertTrue(
            receipts.issubset(set(DeliveryReceipt.objects.values_list("pk", flat=True)))
        )
        self.assertEqual(DeliveryReceipt.objects.count(), 8)

    def test_seed_dry_run_does_not_emit_demo_notices(self):
        with patch(
            "world.sandbox.management.commands.seed_sandbox.Command._purge", return_value={}
        ):
            call_command("seed_sandbox", dry_run=True, verbosity=0)
        self.assertFalse(Notice.objects.exists())
        self.assertFalse(ObjectDB.objects.filter(db_tags__db_key="notice-template-offer").exists())

    def test_golden_notice_fixtures_preserve_single_admin_audit(self):
        # The builder retains and passes its explicitly created admin object.
        # Generic fixture helper creates no account or extra playable character.
        before_accounts = AccountDB.objects.count()
        before_characters = list(self.account.characters.all())
        emit_demo_notices(self.account, self.char1)
        self.assertEqual(AccountDB.objects.count(), before_accounts)
        self.assertEqual(list(self.account.characters.all()), before_characters)
        from pathlib import Path

        builder = Path(settings.GAME_DIR) / "scripts/snapshot_golden.py"
        if builder.exists():
            text = builder.read_text()
            self.assertIn("admin = AccountDB.objects.create_superuser", text)
            self.assertIn("emit_demo_notices(admin, character)", text)
            self.assertIn("len(accounts) != 1", text)

    def test_rendered_selected_character_nav_and_account_command(self):
        emit_demo_notices(self.account, self.char1)
        from commands.default_cmdsets import AccountCmdSet
        from web.website.nav import build_menu

        from evennia_notices import views

        self.assertEqual(sum(c.key == "+notices" for c in AccountCmdSet().commands), 1)
        request = RequestFactory().get("/notices/")
        request.user = self.account
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        self.assertIsNone(from_web(request).character)
        self.assertContains(views.inbox(request).render(), "Choose a character")
        request.session["puppet"] = self.char1.pk
        self.assertContains(views.inbox(request).render(), "simulated waitlist")
        for response in (
            views.inbox(request, history=True),
            views.preferences(request),
            views.detail(request, Notice.objects.first().public_ref),
        ):
            self.assertContains(response.render(), "My Notices")
        self.assertIn(
            "My Notices", [i["label"] for i in build_menu(request)["account"]["personal"]]
        )
        request.user = AnonymousUser()
        self.assertNotIn(
            "My Notices", [i["label"] for i in build_menu(request)["account"]["personal"]]
        )


@override_settings(ROOT_URLCONF=__name__)
class BoardNoticeSeam(EvenniaTest):
    """Use the normal post creator, Social, and both Inbox ownership modes."""

    def test_subscribed_activity_is_generic_and_account_owned(self):
        from evennia_boards.models import Board, Post, PostReadSuppression, Subscription
        from evennia_links.notices import NoticeContext
        from evennia_notices import views
        from evennia_social import ignore

        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        for account in (self.account, self.account2):
            account.permissions.clear()
            account.is_superuser = False
            account.save(update_fields=["is_superuser"])
        self.char2.permissions.clear()
        board = Board.objects.create(name="Sandbox Board", is_read_only=True)
        subscription = Subscription.objects.create(account=self.account, board=board)
        with self.captureOnCommitCallbacks(execute=True):
            visible = Post.create_post(board, None, "spoiler title", "spoiler body")
        ignore.set_entry(self.account, self.char2)
        with self.captureOnCommitCallbacks(execute=True):
            Post.create_post(board, self.char2, "hidden title", "hidden body")

        [entry] = project(NoticeContext(self.account))
        self.assertEqual(entry.events[0].payload["post"], visible.pk)
        self.assertEqual(entry.text, "New activity on Sandbox Board")
        self.assertFalse(project(NoticeContext(self.account2, self.char2)))
        request = RequestFactory().get("/notices/")
        request.user = self.account
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        response = views.inbox(request).render()
        self.assertContains(response, "New activity on Sandbox Board")
        detail = views.detail(request, entry.notice.public_ref).render()
        self.assertContains(detail, f"/boards/{board.pk}/")
        self.assertNotContains(detail, "spoiler title")
        self.assertNotContains(detail, "hidden title")
        request.session["puppet"] = self.char1.pk
        self.assertEqual(from_web(request).character, self.char1)
        mutate(from_web(request), entry.notice.public_ref, "clear")
        self.assertFalse(project(NoticeContext(self.account)))
        self.assertIsNone(self.account.attributes.get("boards_web_read"))
        self.assertTrue(Subscription.objects.filter(pk=subscription.pk).exists())
        self.assertFalse(PostReadSuppression.objects.exists())

    @override_settings(NOTICES_ROUTINE_LIMIT=1)
    def test_real_social_policy_keeps_an_independent_compacted_witness(self):
        from evennia_boards.models import Board, Post, Subscription
        from evennia_links.notices import NoticeContext
        from evennia_notices.services import summarize
        from evennia_social import ignore

        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        for account in (self.account, self.account2):
            account.permissions.clear()
            account.is_superuser = False
            account.save(update_fields=["is_superuser"])
        self.char2.permissions.clear()
        public = Board.objects.create(name="Visible board")
        ignored = Board.objects.create(name="Hidden activity board")
        for board in (public, ignored):
            Subscription.objects.create(account=self.account, board=board)
        with self.captureOnCommitCallbacks(execute=True):
            visible = Post.create_post(public, None, "visible title", "visible body")
            hidden = Post.create_post(ignored, self.char2, "hidden title", "hidden body")
        context = NoticeContext(self.account)
        [envelope] = project(context)
        self.assertTrue(envelope.notice.is_compacted)
        self.assertEqual(len(envelope.events), 2)
        ignore.set_entry(self.account, self.char2)
        self.assertTrue(Post.objects.filter(pk=hidden.pk).exists())
        [remaining] = project(context)
        self.assertEqual([event.payload["post"] for event in remaining.events], [visible.pk])
        self.assertEqual(remaining.text, "New activity on Visible board")
        self.assertEqual(summarize(context), (1, 0))
        ignore.clear(self.account)
        [remaining] = project(context)
        self.assertEqual([event.payload["post"] for event in remaining.events], [visible.pk])


@override_settings(ROOT_URLCONF=__name__)
class XPNoticeSeams(EvenniaTest):
    def setUp(self):
        super().setUp()
        from django.apps import apps

        if not apps.is_installed("evennia_xp"):
            self.skipTest("XP physically absent")
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.session.puppet = self.char1

    def command(self, caller, command=None):
        from evennia_notices.commands import CmdNotices

        command = command or CmdNotices()
        command.caller = caller
        command.session = self.session
        command.switches = []
        command.args = ""
        with patch.object(command, "msg") as output:
            command.func()
        return output.call_args.args[0]

    def request(self, character=None):
        request = RequestFactory().get("/notices/")
        request.user = self.account
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        if character is not None:
            request.session["puppet"] = character.pk
        return request

    def test_registered_xp_command_and_rendered_selected_character(self):
        from django.urls import resolve

        from evennia_notices import views
        from evennia_notices.services import set_preference
        from evennia_xp.awards import record_xp
        from evennia_xp.commands import CmdXp
        from evennia_xp.models import CharacterXP, XPLog

        with self.captureOnCommitCallbacks(execute=True):
            record_xp(
                self.char1.pk,
                "2.50",
                XPLog.SourceType.MANUAL_GRANT,
                0,
                week="2026-W09",
                granted_by=self.char2,
                reason="Private audit detail",
            )
            record_xp(self.char2.pk, "46.75", XPLog.SourceType.RP_SESSION, 9001, week="2026-W09")
        command = self.command(self.char1)
        self.assertIn("Manual Grant: +2.50", command)
        route = resolve("/notices/")
        request = self.request(self.char1)
        response = route.func(request, **route.kwargs).render()
        self.assertContains(response, "Manual Grant: +2.50")
        self.assertContains(views.preferences(request).render(), ">XP<")
        for text in ("Private audit detail", self.char2.key, "46.75", "|w"):
            self.assertNotIn(text, command)
            self.assertNotContains(response, text)
        self.assertNotContains(route.func(self.request(), **route.kwargs).render(), "+2.50")
        self.assertNotIn("+2.50", self.command(self.char2))
        self.session.puppet = None
        self.assertNotIn("+2.50", self.command(self.account))
        context = from_web(request)
        [item] = project(context, source="xp")
        mutate(context, item.notice.public_ref, "read")
        self.assertContains(views.inbox(request, history=True).render(), "+2.50")
        mutate(context, item.notice.public_ref, "clear")
        self.assertNotContains(views.inbox(request).render(), "+2.50")
        self.assertContains(views.inbox(request, history=True).render(), "Cleared")
        set_preference(context, "xp", "off")
        self.session.puppet = self.char1
        self.assertIn("2.50", self.command(self.char1, CmdXp()))
        xp_route = resolve("/xp/")
        self.assertContains(xp_route.func(request, **xp_route.kwargs).render(), "2.50")
        self.assertEqual(CharacterXP.objects.get(character_id=self.char1.pk).current_balance, 2.5)
        self.assertEqual(DeliveryReceipt.objects.filter(source="xp").count(), 2)

    def test_puppet_signal_recovers_pending_legacy_for_exact_character(self):
        from evennia.server.signals import SIGNAL_OBJECT_POST_PUPPET

        from evennia_xp.models import CharacterXP, XPLog

        CharacterXP.objects.create(character_id=self.char1.pk, last_payout_week="2025-W52")
        XPLog.objects.create(
            character_id=self.char1.pk,
            week="2025-W52",
            amount=1,
            source_type=XPLog.SourceType.RP_SESSION,
            source_ref_id=105,
        )
        self.char1.attributes.add("last_xp_summary_week", "2026-W01")
        with patch.object(self.session, "msg") as message:
            with self.captureOnCommitCallbacks(execute=True):
                self.session.puppet = None
                SIGNAL_OBJECT_POST_PUPPET.send(sender=self.char1, session=self.session)
            self.assertFalse(DeliveryReceipt.objects.filter(source="xp").exists())
            self.session.puppet = self.char1
            with self.captureOnCommitCallbacks(execute=True):
                SIGNAL_OBJECT_POST_PUPPET.send(sender=self.char1, session=self.session)
            self.assertEqual(DeliveryReceipt.objects.filter(source="xp").count(), 1)
            SIGNAL_OBJECT_POST_PUPPET.send(sender=self.char1, session=self.session)
            self.assertTrue(any("1 unread alerts" in str(call) for call in message.call_args_list))
