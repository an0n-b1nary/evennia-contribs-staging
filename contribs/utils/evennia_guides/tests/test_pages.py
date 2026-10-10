# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Page files: front matter, loading order, replacement, validation."""

import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase

from evennia_guides import pages
from evennia_guides.pages import GuideError, parse_page
from evennia_guides.tests.base import OVERRIDE, SITE, FreshPagesMixin, site_settings


def _page(meta, body="Body."):
    return f"---\n{meta}\n---\n{body}\n"


class TestParsePage(SimpleTestCase):
    def test_fields_and_defaults(self):
        page = parse_page(_page("key: Trading\ntitle: Money & trade\nrequires: X_ON"))
        self.assertEqual(page.key, "trading")
        self.assertEqual(page.kind, "guide")
        self.assertEqual(page.audience, "player")
        self.assertEqual(page.category, "General")
        self.assertEqual(page.requires, ("X_ON",))
        self.assertEqual(page.order, 100)
        self.assertFalse(page.footer)

    def test_lists_accept_one_string(self):
        page = parse_page(_page("key: a\ntitle: A\naliases: Alpha\nprinciples: [no-quota]"))
        self.assertEqual(page.aliases, ("alpha",))
        self.assertEqual(page.principles, ("no-quota",))

    def test_rejected(self):
        cases = {
            "no front matter": "Just text.",
            "bad or missing key": _page("title: A"),
            "reserved": _page("key: glossary\ntitle: G"),
            "missing title": _page("key: a"),
            "unknown front matter": _page("key: a\ntitle: A\ncolour: red"),
            "kind must be": _page("key: a\ntitle: A\nkind: essay"),
            "audience must be": _page("key: a\ntitle: A\naudience: everyone"),
            "order must be": _page("key: a\ntitle: A\norder: soon"),
            "never closed": _page("key: a\ntitle: A", ":::insight[Open]\nText."),
            "inside another insight": _page(
                "key: a\ntitle: A", ":::insight[One]\n:::insight[Two]\n:::\n:::"
            ),
            "closes nothing": _page("key: a\ntitle: A", "Text.\n:::"),
            "unknown block": _page("key: a\ntitle: A", ":::when[X]\nText.\n:::"),
            "needs a title": _page("key: a\ntitle: A", ":::insight\nText.\n:::"),
        }
        for expected, text in cases.items():
            with self.subTest(expected), self.assertRaisesRegex(GuideError, expected):
                parse_page(text)

    def test_containers_inside_code_fences_are_text(self):
        page = parse_page(_page("key: a\ntitle: A", "```\n:::insight[Not one]\n```"))
        self.assertEqual(page.document.insights(), [])


class TestLoading(FreshPagesMixin, SimpleTestCase):
    def test_contrib_pages_load_without_host_dirs(self):
        with site_settings(dirs=()):
            self.assertIsNotNone(pages.get_page("writing-guides"))
            self.assertIsNone(pages.get_page("start-here"))

    def test_host_dirs_and_aliases(self):
        with site_settings():
            self.assertEqual(pages.get_page("intro").key, "start-here")
            self.assertEqual(pages.get_page("START-HERE").title, "Start here")

    def test_a_later_page_replaces_an_earlier_one(self):
        with site_settings(dirs=(SITE, OVERRIDE)):
            self.assertEqual(pages.get_page("start-here").title, "Start here, our way")
            replaced = pages.registry().replaced
        self.assertEqual([key for key, _old, _new in replaced], ["start-here"])

    def test_a_bad_file_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "bad.md").write_text("no front matter", encoding="utf-8")
            Path(tmp, "good.md").write_text(_page("key: good\ntitle: Good"), encoding="utf-8")
            with site_settings(dirs=(tmp,)):
                self.assertIsNotNone(pages.get_page("good"))
                self.assertEqual(len(pages.registry().errors), 1)

    def test_sorting(self):
        with site_settings():
            kinds = [page.kind for page in pages.all_pages()]
        self.assertEqual(kinds, sorted(kinds, key=pages.KINDS.index))


class TestValidate(FreshPagesMixin, SimpleTestCase):
    def test_the_sample_site_is_clean(self):
        with site_settings():
            errors = [p for p in pages.validate() if p[0] == "error"]
        self.assertEqual(errors, [])

    def test_problems_are_reported(self):
        body = "See [[nowhere]].\n\n:::insight[I]{no-such-principle}\nText.\n:::\n\n`[[in-code]]`"
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.md").write_text(
                _page("key: a\ntitle: A\nrequires: NO_SUCH_SWITCH\naliases: [b, shared]", body),
                encoding="utf-8",
            )
            Path(tmp, "b.md").write_text(_page("key: b\ntitle: B"), encoding="utf-8")
            Path(tmp, "c.md").write_text(
                _page("key: c\ntitle: C\naliases: [shared]"), encoding="utf-8"
            )
            with site_settings(dirs=(tmp,)):
                messages = [message for _level, _source, message in pages.validate()]
        joined = "\n".join(messages)
        self.assertIn("link [[nowhere]] names no page", joined)
        self.assertNotIn("in-code", joined)
        self.assertIn("principle 'no-such-principle' names no principle page", joined)
        self.assertIn("check 'NO_SUCH_SWITCH' resolves to nothing", joined)
        self.assertIn("alias 'b' is another page's key", joined)
        self.assertIn("alias 'shared' is also", joined)

    def test_guides_check_command(self):
        out = StringIO()
        with site_settings():
            call_command("guides_check", stdout=out)
        self.assertIn("0 error(s)", out.getvalue())
        # Without the override, the trading page's check resolves to nothing.
        with site_settings(), self.settings(GUIDES_CHECKS={}), self.assertRaises(CommandError):
            call_command("guides_check", stdout=StringIO())
