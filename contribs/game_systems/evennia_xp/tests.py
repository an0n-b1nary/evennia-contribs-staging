# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Tests for evennia_xp.

Covers models, awards, batch engine (registry), gating seam, commands,
web view, REST API, and Script.

Run:
    evennia test --settings test_xp_settings.py evennia_xp
"""

from datetime import UTC
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, override_settings
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from evennia_xp.awards import record_xp
from evennia_xp.batch import (
    Award,
    BatchSummary,
    _last_monday_00_utc,
    _week_str_from_window_end,
    _window_end_from_week_str,
    run_weekly_batch,
)
from evennia_xp.models import CharacterXP, XPLog

# ---------------------------------------------------------------------------
# Module-level fixtures for registry tests (must be importable by dotted path)
# ---------------------------------------------------------------------------

_SWEEP_LOG = []
_HOOK_LOG = []


def _test_collector(window_end):
    """Yields one Award for character_id=1 (source_ref_id=9001)."""
    yield Award(
        character_id=1,
        amount=Decimal("2.0"),
        source_type=XPLog.SourceType.RP_SESSION,
        source_ref_id=9001,
        multiplier=Decimal("1.0"),
        reason="test",
    )


def _test_collector_b(window_end):
    """Second collector for sources= filter tests (source_ref_id=9002)."""
    yield Award(
        character_id=1,
        amount=Decimal("1.0"),
        source_type=XPLog.SourceType.LORE_AUTHORED,
        source_ref_id=9002,
        multiplier=Decimal("1.0"),
        reason="test-b",
    )


def _test_sweep(window_end):
    _SWEEP_LOG.append(window_end)


def _test_hook(window_end, awards, week_label):
    _HOOK_LOG.append((window_end, awards, week_label))


def _test_multiplier_resolver(source, *, thread=None, room=None, character=None):
    """Returns 0.5 for rp_session, 1.0 otherwise."""
    if source == "rp_session":
        return Decimal("0.5")
    return Decimal("1.0")


def _broken_resolver(source, **kwargs):
    raise RuntimeError("resolver exploded")


# ---------------------------------------------------------------------------
# Window helpers
# ---------------------------------------------------------------------------


class TestWindowHelpers(EvenniaTest):
    def test_last_monday_round_trip(self):
        """_week_str → _window_end → _week_str should be identity."""
        from datetime import datetime

        # Use a known Monday
        monday = datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC)
        week_label = _week_str_from_window_end(monday)
        self.assertEqual(week_label, "2026-W18")
        recovered = _window_end_from_week_str(week_label)
        self.assertEqual(recovered, monday)

    def test_last_monday_00_utc_is_monday(self):
        import calendar

        window_end = _last_monday_00_utc()
        self.assertEqual(window_end.weekday(), calendar.MONDAY)
        self.assertEqual(window_end.hour, 0)
        self.assertEqual(window_end.minute, 0)


# ---------------------------------------------------------------------------
# record_xp — ledger
# ---------------------------------------------------------------------------


class TestRecordXp(EvenniaTest):
    def test_creates_xplog_and_characterxp(self):
        log = record_xp(
            character_id=42,
            amount=Decimal("1.0"),
            source_type=XPLog.SourceType.RP_SESSION,
            source_ref_id=100,
            week="2026-W20",
            character_name="Alice",
        )
        self.assertIsNotNone(log)
        self.assertEqual(log.character_id, 42)
        self.assertEqual(log.amount, Decimal("1.0"))

        cxp = CharacterXP.objects.get(character_id=42)
        self.assertEqual(cxp.total_earned, Decimal("1.0"))
        self.assertEqual(cxp.current_balance, Decimal("1.0"))

    def test_idempotent_second_call_returns_none(self):
        record_xp(
            character_id=42,
            amount=Decimal("1.0"),
            source_type=XPLog.SourceType.RP_SESSION,
            source_ref_id=200,
            week="2026-W20",
        )
        result = record_xp(
            character_id=42,
            amount=Decimal("1.0"),
            source_type=XPLog.SourceType.RP_SESSION,
            source_ref_id=200,
            week="2026-W20",
        )
        self.assertIsNone(result)
        # Only one row
        self.assertEqual(XPLog.objects.filter(source_ref_id=200).count(), 1)

    def test_manual_grant_always_creates(self):
        log1 = record_xp(
            character_id=42,
            amount=Decimal("1.0"),
            source_type=XPLog.SourceType.MANUAL_GRANT,
            source_ref_id=0,
            reason="test",
        )
        log2 = record_xp(
            character_id=42,
            amount=Decimal("1.0"),
            source_type=XPLog.SourceType.MANUAL_GRANT,
            source_ref_id=0,
            reason="test again",
        )
        self.assertIsNotNone(log1)
        self.assertIsNotNone(log2)
        self.assertNotEqual(log1.pk, log2.pk)
        # source_ref_id set to own pk
        self.assertEqual(log1.source_ref_id, log1.pk)

    def test_characterxp_aggregation_via_F(self):
        record_xp(
            character_id=55,
            amount=Decimal("2.0"),
            source_type=XPLog.SourceType.LORE_AUTHORED,
            source_ref_id=301,
        )
        record_xp(
            character_id=55,
            amount=Decimal("3.0"),
            source_type=XPLog.SourceType.CUTSCENE,
            source_ref_id=302,
        )
        cxp = CharacterXP.objects.get(character_id=55)
        self.assertEqual(cxp.total_earned, Decimal("5.0"))
        self.assertEqual(cxp.current_balance, Decimal("5.0"))

    def test_xp_awarded_signal_fires(self):
        fired = []

        def handler(sender, character_id, xplog, source_type, **kwargs):
            fired.append(character_id)

        from evennia_xp.signals import xp_awarded

        xp_awarded.connect(handler)
        try:
            record_xp(
                character_id=77,
                amount=Decimal("1.0"),
                source_type=XPLog.SourceType.RP_SESSION,
                source_ref_id=401,
            )
            self.assertEqual(fired, [77])
        finally:
            xp_awarded.disconnect(handler)


# ---------------------------------------------------------------------------
# Batch engine via registry
# ---------------------------------------------------------------------------


_COLLECTOR_PATH = "evennia_xp.tests._test_collector"
_COLLECTOR_B_PATH = "evennia_xp.tests._test_collector_b"
_SWEEP_PATH = "evennia_xp.tests._test_sweep"
_HOOK_PATH = "evennia_xp.tests._test_hook"


class TestBatchRegistry(EvenniaTest):
    def setUp(self):
        super().setUp()
        _SWEEP_LOG.clear()
        _HOOK_LOG.clear()

    @override_settings(
        XP_COLLECTORS=[("rp_session", _COLLECTOR_PATH)],
        XP_ANTIGAMING_SWEEPS=[],
        XP_POST_BATCH_HOOKS=[],
    )
    def test_registered_collector_invoked(self):
        summary = run_weekly_batch(week="2026-W20", dry_run=True)
        self.assertEqual(summary.total_awards, 1)
        self.assertEqual(summary.total_xp, Decimal("2.0"))

    @override_settings(XP_COLLECTORS=[], XP_ANTIGAMING_SWEEPS=[], XP_POST_BATCH_HOOKS=[])
    def test_no_collectors_empty_summary(self):
        summary = run_weekly_batch(week="2026-W20")
        self.assertIsInstance(summary, BatchSummary)
        self.assertEqual(summary.total_awards, 0)
        self.assertEqual(summary.total_xp, Decimal("0.00"))
        self.assertEqual(summary.errors, [])

    @override_settings(
        XP_COLLECTORS=[("rp_session", _COLLECTOR_PATH)],
        XP_ANTIGAMING_SWEEPS=[],
        XP_POST_BATCH_HOOKS=[],
    )
    def test_dry_run_writes_nothing(self):
        run_weekly_batch(week="2026-W20", dry_run=True)
        self.assertEqual(XPLog.objects.count(), 0)
        self.assertEqual(CharacterXP.objects.count(), 0)

    @override_settings(
        XP_COLLECTORS=[("rp_session", _COLLECTOR_PATH)],
        XP_ANTIGAMING_SWEEPS=[],
        XP_POST_BATCH_HOOKS=[],
    )
    def test_live_run_writes_rows(self):
        run_weekly_batch(week="2026-W20")
        self.assertEqual(XPLog.objects.filter(source_ref_id=9001).count(), 1)
        cxp = CharacterXP.objects.get(character_id=1)
        self.assertEqual(cxp.total_earned, Decimal("2.0"))

    @override_settings(
        XP_COLLECTORS=[
            ("rp_session", _COLLECTOR_PATH),
            ("lore_authored", _COLLECTOR_B_PATH),
        ],
        XP_ANTIGAMING_SWEEPS=[],
        XP_POST_BATCH_HOOKS=[],
    )
    def test_sources_filter_limits_collectors(self):
        summary = run_weekly_batch(week="2026-W20", sources=["rp_session"])
        self.assertEqual(summary.total_awards, 1)
        self.assertIn("rp_session", summary.by_source)
        self.assertNotIn("lore_authored", summary.by_source)

    @override_settings(
        XP_COLLECTORS=[("rp_session", _COLLECTOR_PATH)],
        XP_ANTIGAMING_SWEEPS=[_SWEEP_PATH],
        XP_POST_BATCH_HOOKS=[],
    )
    def test_antigaming_sweep_runs_before_collectors(self):
        run_weekly_batch(week="2026-W20")
        self.assertEqual(len(_SWEEP_LOG), 1)

    @override_settings(
        XP_COLLECTORS=[("rp_session", _COLLECTOR_PATH)],
        XP_ANTIGAMING_SWEEPS=[],
        XP_POST_BATCH_HOOKS=[_HOOK_PATH],
    )
    def test_post_batch_hook_runs_after(self):
        run_weekly_batch(week="2026-W20")
        self.assertEqual(len(_HOOK_LOG), 1)
        _window_end, awards, week_label = _HOOK_LOG[0]
        self.assertEqual(week_label, "2026-W20")
        self.assertEqual(len(awards), 1)

    @override_settings(
        XP_COLLECTORS=[("rp_session", _COLLECTOR_PATH)],
        XP_ANTIGAMING_SWEEPS=[],
        XP_POST_BATCH_HOOKS=[],
    )
    def test_xp_batch_completed_signal(self):
        received = []

        def handler(sender, summary, week, **kwargs):
            received.append(summary)

        from evennia_xp.signals import xp_batch_completed

        xp_batch_completed.connect(handler)
        try:
            run_weekly_batch(week="2026-W20")
            self.assertEqual(len(received), 1)
            self.assertIsInstance(received[0], BatchSummary)
        finally:
            xp_batch_completed.disconnect(handler)

    @override_settings(
        XP_COLLECTORS=[("rp_session", "evennia_xp.tests._test_collector")],
        XP_ANTIGAMING_SWEEPS=[],
        XP_POST_BATCH_HOOKS=[],
    )
    def test_idempotent_rerun(self):
        run_weekly_batch(week="2026-W20")
        run_weekly_batch(week="2026-W20")
        self.assertEqual(XPLog.objects.filter(source_ref_id=9001).count(), 1)


# ---------------------------------------------------------------------------
# Gating seam
# ---------------------------------------------------------------------------

_RESOLVER_PATH = "evennia_xp.tests._test_multiplier_resolver"
_BROKEN_PATH = "evennia_xp.tests._broken_resolver"


class TestGatingSeam(EvenniaTest):
    @override_settings(XP_MULTIPLIER_RESOLVER=_RESOLVER_PATH)
    def test_resolver_honored(self):
        from evennia_xp.gating import resolve_xp_multiplier

        result = resolve_xp_multiplier("rp_session")
        self.assertEqual(result, Decimal("0.5"))

    @override_settings(XP_MULTIPLIER_RESOLVER=_RESOLVER_PATH)
    def test_resolver_full_rate_for_other_source(self):
        from evennia_xp.gating import resolve_xp_multiplier

        result = resolve_xp_multiplier("lore_authored")
        self.assertEqual(result, Decimal("1.0"))

    @override_settings(XP_MULTIPLIER_RESOLVER=None)
    def test_unset_resolver_returns_one(self):
        from evennia_xp.gating import resolve_xp_multiplier

        self.assertEqual(resolve_xp_multiplier("rp_session"), Decimal("1.0"))

    @override_settings(XP_MULTIPLIER_RESOLVER=_BROKEN_PATH)
    def test_broken_resolver_degrades_to_one(self):
        from evennia_xp.gating import resolve_xp_multiplier

        result = resolve_xp_multiplier("rp_session")
        self.assertEqual(result, Decimal("1.0"))

    @override_settings(XP_MULTIPLIER_RESOLVER=_RESOLVER_PATH)
    def test_thread_pauses_xp_predicate(self):
        from evennia_xp.gating import thread_pauses_xp

        self.assertFalse(thread_pauses_xp("lore_authored"))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


class TestCmdXpStaffLock(EvenniaCommandTest):
    @override_settings(XP_STAFF_LOCK="cmd:perm(Builder)")
    def test_non_staff_grant_denied(self):
        from evennia_xp.commands import CmdXp

        # char2's account has no Builder/Developer permission, so the lock fails.
        self.call(
            CmdXp(),
            "/grant TestChar=1:reason",
            "You need staff permission",
            caller=self.char2,
        )

    @override_settings(XP_STAFF_LOCK="cmd:perm(Builder)")
    def test_staff_grant_succeeds(self):
        from evennia_xp.commands import CmdXp

        # Give char1 Builder permission
        self.char1.permissions.add("Builder")
        # char1 tries to grant to itself (search finds itself)
        with patch("evennia_xp.awards.record_xp") as mock_grant:
            mock_log = MagicMock()
            mock_log.pk = 1
            mock_grant.return_value = mock_log
            self.call(
                CmdXp(),
                f"/grant {self.char1.key}=2:for testing",
                "Granted",
                caller=self.char1,
            )
        self.char1.permissions.remove("Builder")


class TestCmdXpBalance(EvenniaCommandTest):
    @override_settings(
        XP_COLLECTORS=[],
        XP_ANTIGAMING_SWEEPS=[],
        XP_POST_BATCH_HOOKS=[],
        XP_MULTIPLIER_RESOLVER=None,
    )
    def test_balance_no_xp(self):
        from evennia_xp.commands import CmdXp

        self.call(CmdXp(), "", "XP —", caller=self.char1)

    @override_settings(
        XP_COLLECTORS=[],
        XP_ANTIGAMING_SWEEPS=[],
        XP_POST_BATCH_HOOKS=[],
        XP_MULTIPLIER_RESOLVER=None,
    )
    def test_log_no_entries(self):
        from evennia_xp.commands import CmdXp

        self.call(CmdXp(), "/log", "No XP awards found", caller=self.char1)

    @override_settings(
        XP_COLLECTORS=[],
        XP_ANTIGAMING_SWEEPS=[],
        XP_POST_BATCH_HOOKS=[],
        XP_MULTIPLIER_RESOLVER=None,
    )
    def test_sources_lists_collectors(self):
        from evennia_xp.commands import CmdXp

        with override_settings(XP_COLLECTORS=[("rp_session", "some.path")]):
            result = self.call(CmdXp(), "/sources", None, caller=self.char1)
        self.assertIn("rp_session", result)

    @override_settings(
        XP_COLLECTORS=[],
        XP_ANTIGAMING_SWEEPS=[],
        XP_POST_BATCH_HOOKS=[],
        XP_MULTIPLIER_RESOLVER=_RESOLVER_PATH,
    )
    def test_balance_downtime_banner(self):
        from evennia_xp.commands import CmdXp

        result = self.call(CmdXp(), "", None, caller=self.char1)
        self.assertIn("XP RATES MODIFIED", result)


# ---------------------------------------------------------------------------
# Web view
# ---------------------------------------------------------------------------


def _build_view(view_class, request):
    """Wire up a ListView for direct context inspection (no template rendering)."""
    view = view_class()
    view.request = request
    view.kwargs = {}
    view.args = ()
    view.object_list = view.get_queryset()
    view.paginate_by = None
    return view


class TestXPSummaryViewAuth(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def test_anonymous_redirected(self):
        from django.contrib.auth.models import AnonymousUser

        from evennia_xp.views import XPSummaryView

        request = self.factory.get("/xp/")
        request.user = AnonymousUser()
        view = XPSummaryView.as_view()
        response = view(request)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_no_puppet_raises_permission_denied(self):
        from django.core.exceptions import PermissionDenied

        from evennia_xp.views import XPSummaryView

        request = self.factory.get("/xp/")
        request.user = self.account2
        # Ensure no puppets
        self.account2.db._playable_characters = []
        view = XPSummaryView()
        view.request = request
        view.kwargs = {}
        view.args = ()
        with self.assertRaises(PermissionDenied):
            view.get_queryset()


class TestXPSummaryViewContext(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def _make_request(self, account, char):
        request = self.factory.get("/xp/")
        request.user = account
        # Patch get_character_id to return char.pk
        self._patcher = patch("evennia_xp.views.get_character_id", return_value=char.pk)
        self._patcher.start()
        return request

    def tearDown(self):
        super().tearDown()
        if hasattr(self, "_patcher"):
            self._patcher.stop()

    def test_context_has_expected_keys(self):
        from evennia_xp.views import XPSummaryView

        request = self._make_request(self.account, self.char1)
        view = _build_view(XPSummaryView, request)
        ctx = view.get_context_data()
        for key in ("balance", "total_earned", "total_spent", "by_source", "logs"):
            self.assertIn(key, ctx)

    def test_context_balance_values(self):
        from evennia_xp.views import XPSummaryView

        record_xp(
            character_id=self.char1.pk,
            amount=Decimal("3.0"),
            source_type=XPLog.SourceType.RP_SESSION,
            source_ref_id=5001,
        )
        request = self._make_request(self.account, self.char1)
        view = _build_view(XPSummaryView, request)
        ctx = view.get_context_data()
        self.assertEqual(ctx["balance"], Decimal("3.0"))
        self.assertEqual(ctx["total_earned"], Decimal("3.0"))

    @override_settings(XP_MULTIPLIER_RESOLVER=_RESOLVER_PATH)
    def test_downtime_active_when_mult_below_one(self):
        from evennia_xp.views import XPSummaryView

        request = self._make_request(self.account, self.char1)
        view = _build_view(XPSummaryView, request)
        ctx = view.get_context_data()
        self.assertTrue(ctx["downtime_active"])

    @override_settings(XP_MULTIPLIER_RESOLVER=None)
    def test_downtime_inactive_when_no_resolver(self):
        from evennia_xp.views import XPSummaryView

        request = self._make_request(self.account, self.char1)
        view = _build_view(XPSummaryView, request)
        ctx = view.get_context_data()
        self.assertFalse(ctx["downtime_active"])


# ---------------------------------------------------------------------------
# REST API — XPLogViewSet
# ---------------------------------------------------------------------------


class TestXPLogApi(EvenniaTest):
    def setUp(self):
        super().setUp()
        from rest_framework.test import APIRequestFactory

        from evennia_xp.api.views import XPLogViewSet

        self.factory = APIRequestFactory()
        self.viewset = XPLogViewSet

    def _get_list(self, user, char_pk=None):
        """Perform GET on /xp-log/ as *user*, patching character id."""
        request = self.factory.get("/xp-log/")
        request.user = user
        view = self.viewset.as_view({"get": "list"})
        with (
            patch("evennia_xp.permissions.get_character_id", return_value=char_pk),
            patch("evennia_xp.api.views.get_character_id", return_value=char_pk),
        ):
            return view(request)

    def test_authenticated_with_puppet_sees_own_rows(self):
        record_xp(
            character_id=self.char1.pk,
            amount=Decimal("1.0"),
            source_type=XPLog.SourceType.RP_SESSION,
            source_ref_id=6001,
        )
        response = self._get_list(self.account, char_pk=self.char1.pk)
        self.assertEqual(response.status_code, 200)
        response.accepted_renderer = MagicMock()
        response.accepted_media_type = "application/json"
        response.renderer_context = {}
        response.render()
        ids = [row["id"] for row in response.data["results"]]
        self.assertEqual(len(ids), 1)

    def test_no_puppet_returns_empty(self):
        record_xp(
            character_id=self.char1.pk,
            amount=Decimal("1.0"),
            source_type=XPLog.SourceType.RP_SESSION,
            source_ref_id=6002,
        )
        response = self._get_list(self.account2, char_pk=None)
        self.assertEqual(response.status_code, 200)
        response.accepted_renderer = MagicMock()
        response.accepted_media_type = "application/json"
        response.renderer_context = {}
        response.render()
        self.assertEqual(len(response.data["results"]), 0)

    def test_char1_cannot_see_char2_rows(self):
        """Self-only privacy: char1 logged in cannot see char2's XPLog rows."""
        record_xp(
            character_id=self.char2.pk,
            amount=Decimal("1.0"),
            source_type=XPLog.SourceType.RP_SESSION,
            source_ref_id=6003,
        )
        response = self._get_list(self.account, char_pk=self.char1.pk)
        self.assertEqual(response.status_code, 200)
        response.accepted_renderer = MagicMock()
        response.accepted_media_type = "application/json"
        response.renderer_context = {}
        response.render()
        # char1 has no rows — only char2 does
        self.assertEqual(len(response.data["results"]), 0)


