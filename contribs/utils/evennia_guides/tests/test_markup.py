# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The page body: insights, links, tables, sections, and what never passes through."""

from types import SimpleNamespace

from django.test import SimpleTestCase

from evennia_guides import markup


def _page(key, title, summary=""):
    return SimpleNamespace(key=key, title=title, summary=summary)


PAGES = {
    "open": (_page("open", "Open page", "Always there."), True),
    "hidden": (_page("hidden", "Hidden page"), False),
    "no-quota": (_page("no-quota", "RP is never a quota"), True),
}


def _render(body, *, staff=False):
    ctx = markup.RenderContext(
        staff=staff, resolve=PAGES.get, page_url=lambda page: f"/guide/{page.key}/"
    )
    return markup.render_html(markup.parse(body), ctx)


class TestInsights(SimpleTestCase):
    def test_an_insight_is_an_aside_after_its_paragraph(self):
        html, _toc = _render("First.\n\n:::insight[Why]{no-quota}\nBecause.\n:::\n\nNext.")
        self.assertLess(html.index("First."), html.index("<aside"))
        self.assertLess(html.index("</aside>"), html.index("Next."))
        self.assertIn('aria-label="Design insight: Why"', html)
        self.assertIn('id="insight-why"', html)
        self.assertIn('Principle: <a href="/guide/no-quota/">RP is never a quota</a>', html)

    def test_a_tag_naming_a_hidden_page_is_left_out(self):
        html, _toc = _render(":::insight[Why]{hidden}\nBecause.\n:::")
        self.assertNotIn("Principle:", html)
        self.assertNotIn("Hidden page", html)


class TestLinks(SimpleTestCase):
    def test_visible_link_uses_title_and_summary(self):
        html, _toc = _render("See [[open]].")
        self.assertIn('<a href="/guide/open/" title="Always there.">Open page</a>', html)

    def test_label(self):
        html, _toc = _render("See [[open|this one]].")
        self.assertIn(">this one</a>", html)

    def test_hidden_link_is_plain_text_for_players(self):
        html, _toc = _render("See [[hidden|the page]].")
        self.assertIn("See the page.", html)
        self.assertNotIn("/guide/hidden/", html)
        self.assertNotIn("Hidden page", html)

    def test_hidden_link_is_marked_for_staff(self):
        html, _toc = _render("See [[hidden]].", staff=True)
        self.assertIn('class="evennia-guides-link-hidden"', html)
        self.assertIn("/guide/hidden/", html)

    def test_unknown_link_is_text_even_for_staff(self):
        html, _toc = _render("See [[nowhere-yet]].", staff=True)
        self.assertIn("See nowhere yet.", html)

    def test_links_in_code_are_left_alone(self):
        html, _toc = _render("Type `[[open]]`.")
        self.assertIn("<code>[[open]]</code>", html)
        self.assertEqual(markup.parse("Type `[[open]]`.").links(), [])


class TestBody(SimpleTestCase):
    def test_raw_html_is_text(self):
        html, _toc = _render("<script>alert(1)</script> and <b>bold</b>")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_javascript_links_are_not_links(self):
        html, _toc = _render("[click](javascript:alert(1))")
        self.assertNotIn('href="javascript', html)

    def test_tables_sit_in_a_focusable_scroll_region(self):
        html, _toc = _render("| a | b |\n|---|---|\n| 1 | 2 |")
        self.assertIn('<div class="evennia-guides-table-scroll" role="region"', html)
        self.assertIn('tabindex="0"', html)
        self.assertIn('<table class="table table-sm">', html)

    def test_sections_make_anchors_and_a_toc(self):
        html, toc = _render("Intro.\n\n## Start *here*\n\nA.\n\n## Start here\n\nB.")
        self.assertEqual(toc, [("start-here", "Start here"), ("start-here-2", "Start here")])
        self.assertIn('<h2 id="start-here">Start <em>here</em></h2>', html)

    def test_a_heading_inside_an_insight_stays_inside_it(self):
        document = markup.parse(":::insight[Why]\n## Not a section\n:::")
        self.assertEqual(len(document.sections), 1)
