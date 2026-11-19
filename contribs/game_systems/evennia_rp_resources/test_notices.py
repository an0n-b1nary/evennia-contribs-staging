# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Committed Resources awards through standalone and real optional Inbox routes."""

from secrets import token_urlsafe
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import Mock, patch
from uuid import uuid4

from django.apps import apps
from django.db import transaction
from django.test import TransactionTestCase, override_settings
from evennia.utils.create import create_account, create_object

from . import batch, notices, payouts
from .models import PlotPayoutReceipt, PlotPayoutRun, ResourceDefinition, ResourceNoticeReceipt
from .services import grant, spend, total_held
from .summary import notify_plot_summary, notify_resource_summary

State = ResourceNoticeReceipt.State
SOURCES = {"resources": "evennia_rp_resources.integrations.notices.ResourcesNoticeSource"}


@override_settings(
    RP_RESOURCES_REVEALED=True,
    RP_RESOURCES_OPEN_TERRAINS=[],
    RP_RESOURCES_WEEKLY_QUANTITY=3,
    RP_RESOURCES_BASE_CAP=9,
)
class ResourceNoticeFixture(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.account = create_account("Resources Owner", None, token_urlsafe(32))
        self.other = create_account("Resources Other", None, token_urlsafe(32))
        self.character = create_object("evennia.DefaultCharacter", key="Resources", nohome=True)
        self.account.characters.add(self.character)
        self.character.account = self.account
        self.character.msg = Mock()
        self.session = self.make_session()
        self.sessions = [self.session]
        registered = patch.object(
            notices, "_registered_sessions", side_effect=lambda: self.sessions
        )
        registered.start()
        self.addCleanup(registered.stop)
        ResourceDefinition.objects.create(key="grain", name="Grain", category="provisions")

    def make_session(self):
        return SimpleNamespace(
            logged_in=True,
            msg=Mock(),
            get_account=lambda: self.account,
            get_puppet=lambda: self.character,
        )

    def award(self, week, **kwargs):
        result = batch.run_weekly_batch(week, characters=[self.character], **kwargs)
        self.assertEqual(result["errors"], [])
        return result

    def plot_award(self, plot, *, paid=True):
        run = PlotPayoutRun.objects.create(
            thread_id=plot.pk,
            plot_name="Old secret title",
            amounts={"grain": 2},
            approvals={"grain": self.character.pk},
        )
        receipt = PlotPayoutReceipt.objects.create(
            run=run, character_id=self.character.pk, character_name=self.character.key
        )
        if paid:
            self.assertEqual(payouts.deliver(run.pk)["paid"], [self.character.pk])
        receipt.refresh_from_db()
        return receipt


@override_settings(NOTICES_ENABLED=False)
class StandaloneResourceNoticeTests(ResourceNoticeFixture):
    def test_no_write_after_unpuppet_returns_pending_and_retries_once(self):
        self.award("week-1")
        send = notices._send

        def disconnect(*args):
            self.session.logged_in = False
            return send(*args)

        with patch.object(notices, "_send", side_effect=disconnect):
            self.assertFalse(notify_resource_summary(self.character))
        self.assertEqual(ResourceNoticeReceipt.objects.get().state, State.PENDING)
        self.assertIsNone(self.character.attributes.get(notices.WEEK_KEY))
        self.session.logged_in = True
        self.assertTrue(notify_resource_summary(self.character))
        self.assertFalse(notify_resource_summary(self.character))
        self.character.msg.assert_called_once()

    def test_hidden_after_render_returns_claim_to_pending_without_a_write(self):
        from django.conf import settings

        self.award("week-1")
        text = notices._standalone_text

        def hide(*args):
            result = text(*args)
            settings.RP_RESOURCES_REVEALED = False
            return result

        with (
            override_settings(RP_RESOURCES_REVEALED=True),
            patch.object(notices, "_standalone_text", side_effect=hide),
        ):
            self.assertFalse(notify_resource_summary(self.character))
        self.character.msg.assert_not_called()
        self.assertEqual(ResourceNoticeReceipt.objects.get().state, State.PENDING)
        self.assertTrue(notify_resource_summary(self.character))
        self.character.msg.assert_called_once()

    def test_losing_last_roster_owner_after_render_does_not_change_claim_scope(self):
        self.award("week-1")
        render = notices._standalone_text

        def remove_owner(*args):
            message = render(*args)
            self.account.characters.remove(self.character)
            return message

        with patch.object(notices, "_standalone_text", side_effect=remove_owner):
            self.assertFalse(notify_resource_summary(self.character))
        self.character.msg.assert_not_called()
        self.assertEqual(ResourceNoticeReceipt.objects.get().state, State.PENDING)
        self.account.characters.add(self.character)
        self.assertTrue(notify_resource_summary(self.character))
        self.character.msg.assert_called_once()

    def test_each_session_is_independent_and_unknown_write_is_never_replayed(self):
        self.sessions.append(self.make_session())
        self.award("week-1")
        self.character.msg.side_effect = [RuntimeError("write started"), None]
        self.assertTrue(notify_resource_summary(self.character))
        self.assertEqual(self.character.msg.call_count, 2)
        self.assertEqual(ResourceNoticeReceipt.objects.get().state, State.DELIVERED)
        self.award("week-2")
        self.character.msg.side_effect = RuntimeError("write started")
        self.assertFalse(notify_resource_summary(self.character))
        self.assertEqual(
            ResourceNoticeReceipt.objects.get(weekly__week="week-2").state, State.UNCERTAIN
        )
        self.character.msg.reset_mock()
        self.assertFalse(notify_resource_summary(self.character))
        self.character.msg.assert_not_called()

    def test_confirmed_write_retries_only_failed_terminal_settlement(self):
        self.award("week-1")
        self.addCleanup(notices._waiting.clear)
        with patch.object(notices, "_finalize", side_effect=RuntimeError("database unavailable")):
            self.assertTrue(notify_resource_summary(self.character))
        self.assertEqual(ResourceNoticeReceipt.objects.get().state, State.ATTEMPTING)
        self.assertFalse(notify_resource_summary(self.character))
        self.assertEqual(ResourceNoticeReceipt.objects.get().state, State.DELIVERED)
        self.assertEqual(self.character.attributes.get(notices.WEEK_KEY), "week-1")
        self.character.msg.assert_called_once()

    def test_latest_only_and_cap_checkpoint_with_recovery(self):
        grant(self.character, "grain", 9)
        self.award("week-1")
        self.award("week-2")
        self.assertTrue(notify_resource_summary(self.character))
        self.assertIn("Your stores are full.", self.character.msg.call_args.args[0])
        self.assertEqual(
            ResourceNoticeReceipt.objects.get(weekly__week="week-1").state, State.SUPERSEDED
        )
        self.award("week-3")
        self.assertFalse(notify_resource_summary(self.character))
        self.assertEqual(self.character.attributes.get(notices.WEEK_KEY), "week-3")
        self.assertEqual(
            ResourceNoticeReceipt.objects.get(weekly__week="week-3").state, State.SUPPRESSED
        )
        spend(self.character, "grain", 6, "staff")
        self.award("week-4")
        self.assertTrue(notify_resource_summary(self.character))
        self.assertFalse(self.character.attributes.get(notices.FULL_KEY))

    def test_preparation_in_outer_transaction_waits_for_commit(self):
        self.award("week-1")
        with transaction.atomic():
            self.assertFalse(notify_resource_summary(self.character))
            self.character.msg.assert_not_called()
            transaction.set_rollback(True)
        self.character.msg.assert_not_called()
        self.assertTrue(notify_resource_summary(self.character))

    def test_guest_retry_is_transient_and_limited_to_original_connections(self):
        from evennia.accounts.accounts import DefaultGuest

        guest = create_account("Resources Guest", None, token_urlsafe(32), typeclass=DefaultGuest)
        self.account.characters.remove(self.character)
        guest.characters.add(self.character)
        self.account = self.character.account = guest
        self.addCleanup(notices._guests.clear)
        with (
            patch("twisted.internet.reactor.callLater"),
            patch.object(notices, "_standalone_text", side_effect=RuntimeError("pre-write")),
        ):
            self.award("guest-week")
        self.character.msg.assert_not_called()
        self.assertFalse(ResourceNoticeReceipt.objects.exists())
        self.sessions[:] = [self.make_session()]
        self.assertFalse(notify_resource_summary(self.character))
        self.sessions[:] = [self.session]
        self.assertTrue(notify_resource_summary(self.character))
        self.assertFalse(notify_resource_summary(self.character))
        self.character.msg.assert_called_once()
        self.assertIsNone(self.character.attributes.get(notices.WEEK_KEY))

    @skipUnless(apps.is_installed("evennia_plots"), "Optional Plots is absent")
    def test_plot_privacy_change_after_claim_means_no_write(self):
        from evennia_plots.models import PlotThread

        outsider = create_object("evennia.DefaultCharacter", key="Plot owner", nohome=True)
        plot = PlotThread.create_thread("Current title", outsider)
        plot.privacy = PlotThread.Privacy.PUBLIC
        plot.save(update_fields=["privacy"])
        award = self.plot_award(plot)
        send = notices._send

        def close_plot(*args):
            PlotThread.objects.filter(pk=plot.pk).update(privacy=PlotThread.Privacy.PRIVATE)
            return send(*args)

        with patch.object(notices, "_send", side_effect=close_plot):
            self.assertFalse(notify_plot_summary(self.character))
        self.character.msg.assert_not_called()
        award.refresh_from_db()
        self.assertIsNone(award.notified_at)
        self.assertEqual(award.notice_receipt.state, State.PENDING)
        PlotThread.objects.filter(pk=plot.pk).update(privacy=PlotThread.Privacy.PUBLIC)
        self.assertTrue(notify_plot_summary(self.character))
        award.refresh_from_db()
        self.assertIsNotNone(award.notified_at)
        self.assertEqual(total_held(self.character), 2)

    @skipUnless(apps.is_installed("evennia_plots"), "Optional Plots is absent")
    def test_paid_receipt_revoked_after_render_is_pending_until_valid_again(self):
        from evennia_plots.models import PlotThread

        plot = PlotThread.create_thread("Current plot", self.character)
        award = self.plot_award(plot)
        paid_at = award.paid_at
        render = notices._standalone_text

        def revoke(*args):
            message = render(*args)
            PlotPayoutReceipt.objects.filter(pk=award.pk).update(paid_at=None)
            return message

        with patch.object(notices, "_standalone_text", side_effect=revoke):
            self.assertFalse(notify_plot_summary(self.character))
        self.character.msg.assert_not_called()
        award.refresh_from_db()
        self.assertEqual(award.notice_receipt.state, State.PENDING)
        self.assertIsNone(award.notified_at)

        PlotPayoutReceipt.objects.filter(pk=award.pk).update(paid_at=paid_at)
        self.assertTrue(notify_plot_summary(self.character))
        self.assertFalse(notify_plot_summary(self.character))
        self.character.msg.assert_called_once()


@skipUnless(apps.is_installed("evennia_notices"), "Optional Inbox is absent")
@override_settings(NOTICES_ENABLED=True, LINKS_NOTICE_SOURCES=SOURCES)
class InboxResourceNoticeTests(ResourceNoticeFixture):
    def context(self, account=None, *, session=False):
        from evennia_links.notices import NoticeContext

        return NoticeContext(
            account or self.account, self.character, self.session if session else None
        )

    def project(self, context=None):
        from evennia_notices.services import project

        return project(context or self.context(), source=notices.SOURCE)

    def prepare(self):
        from .integrations.notices import ResourcesNoticeSource

        ResourcesNoticeSource().prepare(self.context(session=True))

    def test_reveal_changed_during_evaluation_hides_summary_count(self):
        from django.conf import settings

        from evennia_notices.services import summarize

        from .integrations import notices as projection

        self.award("week-1")
        load_plots = projection._plots

        def mask(*args):
            plots = load_plots(*args)
            settings.RP_RESOURCES_REVEALED = False
            return plots

        with (
            override_settings(RP_RESOURCES_REVEALED=True),
            patch.object(projection, "_plots", side_effect=mask),
        ):
            self.assertEqual(summarize(self.context(session=True)), (0, 0))
        self.session.msg.assert_not_called()
        self.assertEqual(summarize(self.context(session=True)), (1, 0))

    def test_temporary_guest_puppet_leaves_all_owned_awards_pending(self):
        from evennia.accounts.accounts import DefaultGuest

        guest = create_account(
            "Temporary controller", None, token_urlsafe(32), typeclass=DefaultGuest
        )
        self.character.account = guest
        self.award("week-1")
        self.award("week-2")
        self.assertEqual(
            set(ResourceNoticeReceipt.objects.values_list("weekly__week", "state")),
            {("week-1", State.PENDING), ("week-2", State.PENDING)},
        )
        self.character.msg.assert_not_called()

        self.character.account = self.account
        self.prepare()
        self.assertEqual(len(self.project()), 2)
        self.character.msg.assert_not_called()

    def test_commit_dry_run_and_no_replay_after_clear_and_backend_switch(self):
        from evennia_notices.models import DeliveryReceipt
        from evennia_notices.services import mutate

        self.award("preview", dry_run=True)
        with transaction.atomic():
            self.award("rolled-back")
            self.assertFalse(DeliveryReceipt.objects.exists())
            transaction.set_rollback(True)
        self.assertFalse(ResourceNoticeReceipt.objects.exists())
        self.award("week-1")
        self.award("week-1")
        [item] = self.project()
        self.assertEqual(
            item.text, "This week you gathered: 3 Grain. Use +resources to view your stores."
        )
        with self.assertRaisesRegex(ValueError, "Invalid notice context"):
            self.project(self.context(self.other))
        mutate(self.context(), item.notice.public_ref, "clear")
        with override_settings(NOTICES_ENABLED=False):
            self.assertFalse(notify_resource_summary(self.character))
        self.prepare()
        self.assertEqual(self.project(), [])
        self.assertEqual(DeliveryReceipt.objects.filter(source="resources").count(), 1)
        self.assertEqual(total_held(self.character), 3)

    def test_dark_only_latest_and_retained_notices_hide_then_recover(self):
        from evennia_notices.services import maintain, set_preference, summarize

        self.award("visible")
        set_preference(self.context(), "resources", "off")
        with override_settings(RP_RESOURCES_REVEALED=False):
            self.award("dark-1")
            self.award("dark-2")
            self.prepare()
            self.assertEqual(ResourceNoticeReceipt.objects.count(), 1)
            self.assertEqual(self.project(), [])
            self.assertEqual(summarize(self.context()), (0, 0))
            maintain()
        set_preference(self.context(), "resources", "summary")
        self.prepare()
        self.assertEqual(
            set(ResourceNoticeReceipt.objects.values_list("weekly__week", flat=True)),
            {"visible", "dark-2"},
        )
        self.assertEqual(len(self.project()), 2)

    def test_reveal_flip_inside_preference_off_routing_rolls_back_acknowledgement(self):
        from django.conf import settings

        from evennia_notices.models import DeliveryReceipt
        from evennia_notices.services import route, set_preference

        set_preference(self.context(), "resources", "off")

        def hide(*args, **kwargs):
            settings.RP_RESOURCES_REVEALED = False
            return route(*args, **kwargs)

        with (
            override_settings(RP_RESOURCES_REVEALED=True),
            patch("evennia_notices.services.route", side_effect=hide),
        ):
            self.award("reveal-race")
        self.assertEqual(ResourceNoticeReceipt.objects.get().state, State.PENDING)
        self.assertFalse(DeliveryReceipt.objects.filter(source="resources").exists())
        self.assertIsNone(self.character.attributes.get(notices.WEEK_KEY))
        set_preference(self.context(), "resources", "summary")
        self.prepare()
        self.assertEqual(len(self.project()), 1)

    def test_pending_full_week_keeps_legacy_cap_baseline_after_newer_fallback(self):
        self.character.attributes.add(notices.FULL_KEY, True)
        grant(self.character, "grain", 9)
        # Leave the zero-gain full week pending before its cap decision.
        with patch.object(notices, "_route_fresh"):
            self.award("pending-full")
        with override_settings(NOTICES_ENABLED=False):
            spend(self.character, "grain", 6, "room again")
            self.award("standalone-nonfull")
            self.assertTrue(notify_resource_summary(self.character))
        self.assertFalse(self.character.attributes.get(notices.FULL_KEY))
        self.prepare()
        old = ResourceNoticeReceipt.objects.get(weekly__week="pending-full")
        self.assertEqual(old.state, State.SUPPRESSED)
        self.assertFalse(old.full_warning)
        self.assertEqual(self.character.attributes.get(notices.WEEK_KEY), "standalone-nonfull")
        self.assertEqual(self.project(), [])

    def test_fresh_immediate_routing_retries_older_award_quietly(self):
        from evennia_notices.services import set_preference

        set_preference(self.context(), "resources", "immediate")
        with patch("evennia_notices.services.route", side_effect=RuntimeError("transient")):
            self.award("first-pending")
        self.assertEqual(ResourceNoticeReceipt.objects.get().state, State.PENDING)
        with patch(
            "evennia.server.sessionhandler.SESSIONS.get_sessions", return_value=self.sessions
        ):
            self.award("fresh")
        self.assertEqual(len(self.project()), 2)
        self.session.msg.assert_called_once()

    def test_older_interrupted_attempt_does_not_starve_later_award(self):
        with override_settings(NOTICES_ENABLED=False):
            self.award("week-1")
            ResourceNoticeReceipt.objects.update(state=State.ATTEMPTING, attempt=uuid4())
        self.award("week-2")
        self.assertEqual(len(self.project()), 1)
        self.assertEqual(
            ResourceNoticeReceipt.objects.get(weekly__week="week-1").state, State.ATTEMPTING
        )

    @skipUnless(apps.is_installed("evennia_plots"), "Optional Plots is absent")
    def test_private_plot_retained_but_only_authorized_viewers_see_redacted_award(self):
        from evennia_notices.services import summarize
        from evennia_plots.models import PlotOwner, PlotThread

        outsider = create_object("evennia.DefaultCharacter", key="Plot owner", nohome=True)
        plot = PlotThread.create_thread("Current private sentinel", outsider)
        plot.privacy = PlotThread.Privacy.PRIVATE
        plot.save(update_fields=["privacy"])
        self.other.characters.add(self.character)
        award = self.plot_award(plot)
        self.assertEqual(award.notice_receipt.state, State.TRANSFERRED)
        self.assertIsNone(award.notified_at)
        self.assertEqual(summarize(self.context()), (0, 0))
        self.assertEqual(self.project(), [])
        # The attached account's elevated permission cannot leak to its shared roster peer.
        self.account.is_superuser = True
        self.account.save(update_fields=["is_superuser"])
        self.assertEqual(self.project(self.context(self.other)), [])
        [item] = self.project(self.context(session=True))
        self.assertIn("Private plot award: 2 grain", item.text)
        plot.owners.all().delete()
        PlotOwner.objects.create(
            plot=plot, character=self.character, character_name=self.character.key
        )
        [item] = self.project(self.context(self.other))
        self.assertNotIn("sentinel", item.text)
        self.assertNotIn("Old secret title", item.text)
        self.assertEqual(item.actions, ())
        plot.privacy = PlotThread.Privacy.INVITE_ONLY
        plot.save(update_fields=["privacy"])
        self.assertIn(plot.name, self.project()[0].text)

    @skipUnless(apps.is_installed("evennia_plots"), "Optional Plots is absent")
    @override_settings(NOTICES_ROUTINE_LIMIT=1)
    def test_compaction_rechecks_current_plot_permissions_and_counts(self):
        from evennia_notices.services import maintain, summarize
        from evennia_plots.models import PlotThread

        outsider = create_object("evennia.DefaultCharacter", key="Plot owner", nohome=True)
        plot = PlotThread.create_thread("Hidden sentinel", outsider)
        self.plot_award(plot)
        self.award("compacted-week")
        [item] = self.project()
        self.assertTrue(item.notice.is_compacted)
        self.assertEqual(len(item.events), 2)
        self.assertIn("You received resource awards.", item.text)
        plot.privacy = PlotThread.Privacy.PRIVATE
        plot.save(update_fields=["privacy"])
        maintain()
        [item] = self.project()
        self.assertEqual(len(item.events), 1)
        self.assertNotIn("Hidden sentinel", item.text)
        self.assertIn("This week you gathered", item.text)
        self.assertEqual(summarize(self.context()), (1, 0))
        plot.privacy = PlotThread.Privacy.PUBLIC
        plot.save(update_fields=["privacy"])
        self.assertEqual(len(self.project()[0].events), 2)

    @skipUnless(not apps.is_installed("evennia_plots"), "Optional Plots is installed")
    def test_paid_historical_plot_is_held_while_weekly_still_routes(self):
        from django.utils import timezone

        run = PlotPayoutRun.objects.create(thread_id=1, plot_name="Hidden", amounts={"grain": 2})
        PlotPayoutReceipt.objects.create(
            run=run,
            character_id=self.character.pk,
            character_name=self.character.key,
            paid_at=timezone.now(),
        )
        self.award("visible")
        self.prepare()
        self.assertEqual(len(self.project()), 1)
        self.assertFalse(ResourceNoticeReceipt.objects.filter(plot__isnull=False).exists())
