# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Tests for evennia_posing.

Uses EvenniaTest/EvenniaCommandTest with local test typeclasses that mix in
PosingCharacterMixin/PosingRoomMixin, since the stock Evennia
DefaultCharacter/DefaultRoom used by the base test classes don't have
record_pose()/get_characters_by_pose_time() etc.

Account options (show_pose_headers, highlight_enabled, ...) are registered
onto settings.OPTIONS_ACCOUNT_DEFAULT in setUpClass — the same registration
step a consuming game performs in server/conf/settings.py (see README step
3) — so this contrib's own suite is self-contained.

Objects available from EvenniaTest/EvenniaCommandTest:
    self.char1 (key="Char"), self.char2 (key="Char2") — both in self.room1
    self.account, self.account2 — linked to char1/char2 respectively
"""

from django.conf import settings
from evennia.objects.objects import DefaultCharacter, DefaultRoom
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from evennia_posing.commands import (
    CmdEmit,
    CmdHighlight,
    CmdLastPose,
    CmdPose,
    CmdPoseHeader,
    CmdPot,
    CmdSemipose,
)
from evennia_posing.highlighting import format_pose_time, highlight_names
from evennia_posing.signals import pose_recorded
from evennia_posing.typeclasses import PosingCharacterMixin, PosingRoomMixin

_POSING_OPTIONS = {
    "show_pose_headers": ("Show character name headers above poses.", "Boolean", True),
    "pose_header_format": (
        "Format string for pose headers.",
        "Text",
        "--- {name} ---",
    ),
    "pose_separator": ("Visual separator between poses.", "Text", ""),
    "highlight_enabled": (
        "Highlight character names in poses and room descriptions.",
        "Boolean",
        True,
    ),
    "highlight_self_color": ("Color for your own name in poses.", "Color", "w"),
    "highlight_others_color": ("Color for other character names.", "Color", "c"),
}


class PosingTestCharacter(PosingCharacterMixin, DefaultCharacter):
    """Test-local Character typeclass mixing in the posing pipeline."""


class PosingTestRoom(PosingRoomMixin, DefaultRoom):
    """Test-local Room typeclass mixing in the posing pipeline."""


class PosingTestCase(EvenniaTest):
    """Base test case: posing typeclasses + registered account options."""

    character_typeclass = PosingTestCharacter
    room_typeclass = PosingTestRoom

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Mirrors README step 3 — the game registers these once at startup.
        # OPTIONS_ACCOUNT_DEFAULT is read by reference by AccountDB.options
        # (a lazy_property), so mutating it here before any account's
        # .options is first accessed is sufficient and self-contained.
        settings.OPTIONS_ACCOUNT_DEFAULT.update(_POSING_OPTIONS)


class PosingCommandTestCase(EvenniaCommandTest):
    """Base command test case: posing typeclasses + registered account options."""

    character_typeclass = PosingTestCharacter
    room_typeclass = PosingTestRoom

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        settings.OPTIONS_ACCOUNT_DEFAULT.update(_POSING_OPTIONS)


# =====================================================================
# highlighting.py
# =====================================================================


class TestHighlightNames(PosingTestCase):
    """Unit tests for the highlight_names() utility function."""

    def test_self_name_highlighted(self):
        """Looker's own name gets self-color (default: white)."""
        result = highlight_names("Char walks in.", self.char1, [self.char1])
        self.assertEqual(result, "|wChar|n walks in.")

    def test_others_name_highlighted(self):
        """Other character's name gets others-color (default: cyan)."""
        result = highlight_names("Char2 waves.", self.char1, [self.char1, self.char2])
        self.assertIn("|cChar2|n", result)

    def test_both_names_in_same_text(self):
        """Both self and others highlighted in one string."""
        result = highlight_names("Char nods to Char2.", self.char1, [self.char1, self.char2])
        self.assertIn("|wChar|n", result)
        self.assertIn("|cChar2|n", result)

    def test_case_insensitive_matching(self):
        """Names match regardless of case, preserving original case."""
        result = highlight_names("char walks in.", self.char1, [self.char1])
        self.assertEqual(result, "|wchar|n walks in.")

    def test_word_boundary_prevents_partial_match(self):
        """'Char' should not match inside 'Char2' — word boundary enforced."""
        result = highlight_names("Char2 greets Char.", self.char1, [self.char1, self.char2])
        self.assertIn("|cChar2|n", result)
        self.assertIn("|wChar|n", result)
        self.assertEqual(result.count("|wChar|n"), 1)

    def test_longer_name_matched_first(self):
        """When names overlap (e.g., 'Char' and 'Char2'), longer wins."""
        result = highlight_names("Char2 is here.", self.char1, [self.char1, self.char2])
        self.assertIn("|cChar2|n", result)
        self.assertNotIn("|wChar|n", result)

    def test_no_characters_returns_unchanged(self):
        """Empty character list returns text unchanged."""
        text = "Nobody is here."
        result = highlight_names(text, self.char1, [])
        self.assertEqual(result, text)

    def test_disabled_returns_unchanged(self):
        """When highlight_enabled is False, text is unchanged."""
        self.account.options.set("highlight_enabled", "False")
        text = "Char walks in."
        result = highlight_names(text, self.char1, [self.char1])
        self.assertEqual(result, text)

    def test_no_account_returns_unchanged(self):
        """If looker has no account, text is unchanged."""
        self.char1.account = None
        text = "Char walks in."
        result = highlight_names(text, self.char1, [self.char1])
        self.assertEqual(result, text)

    def test_custom_colors(self):
        """Custom color preferences are applied."""
        self.account.options.set("highlight_self_color", "y")
        self.account.options.set("highlight_others_color", "g")
        result = highlight_names("Char nods to Char2.", self.char1, [self.char1, self.char2])
        self.assertIn("|yChar|n", result)
        self.assertIn("|gChar2|n", result)

    def test_name_inside_color_code_not_matched(self):
        """Names inside Evennia pipe-color codes are not highlighted."""
        text = "|cChar|n walks in."
        result = highlight_names(text, self.char1, [self.char1])
        self.assertNotIn("|w|c", result)

    def test_multiple_occurrences(self):
        """Same name appearing multiple times is highlighted each time."""
        result = highlight_names(
            "Char looks at Char2. Char smiles.", self.char1, [self.char1, self.char2]
        )
        self.assertEqual(result.count("|wChar|n"), 2)
        self.assertEqual(result.count("|cChar2|n"), 1)


