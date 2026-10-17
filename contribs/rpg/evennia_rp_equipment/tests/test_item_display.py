# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real equipment rendering calls independent optional providers exactly once."""

from unittest.mock import patch

from evennia_rp_equipment import item_display

from .base import GearTest


class ItemDisplayTests(GearTest):
    def test_neutral_provider_transforms_plain_gear_description_and_worn_line_once(self):
        calls = []

        def provider(item, looker, context, text):
            calls.append(context)
            return text + " [host annotation]"

        item = self.make_item(self.char1, "cloak", line="a cloak")
        item.db.desc = "Original."
        with patch.dict(item_display._providers, {}, clear=True):
            item_display.register("host", provider)
            item_display.register("host", provider)
            self.assertEqual(item.get_worn_line(self.char2), "a cloak [host annotation]")
            self.assertEqual(item.get_display_desc(self.char2), "Original. [host annotation]")
        self.assertEqual(calls, ["worn", "desc"])
        self.assertEqual(item.worn_line, "a cloak")
        self.assertEqual(item.db.desc, "Original.")

    def test_broken_provider_preserves_prior_text_and_later_providers_still_render(self):
        def broken(*args):
            raise RuntimeError("optional provider missing")

        item = self.make_item(self.char1, "cloak", line="a cloak")
        with patch.dict(item_display._providers, {}, clear=True):
            item_display.register("a", broken)
            item_display.register("b", lambda item, looker, context, text: text + " [extra]")
            with self.assertLogs("evennia", level="ERROR"):
                self.assertEqual(item.get_worn_line(self.char2), "a cloak [extra]")

    def test_base_selection_precedes_all_extra_providers(self):
        item = self.make_item(self.char1, "cloak", line="original")
        with patch.dict(item_display._providers, {}, clear=True):
            item_display.register("a_extra", lambda item, looker, context, text: text + " [extra]")
            item_display.register(
                "z_base", lambda item, looker, context, text: "selected", phase="base"
            )
            self.assertEqual(item.get_worn_line(self.char2), "selected [extra]")
