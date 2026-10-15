# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Small, dependency-free helpers for explicitly authored IC pages.

Pages are not terminal-width wraps: their numbers remain stable across clients.
Storage, access checks, length limits and bookmarks belong to the caller.
"""

import re
from dataclasses import dataclass

PAGE_BREAK = "---PAGE---"


@dataclass(frozen=True)
class Page:
    text: str
    title: str = ""

    def __post_init__(self):
        if not isinstance(self.text, str) or not isinstance(self.title, str):
            raise ValueError("Page text and title must be strings.")


def split_pages(text):
    """Split on a standalone ---PAGE--- line, preserving internal whitespace.

    Leading/trailing page whitespace is stripped; empty pages are preserved so
    the caller can accept or reject them without silently renumbering pages.
    """
    if not isinstance(text, str):
        raise ValueError("Page text must be a string.")
    return tuple(Page(part.strip()) for part in re.split(r"(?m)^---PAGE---\r?$", text))


def page_at(pages, number):
    """Return a one-based page; reject booleans, zero and negative indices."""
    if type(number) is not int or not 1 <= number <= len(pages):
        raise ValueError(f"Choose a page from 1 to {len(pages)}.")
    return pages[number - 1]


def contents(pages):
    """Plain, screen-reader-friendly contents without exposing page bodies."""
    return "\n".join(
        f"{number}. {page.title or f'Page {number}'}" for number, page in enumerate(pages, 1)
    )