class TestFormatPoseTime(PosingTestCase):
    """Unit tests for format_pose_time()."""

    def test_none_returns_dashes(self):
        self.assertEqual(format_pose_time(None), "--")

    def test_recent_returns_just_now(self):
        import time

        self.assertEqual(format_pose_time(time.time()), "just now")

    def test_minutes_and_seconds(self):
        import time

        result = format_pose_time(time.time() - 125)
        self.assertIn("m", result)
        self.assertIn("s", result)

    def test_hours(self):
        import time

        result = format_pose_time(time.time() - 3700)
        self.assertIn("h", result)

    def test_days(self):
        import time

        result = format_pose_time(time.time() - 90000)
        self.assertIn("d", result)


# =====================================================================
# PosingCharacterMixin.record_pose() + pose_recorded signal
# =====================================================================


class TestRecordPose(PosingTestCase):
    """Tests for PosingCharacterMixin.record_pose()."""

    def test_updates_pose_time_and_text(self):
        self.char1.record_pose("Char nods.", pose_type="pose")
        self.assertIsNotNone(self.char1.last_pose_time)
        self.assertEqual(self.char1.last_pose_text, "Char nods.")

    def test_breaks_observer_mode(self):
        self.char1.pose_status = "observing"
        self.char1.record_pose("Char nods.", pose_type="pose")
        self.assertEqual(self.char1.pose_status, "ic")

    def test_afk_status_not_cleared_by_pose(self):
        """Only 'observing' is broken by posing — AFK is a separate toggle."""
        self.char1.pose_status = "afk"
        self.char1.record_pose("Char nods.", pose_type="pose")
        self.assertEqual(self.char1.pose_status, "afk")

    def test_fires_pose_recorded_signal(self):
        received = []

        def listener(sender, **kwargs):
            received.append(kwargs)

        pose_recorded.connect(listener, weak=False)
        try:
            self.char1.record_pose("Char nods.", pose_type="pose")
        finally:
            pose_recorded.disconnect(listener)

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["character"], self.char1)
        self.assertEqual(received[0]["pose_text"], "Char nods.")
        self.assertEqual(received[0]["pose_type"], "pose")
        self.assertEqual(received[0]["location"], self.room1)


