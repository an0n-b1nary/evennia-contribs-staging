# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from unittest import TestCase

from .pagination import Page, contents, page_at, split_pages


class PaginationTests(TestCase):
    def test_explicit_breaks_preserve_paragraphs_unicode_and_empty_pages(self):
        pages = split_pages("  A\n\n  passage.\r\n---PAGE---\r\nÉpilogue\n---PAGE---\n")
        self.assertEqual([page.text for page in pages], ["A\n\n  passage.", "Épilogue", ""])
        self.assertEqual(
            split_pages("An inline ---PAGE--- stays."), (Page("An inline ---PAGE--- stays."),)
        )

    def test_numbering_does_not_use_python_negative_or_boolean_indexing(self):
        pages = (Page("first", "Opening"), Page("second"))
        self.assertEqual(page_at(pages, 2).text, "second")
        self.assertEqual(contents(pages), "1. Opening\n2. Page 2")
        for number in (0, -1, 3, True, "1", None):
            with self.subTest(number=number), self.assertRaises(ValueError):
                page_at(pages, number)
        with self.assertRaises(ValueError):
            page_at((), 1)

    def test_bad_text_is_rejected_and_page_is_immutable(self):
        from dataclasses import FrozenInstanceError

        with self.assertRaises(ValueError):
            split_pages(None)
        with self.assertRaises(ValueError):
            Page(1)
        with self.assertRaises(FrozenInstanceError):
            Page("Text").text = "Changed"


class ReadingTargetTests(TestCase):
    def test_strict_targets_do_not_reinterpret_numeric_suffixes_as_pages(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        from .pagination import reading_target

        book = object()
        actor = SimpleNamespace(contents=[book], location=None, search=Mock(return_value=None))
        self.assertEqual(reading_target(actor, "Old tome 2", positional_page=False), (None, None))
        actor.search.assert_called_once_with("Old tome 2", candidates=[book])
        actor.search.reset_mock()
        actor.search.return_value = book
        self.assertEqual(
            reading_target(actor, "Chronicle 2", "3", positional_page=False), (book, 3)
        )
        actor.search.assert_called_once_with("Chronicle 2", candidates=[book])
        with self.assertRaisesRegex(ValueError, "read/contents"):
            reading_target(actor, "Chronicle 2", "3", table=True, positional_page=False)

    def test_existing_callers_keep_their_positional_page_behavior(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        from .pagination import reading_target

        book = object()
        actor = SimpleNamespace(contents=[book], location=None, search=Mock(side_effect=[[], book]))
        self.assertEqual(reading_target(actor, "Old tome 2"), (book, 2))
        self.assertEqual(actor.search.call_args.args, ("Old tome",))
