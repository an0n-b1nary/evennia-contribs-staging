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