# =====================================================================
# PosingCharacterMixin.msg() — pose headers + highlighting
# =====================================================================


class TestCharacterMsgHeaderAndHighlight(PosingTestCase):
    """Tests for the cooperative msg() override (headers + highlighting)."""

    def test_header_prepended_to_pose(self):
        # Capture the transformed text just before it would hit Evennia's
        # real delivery machinery, by monkeypatching the base class's msg().
        captured = {}

        def fake_msg(self_, text=None, **kwargs):
            captured["text"] = text

        # Isolate header behavior from highlighting — both run in the same
        # msg() pass, and highlighting would also color the poser's name
        # inside the header text.
        self.account.options.set("highlight_enabled", "False")
        orig = DefaultCharacter.msg
        DefaultCharacter.msg = fake_msg
        try:
            self.char1.msg(text=("nods.", {"type": "pose"}), from_obj=self.char2)
        finally:
            DefaultCharacter.msg = orig

        msg_text, msg_opts = captured["text"]
        self.assertIn("--- Char2 ---", msg_text)
        self.assertIn("nods.", msg_text)

    def test_say_self_echo_has_no_header(self):
        captured = {}

        def fake_msg(self_, text=None, **kwargs):
            captured["text"] = text

        orig = DefaultCharacter.msg
        DefaultCharacter.msg = fake_msg
        try:
            self.char1.msg(text=("You say, 'hi'", {"type": "say"}), from_obj=self.char1)
        finally:
            DefaultCharacter.msg = orig

        msg_text, _ = captured["text"]
        self.assertNotIn("---", msg_text)

    def test_highlighting_applied_when_location_set(self):
        captured = {}

        def fake_msg(self_, text=None, **kwargs):
            captured["text"] = text

        self.account.options.set("show_pose_headers", "False")
        orig = DefaultCharacter.msg
        DefaultCharacter.msg = fake_msg
        try:
            self.char1.msg(text=("Char2 nods.", {"type": "pose"}), from_obj=self.char2)
        finally:
            DefaultCharacter.msg = orig

        msg_text, _ = captured["text"]
        self.assertIn("|cChar2|n", msg_text)

    def test_non_pose_type_passes_through_unchanged(self):
        captured = {}

        def fake_msg(self_, text=None, **kwargs):
            captured["text"] = text

        orig = DefaultCharacter.msg
        DefaultCharacter.msg = fake_msg
        try:
            self.char1.msg(text=("System message.", {"type": "system"}), from_obj=self.char2)
        finally:
            DefaultCharacter.msg = orig

        msg_text, _ = captured["text"]
        self.assertEqual(msg_text, "System message.")


# =====================================================================
# PosingRoomMixin
# =====================================================================


class TestPosingRoomMixin(PosingTestCase):
    """Tests for get_characters_by_pose_time() and get_display_characters().

    get_characters_by_pose_time() filters on obj.has_account, which reflects
    a *connected session* (obj.sessions.count()), not merely an assigned
    Account FK. EvenniaTest's setup_session() only ever establishes a live
    session for char1's account, so char2.has_account is always False under
    the stock test harness. That's a faithful, correct filter (+pot should
    only list connected characters) — it's just not exercisable with two
    characters without a second real session. Since these tests are about
    sort order, not the connectivity filter, has_account is patched True
    for both characters here rather than standing up a second session.
    """

    def _patch_has_account(self):
        from unittest import mock

        return mock.patch.object(
            PosingTestCharacter, "has_account", new_callable=mock.PropertyMock, return_value=True
        )

    def test_sorted_by_pose_time_ascending(self):
        import time

        self.char1.last_pose_time = time.time()
        self.char2.last_pose_time = time.time() - 100
        with self._patch_has_account():
            ordered = self.room1.get_characters_by_pose_time()
        self.assertEqual(ordered[0], self.char2)
        self.assertEqual(ordered[1], self.char1)

    def test_none_pose_time_sorts_first(self):
        import time

        self.char1.last_pose_time = time.time()
        self.char2.last_pose_time = None
        with self._patch_has_account():
            ordered = self.room1.get_characters_by_pose_time()
        self.assertEqual(ordered[0], self.char2)

    def test_display_characters_shows_afk_tag(self):
        self.char2.pose_status = "afk"
        result = self.room1.get_display_characters(self.char1)
        self.assertIn("[AFK]", result)

    def test_display_characters_shows_obs_tag(self):
        self.char2.pose_status = "observing"
        result = self.room1.get_display_characters(self.char1)
        self.assertIn("[OBS]", result)

    def test_display_characters_empty_when_alone(self):
        self.char2.location = None
        result = self.room1.get_display_characters(self.char1)
        self.assertEqual(result, "")


