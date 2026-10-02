# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Tag vocabulary: the ruleset default and a settings-supplied replacement."""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from evennia_rp_rules.ruleset import TagDef
from evennia_rp_rules.testing import RulesetTestMixin
from evennia_rp_rules.vocabulary import RulesetVocabulary, Vocabulary, get_vocabulary


class GrownVocabulary:
    """Stands in for a database-backed vocabulary."""

    def __init__(self):
        self._tags = {"juggling": TagDef("juggling", "Juggling")}

    def tags(self, kind=None):
        return [t for t in self._tags.values() if kind is None or t.kind == kind]

    def get(self, key):
        return self._tags.get(key)

    def find(self, text, *, kind=None):
        for tag in self.tags(kind):
            if text.casefold() in {s.casefold() for s in tag.spellings()}:
                return tag
        raise LookupError(f"Unknown tag '{text}'.")


class VocabularyTests(RulesetTestMixin, SimpleTestCase):
    def test_default_is_the_rulesets_tags(self):
        vocabulary = get_vocabulary()
        self.assertIsInstance(vocabulary, RulesetVocabulary)
        self.assertIsInstance(vocabulary, Vocabulary)
        self.assertEqual(sorted(t.key for t in vocabulary.tags()), ["climbing", "fire", "riddles"])
        self.assertEqual([t.key for t in vocabulary.tags("element")], ["fire"])
        self.assertEqual(vocabulary.get("riddles").name, "Riddles")
        self.assertIsNone(vocabulary.get("juggling"))
        self.assertEqual(vocabulary.find("rid").key, "riddles")
        with self.assertRaises(LookupError):
            vocabulary.find("fire", kind="domain")

    @override_settings(RP_RULES_VOCABULARY=f"{__name__}.GrownVocabulary")
    def test_settings_supply_a_vocabulary(self):
        vocabulary = get_vocabulary()
        self.assertIsInstance(vocabulary, GrownVocabulary)
        self.assertEqual(vocabulary.find("Juggling").key, "juggling")

    @override_settings(RP_RULES_VOCABULARY="no.such.Vocabulary")
    def test_bad_path_is_improperly_configured(self):
        with self.assertRaises(ImproperlyConfigured):
            get_vocabulary()
