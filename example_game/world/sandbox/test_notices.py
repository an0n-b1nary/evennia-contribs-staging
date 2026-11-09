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