# ---------------------------------------------------------------------------
# Script
# ---------------------------------------------------------------------------


class TestXPBatchScript(EvenniaTest):
    def test_ensure_idempotent(self):
        """Calling ensure_xp_batch_script_running twice does not create two scripts."""
        from evennia_xp.scripts import ensure_xp_batch_script_running

        with (
            patch("evennia.utils.search.search_script") as mock_search,
            patch("evennia.utils.create.create_script") as mock_create,
        ):
            # First call: not found
            mock_search.return_value = []
            ensure_xp_batch_script_running()
            self.assertEqual(mock_create.call_count, 1)

            # Second call: found
            mock_search.return_value = [MagicMock()]
            ensure_xp_batch_script_running()
            self.assertEqual(mock_create.call_count, 1)  # still 1, not called again

    def test_at_repeat_noop_when_week_already_run(self):
        """at_repeat does nothing when last_batch_week == current target week."""
        from evennia_xp.scripts import XPBatchScript

        script = MagicMock(spec=XPBatchScript)
        script.db = MagicMock()

        from datetime import datetime

        monday = datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC)
        expected_week = "2026-W18"
        script.db.last_batch_week = expected_week

        with (
            patch("evennia_xp.batch._last_monday_00_utc", return_value=monday),
            patch(
                "evennia_xp.batch._week_str_from_window_end",
                return_value=expected_week,
            ),
            patch("evennia_xp.batch.run_weekly_batch") as mock_batch,
        ):
            # Call the real at_repeat via the unbound method
            XPBatchScript.at_repeat(script)
            mock_batch.assert_not_called()

    def test_at_repeat_runs_when_week_new(self):
        """at_repeat calls run_weekly_batch when the week hasn't been run."""
        from evennia_xp.scripts import XPBatchScript

        script = MagicMock(spec=XPBatchScript)
        script.db = MagicMock()
        script.db.last_batch_week = "2026-W17"

        from datetime import datetime

        monday = datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC)
        target_week = "2026-W18"

        mock_summary = MagicMock()
        mock_summary.week = target_week
        mock_summary.total_awards = 0
        mock_summary.total_xp = Decimal("0.00")
        mock_summary.errors = []

        with (
            patch("evennia_xp.batch._last_monday_00_utc", return_value=monday),
            patch(
                "evennia_xp.batch._week_str_from_window_end",
                return_value=target_week,
            ),
            patch("evennia_xp.batch.run_weekly_batch", return_value=mock_summary) as mock_batch,
        ):
            XPBatchScript.at_repeat(script)
            mock_batch.assert_called_once_with(week=target_week)


