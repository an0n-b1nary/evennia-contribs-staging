# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""A page rendered for one reader, with links that respect visibility."""

from django.urls import NoReverseMatch, reverse

from evennia_guides import checks, markup, pages

PAGE_ROUTE = "evennia_guides:guide-page"


def page_url(page):
    """The web URL of a page, or None when the guide isn't mounted."""
    try:
        return reverse(PAGE_ROUTE, args=[page.key])
    except NoReverseMatch:
        return None


def _resolve(key):
    page = pages.get_page(key)
    return None if page is None else (page, checks.page_visible(page))


def context(*, staff):
    """A RenderContext for a staff or player reader."""
    return markup.RenderContext(
        staff=staff, resolve=_resolve, page_url=lambda page: page_url(page) or "#"
    )


def hidden_reason(page):
    """Why players can't see a page (for staff), or "" if they can."""
    if page.audience == "staff":
        return "Staff only"
    failing = [name for name in page.requires if not checks.check(name)]
    return f"Hidden from players until {', '.join(failing)}" if failing else ""


def html(page, *, staff):
    """``(html, toc)``; see ``markup.render_html``."""
    return markup.render_html(page.document, context(staff=staff))
