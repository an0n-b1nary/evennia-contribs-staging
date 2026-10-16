# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""A missing optional metadata provider hides features and refuses new ones."""

from unittest import skipIf

from django.apps import apps
from evennia.utils.test_resources import EvenniaTest

from .errors import CraftingError
from .models import CraftRecord
from .tests import CraftingFixture


@skipIf(apps.is_installed("evennia_lore"), "requires actual lore absence")
class MissingLoreTests(CraftingFixture, EvenniaTest):
    def setUp(self):
        super().setUp()
        self.unlock()

    def test_existing_metadata_degrades_to_plain_text_and_cannot_authorize_new_crafts(self):
        item = self.book()
        row = item.craft_record
        metadata = {
            "lore_citations": [{"entry": 123, "page": None}],
            "lore_recognition": [{"entry": 123, "text": "Hidden knowledge", "niche": "writing-0"}],
        }
        # A previously shipped record survives removing the optional provider.
        CraftRecord.objects.filter(pk=row.pk).update(prose=row.prose | {"facets": metadata})
        self.assertEqual(item.read(self.char1), "A record of the road.")
        self.assertNotIn("Hidden knowledge", item.get_display_desc(self.char1))
        before = self.held()
        with self.assertRaisesMessage(CraftingError, "facet is unavailable"):
            self.book(facets=metadata)
        self.assertEqual(self.held(), before)
