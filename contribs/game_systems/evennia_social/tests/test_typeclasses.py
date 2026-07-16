# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Tests for SocialCharacterMixin/SocialRoomMixin, with emphasis on the
cooperative msg() chain — the highest-risk piece of this extraction per
the scoping report (§10): ignore-filtering (social) must run before
pose-header/highlight processing (posing), in a single pass, without
either mixin's slice interfering with the other's.
"""

from evennia.objects.objects import DefaultCharacter

from evennia_social.tests.base import SocialTestCase


class TestCooperativeMsg(SocialTestCase):
    """SocialCharacterMixin.msg() + PosingCharacterMixin.msg() chaining.

    Captures at the DefaultCharacter.msg() sink (mirroring evennia_posing's
    own tests) rather than wrapping the instance's own .msg — the mixin
    chain computes its transformed text internally and only ever hands it
    to super().msg(), so patching the entry point captures the pre-transform
    input, not what's actually delivered.
    """

    def _capture_delivered(self):
        """Monkeypatch DefaultCharacter.msg to capture what reaches it.

        Returns (received, restore) — received is the list to inspect,
        restore() puts DefaultCharacter.msg back.
        """
        received = []
        orig = DefaultCharacter.msg

        def fake_msg(self_, text=None, **kwargs):
            received.append(text)

        DefaultCharacter.msg = fake_msg
        return received, lambda: setattr(DefaultCharacter, "msg", orig)

    def test_normal_pose_gets_header_and_highlight(self):
        """A pose from a non-ignored sender passes both mixins in one call:
        social's msg() finds no ignore match and chains into posing's
        msg(), which prepends a header and highlights the poser's name.
        """
        self.account.db.ignore_list = []
        received, restore = self._capture_delivered()
        try:
            self.char2.msg(("Char waves.", {"type": "pose"}), from_obj=self.char1)
        finally:
            restore()

        self.assertEqual(len(received), 1)
        text, opts = received[0]
        # Both mixins' slices land in one delivered string: posing prepends
        # the header, then highlights the whole text (header included), so
        # the poser's name is color-wrapped in both places. Default others
        # color is "c" — char1 is not the looker (char2).
        self.assertEqual(text, "--- |cChar|n ---\n|cChar|n waves.")
        # Type is untouched for non-ignored content.
        self.assertEqual(opts["type"], "pose")

    def test_ignored_sender_placeholder_gets_no_pose_header(self):
        """An ignored sender's pose is replaced with the muted placeholder
        and must NOT pick up a pose header on the way out.

        This is the anonymity guarantee, not just cosmetics: the placeholder
        deliberately says "An ignored player", so a "--- Char2 ---" header
        above it would name the very sender it is meant to anonymize.
        The placeholder still passes *through* PosingCharacterMixin.msg()
        (social chains into it via super()); it survives untouched because
        social retags the type to "system", which posing's header/highlight
        branch does not match.
        """
        self.account.db.ignore_list = [self.account2.id]
        received, restore = self._capture_delivered()
        try:
            self.char1.msg(("Char2 waves.", {"type": "pose"}), from_obj=self.char2)
        finally:
            restore()

        self.assertEqual(len(received), 1)
        text, opts = received[0]
        self.assertIn("ignored player posed", text)
        # No header, and the sender's name appears nowhere in any form.
        self.assertNotIn("---", text)
        self.assertNotIn("Char2", text)
        self.assertEqual(opts["type"], "system")

    def test_whisper_from_ignored_sender_is_suppressed(self):
        """Whispers from ignored senders are dropped entirely, not replaced."""
        self.account.db.ignore_list = [self.account2.id]
        received, restore = self._capture_delivered()
        try:
            self.char1.msg(("psst", {"type": "whisper"}), from_obj=self.char2)
        finally:
            restore()

        self.assertEqual(received, [])

    def test_staff_sender_bypasses_ignore(self):
        """Builder+ senders are never filtered, even if ignored."""
        self.account.db.ignore_list = [self.account2.id]
        self.account2.permissions.add("Builder")
        received, restore = self._capture_delivered()
        try:
            self.char1.msg(("Char2 waves.", {"type": "pose"}), from_obj=self.char2)
        finally:
            restore()

        self.assertEqual(len(received), 1)
        text, _opts = received[0]
        self.assertNotIn("ignored player", text)


class TestVisitTracking(SocialTestCase):
    """visited_rooms / _record_visit() — feeds @tel's "visited" mode."""

    def test_post_puppet_records_current_room(self):
        self.char1.visited_rooms = None
        self.char1.at_post_puppet()
        self.assertIn(self.room1.dbref, self.char1.visited_rooms)

    def test_move_records_destination(self):
        """A real move() records the *destination* — this is what feeds
        @tel's "visited" mode, so drive move_to() rather than calling the
        hook by hand.
        """
        self.char1.visited_rooms = None
        self.char1.move_to(self.room2, quiet=True)
        self.assertEqual(self.char1.location, self.room2)
        self.assertIn(self.room2.dbref, self.char1.visited_rooms)


class TestGetDisplayName(SocialTestCase):
    """get_display_name() short_desc suffix."""

    def test_no_short_desc(self):
        self.char1.short_desc = ""
        name = self.char1.get_display_name(looker=self.char1)
        self.assertNotIn(" - ", name)

    def test_with_short_desc(self):
        self.char1.short_desc = "a tall figure in grey"
        name = self.char1.get_display_name(looker=self.char1)
        self.assertIn("a tall figure in grey", name)
