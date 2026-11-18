# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real account outcome adapter, rendered Inbox and safe self opt-in."""

from importlib import import_module

from django.conf import settings
from django.db import connection
from django.test import RequestFactory, TransactionTestCase, override_settings
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTestMixin

from evennia_jobs.models import RequestDecision
from evennia_links.notices import NoticeContext
from evennia_links.test_transactions import committed_race
from evennia_moderation.models import Application, Notice, Referral
from evennia_notices import views
from evennia_notices.services import mutate, project
from world.sandbox.notices_seed import emit_moderation_demo_notices


@override_settings(ROOT_URLCONF="web.urls")
class ModerationNoticeSeams(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.account.characters.add(self.char2)
        self.factory = RequestFactory()

    def request(self, character=None):
        request = self.factory.get("/notices/")
        request.user = self.account
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        if character is not None:
            request.session["puppet"] = character.pk
        return request

    def test_account_fixture_rendered_shared_read_clear_and_no_workflow_mutation(self):
        before = (
            Application.objects.count(),
            Referral.objects.count(),
            RequestDecision.objects.count(),
        )
        empty = views.inbox(self.request()).render()
        self.assertNotContains(empty, "Example Moderation outcome")
        row = emit_moderation_demo_notices(self.account, self.char1)
        first = project(NoticeContext(self.account, self.char1))[0]
        self.assertEqual(first.label, "Moderation")
        response = views.inbox(self.request(self.char1)).render()
        self.assertContains(response, "Example Moderation outcome")
        detail = views.detail(self.request(self.char2), first.notice.public_ref).render()
        self.assertContains(detail, "simulated referral")
        self.assertEqual(first.actions, ())
        self.assertContains(detail, "No source action is required")
        self.assertTrue(project(NoticeContext(self.account, self.char2))[0].unread)
        request = self.request(self.char2)
        request.method = "POST"
        self.assertEqual(views.change(request, first.notice.public_ref, "read").status_code, 302)
        self.assertFalse(project(NoticeContext(self.account, self.char2))[0].unread)
        self.assertFalse(project(NoticeContext(self.account))[0].unread)
        mutate(NoticeContext(self.account), first.notice.public_ref, "clear")
        self.assertEqual(project(NoticeContext(self.account, self.char1)), [])
        emit_moderation_demo_notices(self.account, self.char2)
        self.assertEqual(project(NoticeContext(self.account)), [])
        self.assertEqual(Notice.objects.filter(kind="example").count(), 1)
        self.assertEqual(
            before,
            (
                Application.objects.count(),
                Referral.objects.count(),
                RequestDecision.objects.count(),
            ),
        )
        self.assertEqual(row.account_id, self.account.pk)
        history = views.inbox(self.request(), history=True).render()
        self.assertContains(history, "Example Moderation outcome")
        self.assertContains(views.preferences(self.request()).render(), "Moderation")

    def test_other_account_cannot_opt_in_a_foreign_character_or_read_source(self):
        with self.assertRaises(ValueError):
            emit_moderation_demo_notices(self.account2, self.char1)
        emit_moderation_demo_notices(self.account)
        self.assertEqual(project(NoticeContext(self.account2)), [])

    def test_edited_fixture_and_marker_cannot_change_real_admissions(self):
        from evennia.server.models import ServerConfig

        row = emit_moderation_demo_notices(self.account)
        original = row.envelope
        Notice.objects.filter(pk=row.pk).update(envelope={})
        with self.assertRaises(ValueError):
            emit_moderation_demo_notices(self.account)
        row.refresh_from_db()
        self.assertEqual(row.envelope, {})
        Notice.objects.filter(pk=row.pk).update(envelope=original)
        ServerConfig.objects.conf(
            f"sandbox_moderation_notice_example_{self.account.pk}", {"notice": "bad"}
        )
        with self.assertRaises(ValueError):
            emit_moderation_demo_notices(self.account)
        self.assertFalse(Application.objects.exists())
        self.assertFalse(Referral.objects.exists())


class ModerationExampleRaces(EvenniaTestMixin, TransactionTestCase):
    """Concurrent self opt-in allocates one synthetic row without domain decisions."""

    def test_simultaneous_opt_in_is_one_account_outcome(self):
        if connection.vendor == "sqlite" and "mode=memory" in connection.settings_dict["NAME"]:
            self.skipTest("Run with a file-backed TEST database")
        from evennia.accounts.models import AccountDB
        from evennia.server.models import ServerConfig

        before = (
            Application.objects.count(),
            Referral.objects.count(),
            RequestDecision.objects.count(),
        )
        committed_race(
            lambda: emit_moderation_demo_notices(AccountDB.objects.get(pk=self.account.pk)),
            lambda: emit_moderation_demo_notices(AccountDB.objects.get(pk=self.account.pk)),
        )
        self.assertEqual(Notice.objects.filter(kind="example", account=self.account).count(), 1)
        self.assertEqual(
            ServerConfig.objects.filter(
                db_key=f"sandbox_moderation_notice_example_{self.account.pk}"
            ).count(),
            1,
        )
        self.assertEqual(
            before,
            (
                Application.objects.count(),
                Referral.objects.count(),
                RequestDecision.objects.count(),
            ),
        )
