# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Owned journal entries and paid, immutable editions of accessible text."""

import hashlib
import json

from django.db.models import F
from evennia.objects.models import ObjectDB

from evennia_links.pagination import Page
from evennia_links.transactions import atomic_objects

from .errors import CraftingError
from .models import CraftRecord, JournalRevision, ReadableEdition
from .pages import MAX_TEXT, authored_pages, configuration, validate


def readable_config(record):
    entry = next((row for row in record.verb_data if row["key"] == "readable"), None)
    if entry is None:
        raise CraftingError("There is nothing written here.")
    return entry["configuration"]


def latest_entries(record):
    latest = {}
    for entry in JournalRevision.objects.filter(craft=record).order_by("page", "revision"):
        latest[entry.page] = entry
    return list(latest.values())


def current_pages(item, config):
    if "journal" not in config:
        return authored_pages(config)
    record = CraftRecord.objects.get(item_id=item.pk)
    return tuple(Page(entry.text, entry.title) for entry in latest_entries(record))


def page_authors(record):
    """Identity snapshots survive gifting, renaming and source-object deletion."""
    config = readable_config(record)
    if "journal" in config:
        return [
            {"id": entry.author_id, "name": entry.author_name, "revision": entry.pk}
            for entry in latest_entries(record)
        ]
    edition = ReadableEdition.objects.filter(craft=record).first()
    if edition:
        return edition.authors
    return [{"id": record.crafter_id, "name": record.crafter_name} for _ in authored_pages(config)]


def page_credit(record, pages, number):
    if (
        "journal" not in readable_config(record)
        and not ReadableEdition.objects.filter(craft=record).exists()
    ):
        return ""
    # A host reader may redact or reorder pages. Do not attach a guessed author.
    canonical = current_pages_for_record(record)
    if tuple(pages) != canonical:
        return "Text attribution (OOC): supplied by the host reader."
    author = page_authors(record)[number - 1]
    return f"Text by (OOC): {author['name']}"


def current_pages_for_record(record):
    config = readable_config(record)
    if "journal" in config:
        return tuple(Page(entry.text, entry.title) for entry in latest_entries(record))
    return authored_pages(config)


def nearby(actor, item):
    holder = ObjectDB.objects.filter(pk=item.pk).values_list("db_location_id", flat=True).first()
    room_id = ObjectDB.objects.filter(pk=actor.pk).values_list("db_location_id", flat=True).get()
    if holder not in {actor.pk, room_id} or holder is None:
        raise CraftingError("Carry the source or visit it first.")


@atomic_objects
def snapshot(actor, item):
    """Copy only the authorized provider output, never its underlying raw prose."""
    from .letters import lock_objects, require_open

    lock_objects(actor, item)
    nearby(actor, item)
    source = CraftRecord.objects.filter(item_id=item.pk).first()
    state = require_open(source) if source else None
    record, pages = configuration(actor, item)
    pages = tuple(pages)
    if not pages:
        raise CraftingError("There are no written pages to copy.")
    config = validate({"pages": [{"title": page.title, "text": page.text} for page in pages]})
    authors = (
        page_authors(record)
        if pages == current_pages_for_record(record)
        else [{"id": None, "name": "host reader"} for _ in pages]
    )
    payload = {"source": record.pk, "configuration": config, "authors": authors}
    if state is not None:
        payload["letter"] = {"addressee": state.addressee, "seal_number": state.seal_number}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return record, config, authors, fingerprint


