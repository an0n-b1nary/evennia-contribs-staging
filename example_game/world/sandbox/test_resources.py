# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Actual maps/social/login seams, and fresh-process partner absence checks."""

from importlib.util import find_spec
from unittest.mock import patch

from django.apps import apps
from django.conf import settings
from django.test import override_settings
from evennia.utils.test_resources import EvenniaTest
from evennia_rp_resources import gathering
from evennia_rp_resources.batch import run_weekly_batch
from evennia_rp_resources.catalog import seed_catalog
from evennia_rp_resources.services import grant, total_held
from typeclasses.characters import Character
from typeclasses.rooms import Room

from evennia_links import runtime


class ResourceSeams(EvenniaTest):
    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        seed_catalog(update=True)

    def test_real_terrain_provider_and_common_pool(self):
        self.room1.set_terrain({"forest"})
        if apps.is_installed("evennia_maps"):
            self.assertEqual(gathering.terrain_for(self.room1), "forest")
        else:
            self.room1.tags.add("forest", category="terrain")
            self.assertEqual(gathering.terrain_for(self.room1), "forest")
        keys = {resource.key for resource in gathering.pool()}
        self.assertIn("grain", keys)
        self.assertIn("timber", keys)
        self.assertNotIn("rare-crystal", keys)

    def test_gathering_field_uses_real_social_profile_and_reveal_policy(self):
        from evennia_social.commands.finger import CmdFinger

        gathering.set_lean(self.char2, "grain")
        profile = CmdFinger._format_profile(self.char2, self.char2)
        self.assertIn("Gathering", profile)
        self.assertIn("Grain", profile)
        with override_settings(RP_RESOURCES_REVEALED=False):
            self.assertNotIn("Gathering", CmdFinger._format_profile(self.char2, self.char2))
            self.assertIn("Gathering", CmdFinger._format_profile(self.char1, self.char2))

    def test_login_hook_shows_summary_once(self):
        run_weekly_batch("2026-W40", characters=[self.char2])
        with patch.object(self.char2, "msg") as msg:
            self.char2.at_post_puppet()
            self.char2.at_post_puppet()
        summaries = [
            call.args[0]
            for call in msg.call_args_list
            if call.args
            and isinstance(call.args[0], str)
            and "This week you gathered" in call.args[0]
        ]
        self.assertEqual(len(summaries), 1)

    def test_cmdset_import_registers_commands_with_partners_absent(self):
        from commands.default_cmdsets import CharacterCmdSet

        keys = {command.key for command in CharacterCmdSet().commands}
        self.assertTrue({"+resources", "+gather", "+runtime"} <= keys)
        self.assertEqual(total_held(self.char2), 0)
        grant(self.char2, "grain", 2)
        self.assertEqual(total_held(self.char2), 2)

    def test_absent_profiles_really_cannot_import_partners(self):
        for name in getattr(settings, "RESOURCES_ABSENT_PARTNERS", []):
            self.assertFalse(apps.is_installed(name))
            self.assertIsNone(find_spec(name))

    def test_runtime_control_changes_batch_without_reload(self):
        runtime.set("RP_RESOURCES_WEEKLY_QUANTITY", 3, by=self.char1)
        result = run_weekly_batch("2026-W40", characters=[self.char2])
        self.assertEqual(result["errors"], [])
        self.assertEqual(total_held(self.char2), 3)
