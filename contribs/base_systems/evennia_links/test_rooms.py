# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Room provider contracts, degradation and callback compatibility."""

from unittest.mock import Mock, patch

from django.test import override_settings
from evennia.utils.test_resources import EvenniaTest

from evennia_links.rooms import ACTIONS, can, owner_of
from evennia_links.visibility import call_room_visibility


class TestRoomProviders(EvenniaTest):
    @override_settings(LINKS_ROOM_PERMISSION=None, LINKS_ROOM_OWNER=None)
    def test_default_control_is_not_an_ownership_record(self):
        self.room1.locks.add(f"control:id({self.char1.pk})")
        for action in ACTIONS:
            self.assertTrue(can(self.char1, self.room1, action))
            self.assertFalse(can(self.char2, self.room1, action))
        self.assertFalse(can(self.char1, self.room1, "unknown"))
        self.assertIsNone(owner_of(self.room1))

    @override_settings(LINKS_ROOM_PERMISSION="provider.can", LINKS_ROOM_OWNER="provider.owner")
    def test_configured_provider_is_authoritative(self):
        provider = Mock(return_value=False)
        with patch("evennia_links.rooms.resolve_dotted", return_value=provider):
            self.assertFalse(can(self.char1, self.room1, "configure"))
            provider.assert_called_once_with(self.char1, self.room1, "configure")
        with patch("evennia_links.rooms.resolve_dotted", return_value=lambda room: self.char2):
            self.assertEqual(owner_of(self.room1), self.char2)
        with patch("evennia_links.rooms.resolve_dotted", return_value=lambda room: 123):
            self.assertIsNone(owner_of(self.room1))

    @override_settings(LINKS_ROOM_PERMISSION="missing.provider", LINKS_ROOM_OWNER="missing.owner")
    def test_broken_provider_never_falls_back_to_control(self):
        self.room1.locks.add("control:all()")
        for result in (None, 42, can, owner_of, Mock(side_effect=RuntimeError("broken"))):
            with (
                self.subTest(result=result),
                patch("evennia_links.rooms.resolve_dotted", return_value=result),
            ):
                self.assertFalse(can(self.char1, self.room1, "install"))
                self.assertIsNone(owner_of(self.room1))
        with patch("evennia_links.rooms.resolve_dotted", side_effect=ImportError("missing")):
            self.assertFalse(can(self.char1, self.room1, "install"))
            self.assertIsNone(owner_of(self.room1))

    def test_visibility_dispatch_invokes_each_supported_signature_once(self):
        self.assertTrue(call_room_visibility(lambda room: True, self.room1, self.char1))
        self.assertTrue(
            call_room_visibility(lambda room, viewer: viewer == self.char1, self.room1, self.char1)
        )
        self.assertTrue(
            call_room_visibility(
                lambda room, *, viewer: viewer == self.char1, self.room1, self.char1
            )
        )
        provider = Mock(side_effect=TypeError("inside callback"))
        with self.assertRaises(TypeError):
            call_room_visibility(provider, self.room1, self.char1)
        provider.assert_called_once()