@atomic_objects
def write(actor, item, title, body, *, page=None):
    """Append or revise one's own entry while holding the journal; writing is free."""
    from .services import _require

    # Same actor-before-item order as crafting/economy handoff services.
    # Reserve SQLite's writer before any reads; row locks serialize PostgreSQL.
    ObjectDB.objects.filter(pk=actor.pk).update(db_key=F("db_key"))
    ObjectDB.objects.select_for_update().get(pk=actor.pk)
    holder = (
        ObjectDB.objects.select_for_update()
        .filter(pk=item.pk)
        .values_list("db_location_id", flat=True)
        .first()
    )
    _require(actor, spending=False)
    if holder != actor.pk:
        raise CraftingError("Carry the journal to write in it.")
    record, _ = configuration(actor, item)
    from .models import LetterState

    if LetterState.objects.filter(craft=record, seal_number__gt=0).exists():
        raise CraftingError("Sealing permanently freezes the enclosed text.")
    config = readable_config(record)
    if "journal" not in config:
        raise CraftingError("Only blank journals accept new writing.")
    if not item.access(actor, "write", default=True):
        raise CraftingError("You cannot write in that journal.")
    normalized = validate({"pages": [{"title": title, "text": body}]})["pages"][0]
    entries = latest_entries(record)
    if page is None:
        page = len(entries) + 1
        if page > config["journal"]:
            raise CraftingError("This journal has no unused pages.")
        revision = 1
    else:
        if type(page) is not int or not 1 <= page <= len(entries):
            raise CraftingError("Choose an existing journal page to revise.")
        previous = entries[page - 1]
        if previous.author_id != actor.pk:
            raise CraftingError("You may revise only your own journal entries.")
        revision = previous.revision + 1
    total = sum(len(entry.text) + len(entry.title) for entry in entries if entry.page != page)
    if total + len(normalized["title"]) + len(normalized["text"]) > MAX_TEXT:
        raise CraftingError(
            f"Journal pages and titles may contain at most {MAX_TEXT} characters total."
        )
    return JournalRevision.objects.create(
        craft=record,
        page=page,
        revision=revision,
        author_id=actor.pk,
        author_name=actor.key,
        **normalized,
    )


@atomic_objects
def history(actor, item, page):
    from .letters import lock_objects, require_open

    lock_objects(actor, item)
    nearby(actor, item)
    source = CraftRecord.objects.filter(item_id=item.pk).first()
    if source:
        require_open(source)
    record, pages = configuration(actor, item)
    if "journal" not in readable_config(record):
        raise CraftingError("That is not a journal.")
    if tuple(pages) != current_pages_for_record(record):
        raise CraftingError("The host reader does not expose journal history.")
    if type(page) is not int or not 1 <= page <= len(pages):
        raise CraftingError("Choose an existing journal page.")
    rows = JournalRevision.objects.filter(craft=record, page=page)
    return "\n\n".join(
        f"Revision {row.revision}, text by (OOC): {row.author_name}, {row.created.isoformat()}\n"
        f"{row.title}\n{row.text}"
        for row in rows
    )


@atomic_objects
def copy_book(actor, source, key, name, description, selected, *, expected=None, addressee=None):
    from .services import craft

    ObjectDB.objects.filter(pk=actor.pk).update(db_key=F("db_key"))
    ObjectDB.objects.select_for_update().get(pk=actor.pk)
    ObjectDB.objects.select_for_update().get(pk=source.pk)
    record, config, authors, fingerprint = snapshot(actor, source)
    if expected is not None and expected != fingerprint:
        raise CraftingError("The source has changed. Start a new copy draft.")
    # Always a carried readable: copying words never clones equipment, fixtures,
    # journal capacity, modifiers or a companion's other components.
    from .models import LetterState

    state = LetterState.objects.filter(craft=record).first()
    facets = (
        {"letter": {"addressee": state.addressee if addressee is None else addressee}}
        if state or addressee is not None
        else None
    )
    item = craft(actor, key, "readable", name, description, config, selected, facets=facets)
    ReadableEdition.objects.create(
        craft=item.craft_record,
        source=record,
        authors=authors,
        source_fingerprint=fingerprint,
    )
    return item


def provenance(record):
    edition = ReadableEdition.objects.filter(craft=record).first()
    if edition:
        names = list(dict.fromkeys(author["name"] for author in edition.authors))
        return f"Copied by {record.crafter_name}; text by {', '.join(names)}; source craft #{edition.source_id}. {record.hallmark}"
    if "readable" in record.behaviour_keys and "journal" in readable_config(record):
        names = list(dict.fromkeys(entry.author_name for entry in latest_entries(record)))
        return f"Binding: {record.hallmark}; journal text by {', '.join(names) or 'no writers yet'}"
    return record.hallmark
