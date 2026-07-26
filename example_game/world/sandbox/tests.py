"""Sandbox integration tests for the world.sandbox glue and the settings
contract the contribs expect from the game.

The glue listener (world/sandbox/glue.py:on_pose_recorded, connected once in
world/sandbox/apps.py:SandboxConfig.ready) is tested end-to-end through
PosingCharacterMixin.record_pose(), with the downstream consumers mocked at
the contrib boundary - their behavior is covered by the contribs' own
suites. Glue imports both consumers lazily inside the function, so patching
the source modules is sufficient.
"""

from unittest import mock

from django.conf import settings
from evennia.utils.test_resources import EvenniaTest, EvenniaTestCase
from typeclasses.characters import Character
from typeclasses.rooms import Room


class TestPoseRecordedGlue(EvenniaTest):
    """Contract (c): on_pose_recorded fans out to scenes then rptracker."""

    character_typeclass = Character
    room_typeclass = Room

    def test_capture_then_record_in_order(self):
        order = []
        with (
            mock.patch("evennia_scenes.capture.capture_to_scene") as mock_capture,
            mock.patch("evennia_rptracker.record_rp_activity") as mock_record,
        ):
            mock_capture.side_effect = lambda *a, **k: order.append("capture")
            mock_record.side_effect = lambda *a, **k: order.append("record")

            self.char1.record_pose("waves.", pose_type="pose")

            mock_capture.assert_called_once_with(self.char1, "waves.", log_type="pose")
            mock_record.assert_called_once_with(self.char1, self.room1)
            self.assertEqual(order, ["capture", "record"])

    def test_capture_failure_does_not_block_record(self):
        order = []

        def capture_boom(*args, **kwargs):
            order.append("capture")
            raise RuntimeError("boom")

        with (
            mock.patch("evennia_scenes.capture.capture_to_scene") as mock_capture,
            mock.patch("evennia_rptracker.record_rp_activity") as mock_record,
        ):
            mock_capture.side_effect = capture_boom
            mock_record.side_effect = lambda *a, **k: order.append("record")

            # Must not raise despite capture_to_scene blowing up.
            self.char1.record_pose("waves.", pose_type="pose")

            mock_record.assert_called_once_with(self.char1, self.room1)
            self.assertEqual(order, ["capture", "record"])

    def test_no_location_skips_record(self):
        self.char1.location = None
        with (
            mock.patch("evennia_scenes.capture.capture_to_scene") as mock_capture,
            mock.patch("evennia_rptracker.record_rp_activity") as mock_record,
        ):
            self.char1.record_pose("waves.", pose_type="pose")

            mock_capture.assert_called_once_with(self.char1, "waves.", log_type="pose")
            mock_record.assert_not_called()


class TestContribSettings(EvenniaTestCase):
    """Contract (d): settings the posing/social contribs expect the game to
    register (see server/conf/settings.py and both contribs' READMEs)."""

    def test_contrib_apps_installed(self):
        self.assertIn("evennia_posing", settings.INSTALLED_APPS)
        self.assertIn("evennia_social", settings.INSTALLED_APPS)

    def test_social_settings_exist(self):
        self.assertTrue(hasattr(settings, "OOC_ROOM_DBREF"))
        self.assertTrue(hasattr(settings, "TELEPORT_MODE"))

    def test_posing_account_options_registered(self):
        for key in (
            "show_pose_headers",
            "pose_header_format",
            "pose_separator",
            "highlight_enabled",
            "highlight_self_color",
            "highlight_others_color",
        ):
            self.assertIn(key, settings.OPTIONS_ACCOUNT_DEFAULT)
