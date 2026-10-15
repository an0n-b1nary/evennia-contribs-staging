# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Immutable authored pages and personal reading progress.

Read from the verified verb configuration, never mutable item attributes.
This module deliberately does not implement journals, copying or lore grants.
"""

from evennia_links.pagination import Page, contents, page_at, split_pages

from .behaviours import text
from .errors import CraftingError

MAX_PAGES = 100
MAX_TEXT = 12000
MAX_TITLE = 80
BOOKMARK_CATEGORY = "rp_crafting_reading"


def validate(config):
    if "pages" in config and "text" in config:
        raise CraftingError("Choose readable text or pages, not both.")
    if "pages" not in config:
        value = text(config.get("text", ""), "Readable text", MAX_TEXT, required=True)
        pages = split_pages(value)
        if len(pages) == 1:
            return {"text": value}
        config = {"pages": [{"title": "", "text": page.text} for page in pages]}
    entries = config["pages"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_PAGES:
        raise CraftingError(f"Choose 1-{MAX_PAGES} readable pages.")
    normalized = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {"text", "title"}:
            raise CraftingError("Each page needs text and an optional title.")
        title = text(entry.get("title", ""), "Page title", MAX_TITLE)
        if not title.isprintable() and title:
            raise CraftingError("Page titles must be single-line text.")
        normalized.append(
            {
                "title": title,
                "text": text(entry.get("text", ""), "Page text", MAX_TEXT, required=True),
            }
        )
    if sum(len(page["text"]) + len(page["title"]) for page in normalized) > MAX_TEXT:
        raise CraftingError(
            f"Readable pages and titles may contain at most {MAX_TEXT} characters total."
        )
    return {"pages": normalized}


def authored_pages(config):
    """Legacy text remains one page, including old delimiter-shaped prose."""
    if "pages" in config:
        return tuple(Page(entry["text"], entry.get("title", "")) for entry in config["pages"])
    return (Page(config["text"]),)


def configuration(actor, item):
    from .behaviours import behaviour
    from .models import CraftRecord

    if not item.access(actor, "view", default=True):
        raise CraftingError("You cannot read that.")
    record = CraftRecord.objects.filter(item_id=item.pk).first()
    entry = (
        next((entry for entry in record.verb_data if entry["key"] == "readable"), None)
        if record
        else None
    )
    if entry is None:
        raise CraftingError("There is nothing written here.")
    implementation = behaviour("readable")
    if implementation.role != "verb":
        raise CraftingError("That action is unavailable.")
    # Never recover raw pages behind a custom verb's access checks/redaction.
    # Standard contents requests do not perform a full-text read.
    provider = getattr(implementation, "get_pages", None)
    if callable(provider):
        pages = provider(actor, item, entry["configuration"])
    else:
        pages = (Page(implementation.invoke(actor, item, entry["configuration"])),)
    return record, pages


def read(actor, item, number=None, *, table=False):
    record, pages = configuration(actor, item)
    if table:
        noun = "page" if len(pages) == 1 else "pages"
        return f"Contents ({len(pages)} {noun}):\n{contents(pages)}"
    bookmark_key = f"craft_{record.pk}"
    if number is None:
        number = actor.attributes.get(bookmark_key, category=BOOKMARK_CATEGORY, default=1)
    try:
        page = page_at(pages, number)
    except ValueError as exc:
        raise CraftingError(str(exc)) from None
    actor.attributes.add(bookmark_key, number, category=BOOKMARK_CATEGORY)
    # Retain the original single-text read output exactly.
    if len(pages) == 1 and not page.title:
        return page.text
    title = f": {page.title}" if page.title else ""
    return f"Page {number} of {len(pages)}{title}\n{page.text}"