# =====================================================================
# Commands
# =====================================================================


class TestCmdSemipose(PosingCommandTestCase):
    """Tests for the semipose (;) command."""

    def test_possessive(self):
        result = self.call(CmdSemipose(), "'s eyes narrow.", caller=self.char1)
        self.assertIn("Char's eyes narrow.", result)

    def test_no_space(self):
        result = self.call(CmdSemipose(), "nods", caller=self.char1)
        self.assertIn("Charnods", result)

    def test_empty_args(self):
        result = self.call(CmdSemipose(), "", caller=self.char1)
        self.assertIn("What do you want to pose?", result)

    def test_no_location(self):
        self.char1.location = None
        result = self.call(CmdSemipose(), "'s eyes narrow.", caller=self.char1)
        self.assertIn("no location", result)

    def test_records_pose(self):
        self.call(CmdSemipose(), "'s eyes narrow.", caller=self.char1)
        self.assertIsNotNone(self.char1.last_pose_time)
        self.assertIn("Char's eyes narrow.", self.char1.last_pose_text)


class TestCmdPose(PosingCommandTestCase):
    """Tests for the pose command override."""

    def test_records_pose(self):
        self.call(CmdPose(), "nods.", caller=self.char1)
        self.assertIsNotNone(self.char1.last_pose_time)
        self.assertIn("Char nods.", self.char1.last_pose_text)

    def test_empty_args(self):
        result = self.call(CmdPose(), "", caller=self.char1)
        self.assertIn("What do you want to pose?", result)


class TestCmdEmit(PosingCommandTestCase):
    """Tests for the emit command."""

    def test_records_pose_type_emit(self):
        self.call(CmdEmit(), "The wind howls.", caller=self.char1)
        self.assertEqual(self.char1.last_pose_text, "The wind howls.")

    def test_empty_args(self):
        result = self.call(CmdEmit(), "", caller=self.char1)
        self.assertIn("What do you want to emit?", result)

    def test_no_location(self):
        self.char1.location = None
        result = self.call(CmdEmit(), "The wind howls.", caller=self.char1)
        self.assertIn("no location", result)


class TestCmdPot(PosingCommandTestCase):
    """Tests for the +pot pose order tracker."""

    def test_display_shows_characters(self):
        result = self.call(CmdPot(), "", caller=self.char1)
        self.assertIn("Pose Order", result)
        self.assertIn("Char", result)

    def test_no_location(self):
        self.char1.location = None
        result = self.call(CmdPot(), "", caller=self.char1)
        self.assertIn("no location", result)

    def test_obs_toggle(self):
        self.call(CmdPot(), "/obs", "You are now observing.", caller=self.char1)
        self.assertEqual(self.char1.pose_status, "observing")
        self.call(CmdPot(), "/obs", "You are no longer observing.", caller=self.char1)
        self.assertEqual(self.char1.pose_status, "ic")

    def test_afk_toggle(self):
        self.call(CmdPot(), "/afk", "You are now AFK.", caller=self.char1)
        self.assertEqual(self.char1.pose_status, "afk")

    def test_ic_switch(self):
        self.char1.pose_status = "afk"
        self.call(CmdPot(), "/ic", "Your status is now IC.", caller=self.char1)
        self.assertEqual(self.char1.pose_status, "ic")

    def test_unknown_switch(self):
        result = self.call(CmdPot(), "/bogus", caller=self.char1)
        self.assertIn("Unknown switch", result)


