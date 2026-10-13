# SPDX-License-Identifier: BSD-3-Clause
from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from evennia.utils.create import create_channel
from evennia.utils.test_resources import EvenniaTest

from evennia_rptracker.antigaming import review_alt_copresence
from evennia_rptracker.models import CoPresenceNotice, RPSession


@override_settings(RPTRACKER_ALT_COPRESENCE_COUNT=3, RPTRACKER_ALT_COPRESENCE_DAYS=7)
class TestAltCoPresence(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.now = timezone.now()

    def exchange(self, hours, *, account_id=None, overlap=True, channel=None):
        start = self.now - timedelta(hours=hours)
        for i, character in enumerate((self.char1, self.char2)):
            RPSession.objects.create(
                character=character,
                character_name=character.key,
                account_id_snapshot=account_id or self.account2.pk,
                room=self.room1,
                room_name=self.room1.key,
                channel=channel,
                source_type="rp_channel_session" if channel else "rp_session",
                status="completed",
                pose_count=10,
                activated_at=start + timedelta(minutes=0 if overlap else i * 15),
                ended_at=start + timedelta(minutes=10 if overlap else i * 15 + 10),
            )

    def test_threshold_and_idempotency_do_not_change_session_or_xp_fields(self):
        self.exchange(6)
        self.exchange(4)
        with patch("evennia_rptracker.antigaming._notify_flag_review") as notify:
            review_alt_copresence(self.now)
            notify.assert_not_called()
            self.exchange(2)
            before = list(RPSession.objects.order_by("pk").values())
            review_alt_copresence(self.now)
            review_alt_copresence(self.now)
            notify.assert_called_once()
        self.assertEqual(list(RPSession.objects.order_by("pk").values()), before)
        self.assertEqual(CoPresenceNotice.objects.count(), 1)

    def test_sequential_sessions_and_different_accounts_do_not_count(self):
        for hours in (6, 4, 2):
            self.exchange(hours, overlap=False)
        review_alt_copresence(self.now)
        self.assertFalse(CoPresenceNotice.objects.exists())
        RPSession.objects.filter(character=self.char2).update(account_id_snapshot=self.account.pk)
        review_alt_copresence(self.now)
        self.assertFalse(CoPresenceNotice.objects.exists())

    def test_channel_sessions_use_same_advisory_rule(self):
        channel = create_channel("Shared IC channel")
        for hours in (6, 4, 2):
            self.exchange(hours, channel=channel)
        review_alt_copresence(self.now)
        self.assertEqual(CoPresenceNotice.objects.count(), 1)

    def test_old_sessions_outside_window_do_not_count(self):
        self.exchange(24 * 8)
        self.exchange(4)
        self.exchange(2)
        review_alt_copresence(self.now)
        self.assertFalse(CoPresenceNotice.objects.exists())
