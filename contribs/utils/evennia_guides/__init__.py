# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_guides — player guides as web pages, written in Markdown.

Each page is a Markdown file with YAML front matter. Pages are found in the
``guides/`` directory of every installed app (so a contrib ships its own) and
in the host's ``GUIDES_DIRS``; a later page with the same key replaces an
earlier one. A page can require a named check, such as a reveal switch, and
stays hidden from players until the check passes. Pages are web-only; they
are separate from in-game ``help``.

Modules:

    pages    — Page, parse_page, get_page, all_pages, validate (raises GuideError)
    markup   — :::insight blocks, [[links]], HTML output
    checks   — register_check, check, can_view, is_staff
    render   — a page rendered for one reader
    views    — the web guide (index, page, principles, glossary)

Importing the package imports no models; import the modules you need.
"""

__version__ = "0.1.0"
