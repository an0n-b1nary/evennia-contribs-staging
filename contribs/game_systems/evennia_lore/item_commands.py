# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Draft lore facets and staff books; neither command edits finished crafts."""

from django.apps import apps
from evennia.commands.default.muxcommand import MuxCommand
from evennia.utils.dbserialize import deserialize

from evennia_links.pagination import reading_target

from .command_syntax import SingleSwitchMixin
from .items import LoreItemError, create_tome, staff, validate_citations, validate_pages

TOME_DRAFT = "lore_tome_draft"


def entry_id(actor, value):
    from .commands import _resolve_entry

    entry, error = _resolve_entry(value, actor, require_published=True)
    if error:
        raise LoreItemError(error)
    return entry.pk


class ItemCommand(SingleSwitchMixin, MuxCommand):
    locks = "cmd:all()"
    help_category = "Lore"

    def func(self):
        try:
            self.run(self.switches[0] if self.switches else "")
        except ValueError as exc:
            self.msg(str(exc))


class CmdReadTome(ItemCommand):
    """Read a staff tome or visible craft; lore is independent of crafting reveal.

    Usage:
      read <item>[=<page>]
      read/contents <item>
    """

    key = "read"
    aliases = ["+read"]  # noqa: RUF012
    switch_options = ("contents",)

    def run(self, switch):
        if switch not in ("", "contents") or not self.args.strip():
            raise LoreItemError("Usage: read <item>[=<page>], or read/contents <item>")
        item, number = reading_target(
            self.caller, self.lhs, self.rhs, table=switch == "contents", positional_page=False
        )
        if item is None:
            return
        reader = getattr(item, "read", None)
        if apps.is_installed("evennia_rp_crafting"):
            from evennia_rp_crafting import conf
            from evennia_rp_crafting.models import CraftRecord

            if CraftRecord.objects.filter(item_id=item.pk).exists():
                if not conf.visible(self.caller):
                    raise LoreItemError("Crafting is unavailable.")
                if not callable(reader):
                    from evennia_rp_crafting.pages import read

                    def reader(actor, number, *, contents=False):
                        return read(actor, item, number, table=contents)

        if not callable(reader):
            raise LoreItemError("There is nothing written here.")
        self.msg(f"{item.key}\n{reader(self.caller, number, contents=switch == 'contents')}")


class CmdLoreCraft(ItemCommand):
    """Attach lore to a complete crafting draft before paying for it.

    Usage:
      +lorecraft/cite [page] = #entry
      +lorecraft/recognise #entry[/<niche>]=<feature text>
      +lorecraft/uncite <number>
      +lorecraft/unrecognise <number>
      +lorecraft

    Hold the lore in your compendium. Restricted entries are permitted.
    Recognition costs one additional input per feature; citations are free.
    Finish through +craft/finish. Completed item prose remains immutable.
    """

    key = "+lorecraft"
    switch_options = ("cite", "recognise", "uncite", "unrecognise")

    def access(self, srcobj, access_type="cmd", default=False, **kwargs):
        from .integrations.crafting import supported

        if not supported():
            return False
        from evennia_rp_crafting import conf

        return conf.visible(srcobj) and super().access(srcobj, access_type, default, **kwargs)

    def run(self, switch):
        from .integrations.crafting import supported

        if not supported():
            raise LoreItemError("Compatible crafting is not installed.")
        from evennia_rp_crafting import conf, services
        from evennia_rp_crafting.commands import DRAFT_KEY

        if not conf.visible(self.caller):
            raise LoreItemError("Crafting is unavailable.")
        stored = self.caller.attributes.get(DRAFT_KEY)
        if not stored or "copy_source" in stored:
            raise LoreItemError("Start an authored draft with +craft/new first.")
        draft = deserialize(stored)
        facets = draft.setdefault("facets", {})
        key = "lore_recognition" if switch in ("recognise", "unrecognise") else "lore_citations"
        rows = list(facets.get(key, []))
        if switch == "cite":
            if self.rhs is None:
                raise LoreItemError("Usage: +lorecraft/cite [page] = #entry")
            rows.append(
                {
                    "entry": entry_id(self.caller, self.rhs),
                    "page": int(self.lhs) if self.lhs.strip() else None,
                }
            )
        elif switch == "recognise":
            reference, slash, niche = self.lhs.strip().partition("/")
            if (
                not reference.startswith("#")
                or not reference[1:].isascii()
                or not reference[1:].isdigit()
                or self.rhs is None
                or not self.rhs.strip()
                or (slash and (not niche.strip() or "/" in niche))
            ):
                raise LoreItemError("Usage: +lorecraft/recognise #entry[/<niche>]=<feature text>")
            row = {"entry": entry_id(self.caller, reference), "text": self.rhs.strip()}
            if slash:
                row["niche"] = niche.strip()
            rows.append(row)
        elif switch in ("uncite", "unrecognise"):
            number = int(self.args.strip())
            if not 1 <= number <= len(rows):
                raise LoreItemError("No such draft feature.")
            rows.pop(number - 1)
        elif switch:
            raise LoreItemError("Use +lorecraft, /cite, /recognise, /uncite or /unrecognise.")
        else:
            self.msg(
                f"Draft lore facets: {facets or 'none'}. Use +craft to review the combined cost."
            )
            return
        if rows:
            facets[key] = rows
        else:
            facets.pop(key, None)
        # Removal must remain possible while other facets or draft pages are
        # invalid. Additions, previews and completion still validate the whole.
        if switch in ("cite", "recognise"):
            services.craft_cost(
                self.caller,
                draft["niche"],
                draft["behaviour"],
                draft["configuration"],
                verbs=draft.get("verbs"),
                facets=facets,
            )
        self.caller.attributes.add(DRAFT_KEY, draft)
        self.msg("Draft lore facets saved. Use +craft to preview, then /finish.")


