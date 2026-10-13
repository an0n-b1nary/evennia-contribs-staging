# SPDX-License-Identifier: BSD-3-Clause
from unittest.mock import Mock, patch

from django.core.exceptions import PermissionDenied
from django.dispatch import Signal
from django.test import SimpleTestCase

from evennia_links import communication


class TestCommunicationRestrictions(SimpleTestCase):
    def setUp(self):
        self.signal = Signal()
        self.swap = patch.object(communication, "communication_requested", self.signal)
        self.swap.start()
        self.addCleanup(self.swap.stop)

    def test_no_provider_leaves_communication_available(self):
        self.assertIsNone(communication.denial(None, "page"))

    def test_any_denial_wins(self):
        def permit(**kwargs):
            return None

        def refuse(**kwargs):
            return "Restricted"

        self.signal.connect(permit, weak=False)
        self.signal.connect(refuse, weak=False)
        with self.assertRaisesMessage(PermissionDenied, "Restricted"):
            communication.require_communication(None, "page")

    def test_provider_error_fails_closed(self):
        def fail(**kwargs):
            raise ValueError("Unavailable provider")

        self.signal.connect(fail, weak=False)
        with self.assertLogs(level="ERROR"), self.assertRaises(PermissionDenied):
            communication.require_communication(None, "page")

    def test_channel_checks_every_sender_and_does_not_allow_bypass_mute_flag(self):
        class Terminal:
            def at_pre_msg(self, message, **kwargs):
                return message

        class Channel(communication.CommunicationChannelMixin, Terminal):
            pass

        first, second = Mock(), Mock()

        def refuse(sender, actor, **kwargs):
            return "Restricted" if actor == second else None

        self.signal.connect(refuse, weak=False)
        self.assertIsNone(Channel().at_pre_msg("Speech", senders=[first, second], bypass_mute=True))
        second.msg.assert_called_once_with("Restricted")
