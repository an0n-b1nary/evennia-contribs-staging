# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Published lore references, page acquisitions and staff-authored tomes."""

from django.conf import settings
from django.db import transaction
from evennia.objects.objects import DefaultObject
from evennia.utils.ansi import strip_ansi
from evennia.utils.create import create_object

from evennia_links.pagination import Page, page_at
from evennia_links.pagination import contents as render_contents
from evennia_links.transactions import atomic_objects

from .models import LoreAcquisition, LoreEntry, LoreTomeRecord


class LoreItemError(ValueError):
    pass


def staff(actor):
    from .commands import is_staff

    return is_staff(actor)


def label(value):
    return " ".join(strip_ansi(value).split())


def held_entry(actor, identifier):
    if type(identifier) is not int or identifier <= 0:
        raise LoreItemError("Choose a published lore entry.")
    entries = LoreEntry.objects.filter(pk=identifier, status=LoreEntry.Status.PUBLISHED)
    if transaction.get_connection().in_atomic_block:
        entries = entries.select_for_update()
    entry = entries.first()
    if entry is None:
        raise LoreItemError("Choose a published lore entry.")
    if (
        not staff(actor)
        and not LoreAcquisition.objects.filter(entry=entry, character=actor).exists()
    ):
        raise LoreItemError("You must hold that lore entry in your compendium.")
    return entry


def validate_citations(actor, value, page_count):
    if not isinstance(value, list) or len(value) > 100:
        raise LoreItemError("Choose at most 100 lore citations.")
    rows, seen = [], set()
    for row in value:
        if not isinstance(row, dict) or set(row) - {"entry", "page"} or "entry" not in row:
            raise LoreItemError("Citations need an entry and optional page.")
        entry = held_entry(actor, row["entry"])
        number = row.get("page")
        if number is not None and (type(number) is not int or not 1 <= number <= page_count):
            raise LoreItemError("Pin citations to an existing authored page.")
        identity = entry.pk, number
        if identity in seen:
            raise LoreItemError("Don't repeat a citation on the same page.")
        seen.add(identity)
        rows.append({"entry": entry.pk, "page": number})
    return rows


@transaction.atomic
def acquire_page(actor, citations, number):
    """Only explicit successful reads call this; enumeration is side-effect free."""
    from .signals import lore_acquired

    identifiers = {row["entry"] for row in citations if row.get("page") in (None, number)}
    lines = []
    for entry in LoreEntry.objects.filter(
        pk__in=identifiers, status=LoreEntry.Status.PUBLISHED
    ).order_by("entry_number"):
        acquisition, created = LoreAcquisition.objects.get_or_create(
            entry=entry,
            character=actor,
            defaults={"character_name": actor.key, "source": LoreAcquisition.Source.READ},
        )
        if created:
            transaction.on_commit(
                lambda acq=acquisition, lore=entry: lore_acquired.send_robust(
                    sender=LoreAcquisition,
                    acquisition=acq,
                    entry=lore,
                    character=actor,
                )
            )
        lines.append(
            f"[Lore] You recognise: {label(entry.title)} (#{entry.entry_number}) — {label(entry.kind_label)}."
        )
    return "\n".join(lines)


def validate_pages(pages):
    if not isinstance(pages, list) or not 1 <= len(pages) <= 100:
        raise LoreItemError("A tome needs 1-100 authored pages.")
    normalized = []
    for page in pages:
        if not isinstance(page, dict) or set(page) - {"title", "text"}:
            raise LoreItemError("Each page needs text and an optional title.")
        title, text = page.get("title", ""), page.get("text", "")
        if (
            not isinstance(title, str)
            or len(title.strip()) > 80
            or (title and not title.isprintable())
        ):
            raise LoreItemError("Page titles must be single-line text of at most 80 characters.")
        if not isinstance(text, str) or not text.strip():
            raise LoreItemError("Page text is required.")
        normalized.append({"title": title.strip(), "text": text.strip()})
    if sum(len(page["title"]) + len(page["text"]) for page in normalized) > 12000:
        raise LoreItemError("Tome pages and titles may contain at most 12000 characters total.")
    return normalized


@atomic_objects
def create_tome(actor, name, description, pages, citations):
    if not staff(actor):
        raise LoreItemError("Staff only.")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise LoreItemError("Choose a tome name of 1-80 characters.")
    if not isinstance(description, str) or not 1 <= len(description.strip()) <= 4000:
        raise LoreItemError("Choose a tome description of 1-4000 characters.")
    pages = validate_pages(pages)
    citations = validate_citations(actor, citations, len(pages))
    item = create_object(
        getattr(settings, "LORE_TOME_TYPECLASS", LoreTome),
        key=name.strip(),
        location=actor,
        home=actor,
    )
    if not isinstance(item, LoreTome):
        raise LoreItemError("The host tome typeclass must inherit LoreTome.")
    item.db.desc = description.strip()
    LoreTomeRecord.objects.create(
        item_id=item.pk,
        author_id=actor.pk,
        author_name=actor.key,
        pages=pages,
        citations=citations,
    )
    return item


class LoreTome(DefaultObject):
    """A staff-made fixed readable, independent of the crafting contrib."""

    @atomic_objects
    def read(self, reader, page=None, *, contents=False):
        if not self.access(reader, "view", default=True) or not self.access(
            reader, "read", default=True
        ):
            raise LoreItemError("You cannot read that.")
        record = LoreTomeRecord.objects.filter(item_id=self.pk).first()
        if record is None:
            raise LoreItemError("This tome has no published pages.")
        pages = tuple(Page(row["text"], row["title"]) for row in record.pages)
        if contents:
            return f"Contents ({len(pages)} pages):\n{render_contents(pages)}"
        key, category = f"tome_{record.pk}", "lore_reading"
        if page is None:
            page = reader.attributes.get(key, category=category, default=1)
            if type(page) is not int or not 1 <= page <= len(pages):
                page = 1
        selected = page_at(pages, page)
        extra = acquire_page(reader, record.citations, page)
        if len(pages) > 1:
            reader.attributes.add(key, page, category=category)
        title = f": {selected.title}" if selected.title else ""
        result = f"Page {page} of {len(pages)}{title}\n{selected.text}"
        return f"{result}\n{extra}" if extra else result
