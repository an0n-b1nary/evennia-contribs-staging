# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from evennia.utils.test_resources import EvenniaCommandTest

from .accessibility import mutes_ambient
from .commands import CmdAmbient


class AmbientTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.account.options.options_dict = dict(self.account.options.options_dict)
        self.account.options.options_dict["mute_ambient_effects"] = (
            "Ambient effects",
            "Boolean",
            False,
        )

    def test_toggle_persists_on_account_and_applies_to_other_puppet(self):
        self.call(CmdAmbient(), "", "Ambient effects: enabled.")
        self.call(CmdAmbient(), "/mute", "Ambient effects: muted.")
        self.assertTrue(mutes_ambient(self.account))
        self.char2.account = self.account
        self.assertTrue(mutes_ambient(self.char2))
        self.assertTrue(self.account.attributes.get("mute_ambient_effects", category="option"))
        self.call(CmdAmbient(), "/unmute", "Ambient effects: enabled.")
        self.assertFalse(mutes_ambient(self.char2))

    def test_unknown_switch_and_missing_registration_do_not_change_preference(self):
        self.call(CmdAmbient(), "/oops", "Use +ambient")
        self.account.options.options_dict.pop("mute_ambient_effects")
        self.call(CmdAmbient(), "/mute", "Ambient preferences aren't available")
        self.assertTrue(mutes_ambient(self.account))

    def test_none_and_unowned_character_are_safe(self):
        self.assertFalse(mutes_ambient(None))
        self.char2.account = None
        self.assertFalse(mutes_ambient(self.char2))
