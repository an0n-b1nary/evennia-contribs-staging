# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Investigation preferences survive object eviction across all entry points."""

from decimal import Decimal
from importlib import import_module

from django.conf import settings
from django.test import RequestFactory, override_settings
from evennia.objects.models import ObjectDB
from evennia.utils.test_resources import EvenniaCommandTest

from evennia_lore.commands import CmdInvestigate
from evennia_lore.models import LoreEntry, LoreTag
from evennia_lore.selection import _build_pool
from evennia_lore.views import LoreLeanView


@override_settings(
    ROOT_URLCONF="evennia_lore.tests",
    LORE_SESSION_CONTEXT_PROVIDER=None,
    LORE_PASSIVE_LEAN_MULTIPLIER=Decimal("2.0"),
)
class TestLoreLeanPersistence(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.account2.characters.add(self.char2)
        self.tag = LoreTag.objects.create(name="Alchemy")
        self.entry = LoreEntry.create_entry(title="The Codex", author=self.char1)
        self.entry.tags.add(self.tag)

    def _reload_character(self):
        previous = self.char2
        previous.flush_from_cache(force=True)
        self.char2 = ObjectDB.objects.get(pk=previous.pk)
        self.assertIsNot(self.char2, previous)

    def _web(self, data=None):
        factory = RequestFactory()
        request = factory.get("/lore/lean/") if data is None else factory.post("/lore/lean/", data)
        request.user = self.account2
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        return LoreLeanView.as_view()(request)

    def _assert_lean(self, lean_type, value, weight):
        output = self.call(CmdInvestigate(), "", caller=self.char2)
        if lean_type:
            self.assertIn(f"Current lean: {lean_type.capitalize()} — {value}", output)
        else:
            self.assertIn("You have no active lore lean", output)
        self.assertEqual(dict(_build_pool(self.char2, None))[self.entry], weight)
        response = self._web()
        response.render()
        initial = response.context_data["form"].initial
        self.assertEqual(initial, {"lean_type": lean_type or "", "lean_value": value or ""})

    def test_new_character_has_no_lean(self):
        self._assert_lean(None, None, 1)

    def test_command_lean_survives_cache_eviction(self):
        self.call(CmdInvestigate(), "/tag Alchemy", caller=self.char2)
        self._reload_character()
        self._assert_lean("tag", "Alchemy", 2)

    def test_entry_lean_survives_cache_eviction(self):
        self.call(CmdInvestigate(), f"/entry #{self.entry.entry_number}", caller=self.char2)
        self._reload_character()
        self._assert_lean("entry", self.entry.entry_number, 2)

    def test_theme_lean_survives_cache_eviction(self):
        self.tag.is_major = True
        self.tag.save()
        self.call(CmdInvestigate(), "/theme Alchemy", caller=self.char2)
        self._reload_character()
        self._assert_lean("theme", "Alchemy", 4)

    def test_command_clear_survives_cache_eviction(self):
        self.call(CmdInvestigate(), "/tag Alchemy", caller=self.char2)
        self._reload_character()
        self.call(CmdInvestigate(), "/clear", caller=self.char2)
        self._reload_character()
        self._assert_lean(None, None, 1)

    def test_web_lean_survives_cache_eviction(self):
        response = self._web({"lean_type": "tag", "lean_value": "Alchemy"})
        self.assertEqual(response.status_code, 302)
        self._reload_character()
        self._assert_lean("tag", "Alchemy", 2)

    def test_web_clear_survives_cache_eviction(self):
        self.call(CmdInvestigate(), "/tag Alchemy", caller=self.char2)
        self._reload_character()
        response = self._web({"lean_type": "", "lean_value": ""})
        self.assertEqual(response.status_code, 302)
        self._reload_character()
        self._assert_lean(None, None, 1)