# ---------------------------------------------------------------------------
# Antigaming helpers
# ---------------------------------------------------------------------------


class TestAntgamingHelpers(EvenniaTest):
    def _make_item(self, ts):
        item = MagicMock()
        item.created_at = ts
        del item.ended_at  # ensure _item_time uses created_at
        return item

    def test_find_burst_detects_burst(self):
        from datetime import datetime, timedelta

        from evennia_xp.antigaming import _find_burst

        base = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        items = [self._make_item(base + timedelta(hours=i)) for i in range(5)]
        burst = _find_burst(items, count=3, window_hours=3)
        self.assertEqual(len(burst), 3)

    def test_find_burst_no_burst(self):
        from datetime import datetime, timedelta

        from evennia_xp.antigaming import _find_burst

        base = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)
        # Use a spread > 24h between pairs so no 3-item burst fits in 24h window.
        items = [self._make_item(base + timedelta(hours=13 * i)) for i in range(4)]
        burst = _find_burst(items, count=3, window_hours=24)
        self.assertEqual(burst, [])


# ---------------------------------------------------------------------------
# Standalone import (no partner apps)
# ---------------------------------------------------------------------------


class TestStandaloneImport(EvenniaTest):
    def test_import_evennia_xp(self):
        import evennia_xp

        self.assertTrue(hasattr(evennia_xp, "__version__"))
        self.assertTrue(hasattr(evennia_xp, "xp_awarded"))
        self.assertTrue(hasattr(evennia_xp, "xp_batch_completed"))

    def test_lazy_model_load(self):
        from evennia_xp import XPLog

        self.assertTrue(issubclass(XPLog, __import__("django.db.models", fromlist=["Model"]).Model))
