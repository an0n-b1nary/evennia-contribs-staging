# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Journal authoring and reviewable copy drafts."""

from evennia.objects.models import ObjectDB
from evennia.utils.ansi import strip_ansi

from . import services
from .command_base import CraftCommand
from .command_syntax import bare_value, select_resource
from .errors import CraftingError
from .readables import copy_book, history, snapshot, write


def find_item(actor, name):
    candidates = list(actor.contents)
    if actor.location:
        candidates += list(actor.location.contents)
    return actor.search(name, candidates=candidates)


def copy_draft(command):
    from .behaviours import text
    from .commands import DRAFT_KEY

    if command.rhs is None or "/" not in command.rhs:
        raise CraftingError("Usage: +craft/copy source item = niche/new item name")
    source = find_item(command.caller, command.lhs.strip())
    if source is None:
        return
    key, name = (value.strip() for value in command.rhs.split("/", 1))
    record, config, _, fingerprint = snapshot(command.caller, source)
    services.craft_cost(command.caller, key, "readable", config)
    draft = {
        "copy_source": source.pk,
        "copy_fingerprint": fingerprint,
        "niche": key,
        "name": text(name, "Item name", 80, required=True),
        "description": record.prose.get("description") or "A bound copy.",
        "selected": {},
    }
    from .models import LetterState

    state = LetterState.objects.filter(craft=record).first()
    if state is not None:
        draft["addressee"] = state.addressee
    command.caller.attributes.add(DRAFT_KEY, draft)
    command.msg(
        f"Copy draft saved: {draft['name']}. It starts with the source's description; "
        "set your own with +craft/desc. Use +craft to review its pages and cost."
    )


def continue_copy(command, switch, draft):
    from .commands import DRAFT_KEY, costs_text

    if switch not in ("", "desc", "resources", "unresource", "finish", "addressee"):
        raise CraftingError(
            "Copy drafts allow /desc, /addressee, /resources, /unresource, /finish or /cancel. Start a new craft for rewritten text."
        )
    if switch == "desc":
        from .behaviours import text

        # The binding is the copier's own work; only the pages are copied.
        value = bare_value(command)
        draft["description"] = text(value, "Description", 4000, required=True)
        command.caller.attributes.add(DRAFT_KEY, draft)
        command.msg(f"Copy draft saved: {draft['name']}.")
        return
    source = ObjectDB.objects.filter(pk=draft["copy_source"]).first()
    if source is None:
        raise CraftingError("The source no longer exists. Start a new copy draft.")
    if switch == "finish":
        item = copy_book(
            command.caller,
            source,
            draft["niche"],
            draft["name"],
            draft["description"],
            draft["selected"],
            expected=draft["copy_fingerprint"],
            addressee=draft.get("addressee"),
        )
        command.caller.attributes.remove(DRAFT_KEY)
        command.msg(
            f"You copy {item.key}. Hallmark (OOC): {item.get_display_provenance(command.caller)}."
        )
        return
    record, config, authors, fingerprint = snapshot(command.caller, source)
    if fingerprint != draft["copy_fingerprint"]:
        raise CraftingError("The source has changed. Start a new copy draft.")
    if switch == "addressee":
        from .letters import line

        value = bare_value(command)
        draft["addressee"] = line(value, "Addressee")
        command.caller.attributes.add(DRAFT_KEY, draft)
        command.msg(f"Copy draft saved: {draft['name']}.")
        return
    if switch in ("resources", "unresource"):
        value = bare_value(command)
        select_resource(draft, value, remove=switch == "unresource")
        command.caller.attributes.add(DRAFT_KEY, draft)
        command.msg(f"Copy draft saved: {draft['name']}.")
        return
    _, _, _, cost = services.craft_cost(command.caller, draft["niche"], "readable", config)
    rows = [f"Copy draft: {draft['name']} (source craft #{record.pk})", draft["description"]]
    if "addressee" in draft:
        rows.append(
            f"Addressee (IC): {draft['addressee'] or '(unspecified)'} — copy starts unsealed."
        )
    for number, (page, author) in enumerate(zip(config["pages"], authors, strict=True), 1):
        rows.append(
            f"{number}. {page['title'] or f'Page {number}'}\n{page['text']}\nText by (OOC): {author['name']}"
        )
    selected = ", ".join(f"{amount} {key}" for key, amount in draft["selected"].items()) or "none"
    rows.append(
        f"Cost: {costs_text(cost)}. Selected: {selected}.\n+craft/finish pays and creates the copy."
    )
    command.msg("\n".join(rows))


class CmdJournal(CraftCommand):
    """Write in a carried journal; only your own entries may be revised.

    Usage:
      +journal/write <journal> = <text>
      +journal/title <journal>/<page number> = <title>
      +journal/revise <journal>/<page number> = <text>
      +journal/history <journal>/<page number>

    Writing is free. Earlier revisions remain readable in the journal history.
    Gifting transfers writing rights, while earlier writers retain attribution.
    """

    key = "+journal"
    switch_options = ("write", "title", "revise", "history")

    def run(self, switch):
        number = None
        name = self.lhs.strip()
        if switch not in self.switch_options:
            raise CraftingError(
                "Use +journal/write, /title, /revise or /history. See help +journal."
            )
        if switch == "history":
            if self.rhs is not None:
                raise CraftingError("Usage: +journal/history <journal>/<page>")
        # Colour markup and escaped literal pipes are authored text, not separators.
        elif self.rhs is None or "|" in strip_ansi(self.rhs.replace("||", "")):
            raise CraftingError(
                f"Usage: +journal/{switch} <journal>"
                + ("/<page>" if switch != "write" else "")
                + " = <text>"
            )
        if switch != "write":
            parts = name.split("/")
            if (
                len(parts) != 2
                or not parts[1].isascii()
                or not parts[1].isdecimal()
                or int(parts[1]) < 1
            ):
                raise CraftingError(
                    f"Usage: +journal/{switch} <journal>/<page>"
                    + (" = <text>" if switch != "history" else "")
                )
            name, number = parts[0].strip(), int(parts[1])
        item = find_item(self.caller, name)
        if item is None:
            return
        if switch == "history":
            self.msg(history(self.caller, item, number))
            return
        title = self.rhs.strip() if switch == "title" else "" if switch == "write" else None
        body = None if switch == "title" else self.rhs.strip()
        revision = write(self.caller, item, title, body, page=number)
        self.msg(
            f"Journal page {revision.page} saved (revision {revision.revision}); text by (OOC): {revision.author_name}."
        )