class TestCmdLastPose(PosingCommandTestCase):
    """Tests for +lastpose."""

    def test_no_location(self):
        self.char1.location = None
        result = self.call(CmdLastPose(), "", caller=self.char1)
        self.assertIn("no location", result)

    def test_no_recent_poses(self):
        result = self.call(CmdLastPose(), "", caller=self.char1)
        self.assertIn("No recent poses", result)

    def test_shows_summary_after_pose(self):
        self.char1.record_pose("Char nods.", pose_type="pose")
        result = self.call(CmdLastPose(), "", caller=self.char2)
        self.assertIn("Char nods.", result)

    def test_specific_character_full_pose(self):
        self.char1.record_pose("Char nods slowly.", pose_type="pose")
        result = self.call(CmdLastPose(), "Char", caller=self.char2)
        self.assertIn("Char nods slowly.", result)

    def test_specific_character_no_pose(self):
        result = self.call(CmdLastPose(), "Char2", caller=self.char1)
        self.assertIn("has no recent pose", result)


class TestCmdPoseHeader(PosingCommandTestCase):
    """Tests for +poseheader."""

    def test_display_settings(self):
        result = self.call(CmdPoseHeader(), "", caller=self.char1)
        self.assertIn("Pose Header Settings", result)

    def test_toggle_off(self):
        self.call(CmdPoseHeader(), "/off", "Pose headers disabled", caller=self.char1)

    def test_toggle_on(self):
        self.account.options.set("show_pose_headers", "False")
        self.call(CmdPoseHeader(), "/on", "Pose headers enabled", caller=self.char1)

    def test_set_format(self):
        result = self.call(CmdPoseHeader(), "/format [{name}]", caller=self.char1)
        self.assertIn("Preview:", result)

    def test_format_requires_placeholder(self):
        result = self.call(CmdPoseHeader(), "/format no placeholder", caller=self.char1)
        self.assertIn("must contain", result)

    def test_set_separator(self):
        result = self.call(CmdPoseHeader(), "/separator ===", caller=self.char1)
        self.assertIn("separator set", result)

    def test_clear_separator(self):
        result = self.call(CmdPoseHeader(), "/separator", caller=self.char1)
        self.assertIn("cleared", result)

    def test_unknown_switch(self):
        result = self.call(CmdPoseHeader(), "/bogus", caller=self.char1)
        self.assertIn("Unknown switch", result)


class TestCmdHighlight(PosingCommandTestCase):
    """Tests for the +highlight command."""

    def test_display_settings(self):
        result = self.call(CmdHighlight(), "")
        self.assertIn("Name Highlighting", result)
        self.assertIn("ON", result)

    def test_disable(self):
        self.call(CmdHighlight(), "/off", "Name highlighting disabled")

    def test_enable(self):
        self.account.options.set("highlight_enabled", "False")
        self.call(CmdHighlight(), "/on", "Name highlighting enabled")

    def test_set_self_color(self):
        self.call(CmdHighlight(), "/self y", "Self highlight color set")

    def test_set_others_color(self):
        self.call(CmdHighlight(), "/others g", "Others highlight color set")

    def test_invalid_color_rejected(self):
        self.call(CmdHighlight(), "/self z", "Usage:")

    def test_empty_color_rejected(self):
        self.call(CmdHighlight(), "/self", "Usage")

    def test_unknown_switch(self):
        self.call(CmdHighlight(), "/badswitch", "Unknown switch")


# =====================================================================
# Screen-reader soft dependency
# =====================================================================


class TestScreenreaderFallback(PosingCommandTestCase):
    """+pot falls back to the standard table when evennia_accessibility
    is not installed (uses_screenreader() always returns False)."""

    def test_pot_uses_table_without_accessibility_extra(self):
        result = self.call(CmdPot(), "", caller=self.char1)
        self.assertIn("+====", result)
