# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""XP and Evennia alone can stage and deliver a weekly summary."""

import importlib.metadata
import secrets
from importlib.util import find_spec
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.apps import apps
from django.conf import settings
from django.test import TransactionTestCase, override_settings
from evennia.objects.objects import DefaultCharacter
from evennia.utils import create

from .awards import record_xp
from .models import CharacterXP, XPLog, XPNoticeReceipt
from .summary import SUMMARY_WEEK_ATTRIBUTE, notify_xp_summary
from .typeclasses import XPSummaryCharacterMixin


class SummaryCharacter(XPSummaryCharacterMixin, DefaultCharacter):
    pass


class NoticeFixture:
    def setUp(self):
        super().setUp()
        self.account = create.create_account(
            "XP Owner", "xp-owner@example.invalid", secrets.token_urlsafe(32)
        )
        self.other = create.create_account(
            "XP Other", "xp-other@example.invalid", secrets.token_urlsafe(32)
        )
        self.character = create.create_object(SummaryCharacter, key="XP", nohome=True)
        self.account.characters.add(self.character)
        self.character.account = self.account
        self.character.msg = Mock()
        self.sessions = [self.make_session()]
        connected = patch("evennia_xp.notices._registered_sessions", lambda: self.sessions)
        connected.start()
        self.addCleanup(connected.stop)

    def make_session(self):
        return SimpleNamespace(
            logged_in=True,
            msg=Mock(),
            get_account=lambda: self.account,
            get_puppet=lambda: self.character,
        )

    def award(self, ref=1, week="2026-W09"):
        return record_xp(
            self.character.pk,
            "1.25",
            XPLog.SourceType.RP_SESSION,
            ref,
            week=week,
            character_name=self.character.key,
        )

    def show(self):
        return notify_xp_summary(self.character)


@override_settings(NOTICES_ENABLED=False)
class StandaloneNoticeTests(NoticeFixture, TransactionTestCase):
    def test_core_profile_mixin_and_award(self):
        for name in getattr(settings, "XP_ABSENT_PARTNERS", []):
            self.assertIsNone(find_spec(name))
            self.assertFalse(apps.is_installed(name))
            with self.assertRaises(importlib.metadata.PackageNotFoundError):
                importlib.metadata.distribution(name.replace("_", "-"))

        self.award()
        with patch.object(DefaultCharacter, "at_post_puppet"):
            self.character.at_post_puppet()
        self.assertEqual(self.character.msg.call_count, 1)
        self.assertIn("1.25 XP total", self.character.msg.call_args.args[0])
        self.assertEqual(self.character.attributes.get(SUMMARY_WEEK_ATTRIBUTE), "2026-W09")
        self.assertEqual(CharacterXP.objects.get().current_balance, 1.25)
        self.assertFalse(self.show())

    def test_unpuppet_after_claim_before_write_returns_pending_and_retries_once(self):
        self.award()
        session = self.sessions[0]
        with patch(
            "evennia_xp.summary.uses_screenreader", side_effect=lambda _: self.sessions.clear()
        ):
            self.assertFalse(self.show())
        self.character.msg.assert_not_called()
        self.assertEqual(XPNoticeReceipt.objects.get().state, XPNoticeReceipt.State.PENDING)
        self.sessions.append(session)
        self.assertTrue(self.show())
        self.assertFalse(self.show())
        self.character.msg.assert_called_once()

    def test_wrong_account_or_connection_after_render_never_exposes_payout(self):
        self.award()
        session = self.sessions[0]

        def switch_account(_):
            session.get_account = lambda: self.other
            self.character.account = self.other

        with patch("evennia_xp.summary.uses_screenreader", side_effect=switch_account):
            self.assertFalse(self.show())
        self.assertFalse(self.show())
        self.character.msg.assert_not_called()

    def test_new_current_payout_after_render_leaves_old_attempt_unconsumed(self):
        self.award()
        with patch(
            "evennia_xp.summary.uses_screenreader",
            side_effect=lambda _: bool(self.award(2, "2026-W10")),
        ):
            self.assertFalse(self.show())
        self.character.msg.assert_not_called()
        self.assertEqual(
            XPNoticeReceipt.objects.get(week="2026-W09").state, XPNoticeReceipt.State.PENDING
        )
        self.assertTrue(self.show())
        self.assertIn("2026-W10", self.character.msg.call_args.args[0])

    def test_staff_may_play_unowned_puppet_but_not_receive_someone_elses_xp(self):
        self.award()
        self.character.account = self.other
        self.sessions[0].get_account = lambda: self.other
        self.assertFalse(self.show())
        self.account.characters.remove(self.character)
        self.assertTrue(self.show())

    def test_one_failing_session_does_not_stop_the_other(self):
        self.award()
        self.sessions.append(self.make_session())
        self.character.msg.side_effect = [RuntimeError("first writer failed"), None]
        self.assertTrue(self.show())
        self.assertEqual(self.character.msg.call_count, 2)
        self.assertEqual(XPNoticeReceipt.objects.get().state, XPNoticeReceipt.State.DELIVERED)

    def test_finalize_only_retry_never_calls_socket_again(self):
        self.award()
        with patch("evennia_xp.notices._finalize", side_effect=RuntimeError("DB unavailable")):
            self.assertTrue(self.show())
        self.assertEqual(XPNoticeReceipt.objects.get().state, XPNoticeReceipt.State.ATTEMPTING)
        self.assertFalse(self.show())
        self.character.msg.assert_called_once()
        self.assertEqual(XPNoticeReceipt.objects.get().state, XPNoticeReceipt.State.DELIVERED)

    def make_guest(self):
        from evennia.accounts.accounts import DefaultGuest

        from .notices import _guest_claims

        guest = create.create_account(
            "XP Disposable", "", secrets.token_urlsafe(32), typeclass=DefaultGuest
        )
        self.account.characters.remove(self.character)
        guest.characters.add(self.character)
        self.account = guest
        self.character.account = guest
        self.addCleanup(_guest_claims.clear)

    def test_guest_skipped_write_remains_unconsumed_without_persistence(self):
        self.make_guest()
        with patch("evennia_xp.notices.summary_text", side_effect=ValueError("pre-write")):
            self.award()
        self.character.msg.assert_not_called()
        self.assertTrue(self.show())
        self.assertFalse(self.show())
        self.character.msg.assert_called_once()
        self.assertFalse(XPNoticeReceipt.objects.exists())
        self.assertIsNone(self.character.attributes.get(SUMMARY_WEEK_ATTRIBUTE))

    def test_offline_guest_is_never_replayed_on_later_connection(self):
        self.make_guest()
        self.sessions.clear()
        self.award()
        self.sessions.append(self.make_session())
        self.assertFalse(self.show())
        self.character.msg.assert_not_called()
        self.assertFalse(XPNoticeReceipt.objects.exists())

    def test_latest_standalone_week_and_backdated_first_payment(self):
        self.award(1, "2026-W09")
        self.award(2, "2026-W10")
        self.assertTrue(self.show())
        self.assertIn("2026-W10", self.character.msg.call_args.args[0])
        self.award(3, "2026-W09")
        self.assertFalse(self.show())
        self.award(4, "2025-W52")
        self.assertTrue(self.show())
        self.assertEqual(self.character.attributes.get(SUMMARY_WEEK_ATTRIBUTE), "2025-W52")