class CmdTome(ItemCommand):
    """Publish a fixed staff-authored lore tome, without a crafting Workshop.

    Usage:
      +tome/new <name>
      +tome/desc = <description>
      +tome/page [title] = <text>  (repeat for additional pages)
      +tome/cite [page] = #entry
      +tome
      +tome/publish
      +tome/cancel
    """

    key = "+tome"
    switch_options = ("new", "desc", "page", "cite", "publish", "cancel")

    def access(self, srcobj, access_type="cmd", default=False, **kwargs):
        return staff(srcobj) and super().access(srcobj, access_type, default, **kwargs)

    def run(self, switch):
        if not staff(self.caller):
            raise LoreItemError("Staff only.")
        if switch == "new":
            name = self.args.strip()
            if not 1 <= len(name) <= 80:
                raise LoreItemError("Choose a tome name of 1-80 characters.")
            draft = {"name": name, "description": "", "pages": [], "citations": []}
        elif switch == "cancel":
            self.caller.attributes.remove(TOME_DRAFT)
            self.msg("Tome draft discarded.")
            return
        else:
            stored = self.caller.attributes.get(TOME_DRAFT)
            if not stored:
                raise LoreItemError("Start a draft with +tome/new <name>.")
            draft = deserialize(stored)
            if switch == "desc":
                draft["description"] = (
                    self.rhs if self.rhs is not None else self.args.lstrip("= ")
                ).strip()
            elif switch == "page":
                if self.rhs is None:
                    raise LoreItemError("Usage: +tome/page [title] = page text")
                draft["pages"] = validate_pages(
                    [*draft["pages"], {"title": self.lhs.strip(), "text": self.rhs}]
                )
            elif switch == "cite":
                if self.rhs is None:
                    raise LoreItemError("Usage: +tome/cite [page] = #entry")
                row = {
                    "entry": entry_id(self.caller, self.rhs),
                    "page": int(self.lhs) if self.lhs.strip() else None,
                }
                draft["citations"] = validate_citations(
                    self.caller, [*draft["citations"], row], len(draft["pages"])
                )
            elif switch == "publish":
                item = create_tome(
                    self.caller,
                    draft["name"],
                    draft["description"],
                    draft["pages"],
                    draft["citations"],
                )
                self.caller.attributes.remove(TOME_DRAFT)
                self.msg(f"Published {item.key}.")
                return
            elif switch:
                raise LoreItemError("Use +tome/new, /desc, /page, /cite, /publish or /cancel.")
            else:
                self.msg(
                    f"Tome draft: {draft['name']}\n{draft['description']}\nPages: {draft['pages']}\nCitations: {draft['citations']}"
                )
                return
        self.caller.attributes.add(TOME_DRAFT, draft)
        self.msg(f"Tome draft saved: {draft['name']}.")
