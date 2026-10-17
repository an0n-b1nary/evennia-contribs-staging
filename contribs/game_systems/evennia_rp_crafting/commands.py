# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Persistent, editable drafts keep composition separate from the final spend."""

from evennia import CmdSet

from . import conf, services
from .behaviours import registry
from .catalog import seed_catalog
from .command_base import CraftCommand as _CraftCommand
from .composition import specifications
from .detail_commands import CmdLook as CmdLook
from .errors import CraftingError
from .models import CraftRecord, NicheDefinition, Workshop
from .readable_commands import CmdJournal as CmdJournal
from .room_commands import CmdFixture as CmdFixture
from .room_commands import CmdListen as CmdListen
from .room_commands import CmdSense as CmdSense
from .room_commands import CmdTouch as CmdTouch
from .wave_three_commands import CmdModify as CmdModify
from .wave_three_commands import CmdPet as CmdPet

DRAFT_KEY = "rp_crafting_draft"


def resource_spec(value):
    result = {}
    try:
        for part in value.split(","):
            key, amount = part.strip().rsplit(":", 1)
            key, amount = key.strip(), int(amount)
            if not key or not conf.positive(amount) or key in result:
                raise ValueError
            result[key] = amount
    except ValueError:
        raise CraftingError(
            "Select resources as key:quantity, key:quantity, without repeats."
        ) from None
    return result


def costs_text(cost):
    parts = [f"{quantity} {key}" for key, quantity in cost["resources"].items()]
    if cost["money"]:
        from evennia_economy.conf import currency

        parts.append(currency(cost["money"]))
    return ", ".join(parts)


class CmdWorkshop(_CraftCommand):
    """Your invested niches and the next unlock's cost.

    Usage:
      +workshop
      +workshop/catalog
      +workshop/unlock <niche key> = <resource key>:<quantity>[,...]
      +workshop/abandon <niche key>

    Unlock costs escalate with the number of active niches. Abandoning frees
    a slot and lowers your passive-income caps, without refunding investment.
    """

    key = "+workshop"

    def run(self, switch):
        workshop = Workshop.objects.filter(character=self.caller).first()
        held = list(services.active_unlocks(workshop).select_related("niche")) if workshop else []
        if switch == "catalog":
            rows = [f"Niches — next unlock position {len(held) + 1}:"]
            implementations = registry()
            for definition in NicheDefinition.objects.filter(archived=False):
                if not any(
                    conf.component_visible(self.caller, key) for key in definition.behaviours
                ):
                    continue
                # A stored niche may name a behaviour the host has since
                # unregistered; list it as unavailable rather than failing.
                available = [
                    key
                    for key in definition.behaviours
                    if key in implementations
                    and implementations[key].available()
                    and conf.component_visible(self.caller, key)
                ]
                try:
                    cost = costs_text(services.unlock_cost(definition, len(held)))
                except (CraftingError, ValueError):
                    cost = "unavailable"
                rows.append(
                    f"{definition.key}: {definition.name} [{', '.join(available) or 'unavailable'}] — {cost}\n  {definition.description}"
                )
            self.msg("\n".join(rows))
        elif switch == "unlock":
            if self.rhs is None:
                raise CraftingError("Usage: +workshop/unlock niche = resource:quantity")
            result = services.unlock(self.caller, self.lhs.strip(), resource_spec(self.rhs))
            self.msg(f"Unlocked {result.niche.name} in your Workshop.")
        elif switch == "abandon":
            result = services.abandon(self.caller, self.args.strip())
            self.msg(f"Abandoned {result.niche.name}; investment is not refunded.")
        elif switch:
            raise CraftingError("Use +workshop, /catalog, /unlock or /abandon.")
        else:
            from evennia_links.runtime import get

            from .contributions import caps

            raises = caps(None, self.caller)["workshops"]
            rows = [f"Your Workshop: {len(held)}/{get('RP_CRAFTING_NICHE_CAP')} active niches."]
            rows += [
                f"  {row.niche.name} ({row.niche.key}){' [archived]' if row.niche.archived else ''}"
                for row in held
            ]
            rows.append(f"Cap raises: money +{raises['money']}, resources +{raises['resources']}.")
            if workshop:
                investments = (
                    ", ".join(
                        f"{row.quantity} {row.resource_key}" for row in workshop.investments.all()
                    )
                    or "none"
                )
                rows.append(
                    f"Built from: {investments}. Money invested: {workshop.invested_money}."
                )
            self.msg("\n".join(rows))


class CmdCraft(_CraftCommand):
    """Compose an item in a persistent draft, preview its costs, then craft it.

    Usage:
      +craft/new <niche key>/<behaviour key> = <item name>
      +craft/desc = <description>
      +craft/line = <worn line>
      +craft/aura = <optional aura line>
      +craft/slot = <flavour slot>
      +craft/require = <equipment requirement>  (repeat for several)
      +craft/unrequire <number>
      +craft/text = <readable text>
      +craft/journal = <blank page capacity>
      +craft/detail <name> = <exterior detail prose>
      +craft/undetail <name>
      +craft/sense <smell|sound|touch> = <item sensory prose>
      +craft/unsense <smell|sound|touch>
      +craft/copy <source item> = <niche key>/<new item name>
      +craft/page [title] = <page text>  (repeat to append authored pages)
      +craft/unpage <number>
      +craft/verb <niche key>/<verb key>  (only an allowed combination)
      +craft/unverb <verb key>
      +craft/beat = <EVENT prose>  (repeat for up to three beats)
      +craft/unbeat <number>
      +craft/reach = adjacent  (Broadcast; the default)
      +craft/mode <mode key> = <reading>  (repeat for random readings)
      +craft/unmode <mode key>
      +craft/room_line = <room description layer>
      +craft/smell = <sensory line>
      +craft/sound = <sensory line>
      +craft/ambient = <periodic EVENT prose>
      +craft/arrival = <Companion arrival prose>
      +craft/resources = <resource key>:<quantity>[,...]
      +craft                   preview; consumes nothing
      +craft/finish            pay and create once; clears the draft on success
      +craft/cancel

    A new crafter works at full quality. No RP, XP or waiting is required.
    Requirements use equipment's vocabulary. An aura is a cosmetic worn line.
    """

    key = "+craft"

    def run(self, switch):
        if switch == "copy":
            from .readable_commands import copy_draft

            copy_draft(self)
            return
        if switch == "new":
            if self.rhs is None or "/" not in self.lhs:
                raise CraftingError("Usage: +craft/new niche/behaviour = item name")
            key, kind = (value.strip() for value in self.lhs.split("/", 1))
            definition = services.niche(key)
            from .behaviours import behaviour, text

            behaviour(kind)
            if not conf.component_visible(self.caller, kind):
                raise CraftingError("That crafting behaviour is unavailable.")
            if kind not in definition.behaviours:
                raise CraftingError("That niche doesn't grant this behaviour.")
            name = text(self.rhs, "Item name", 80, required=True)
            draft = {
                "niche": key,
                "behaviour": kind,
                "name": name,
                "description": "",
                "configuration": {},
                "selected": {},
            }
        elif switch == "cancel":
            self.caller.attributes.remove(DRAFT_KEY)
            self.msg("Craft draft discarded.")
            return
        else:
            stored = self.caller.attributes.get(DRAFT_KEY)
            if not stored:
                raise CraftingError("Start a draft with +craft/new niche/behaviour = name.")
            from evennia.utils.dbserialize import deserialize

            draft = deserialize(stored)
            if "copy_source" in draft:
                from .readable_commands import continue_copy

                continue_copy(self, switch, draft)
                return
            if switch == "finish":
                item = services.craft(
                    self.caller,
                    draft["niche"],
                    draft["behaviour"],
                    draft["name"],
                    draft["description"],
                    draft["configuration"],
                    draft["selected"],
                    verbs=draft.get("verbs"),
                    facets=draft.get("facets"),
                )
                self.caller.attributes.remove(DRAFT_KEY)
                self.msg(
                    f"You craft {item.key}. Hallmark (OOC): {item.get_display_provenance(self.caller)}."
                )
                return
            if switch in ("detail", "undetail", "sense", "unsense"):
                from .item_details import edit_draft

                edit_draft(self, switch, draft)
            elif switch == "journal":
                from .pages import validate

                entry = next(
                    (entry for entry in draft.get("verbs", []) if entry["key"] == "readable"), None
                )
                implementation = registry().get(entry["key"] if entry else draft["behaviour"])
                if implementation is None or "journal" not in implementation.fields:
                    raise CraftingError("Add a Readable verb first.")
                value = self.rhs if self.rhs is not None else self.args.lstrip("= ")
                normalized = validate({"journal": int(value)})
                target = entry["configuration"] if entry else draft["configuration"]
                target.clear()
                target.update(normalized)
            elif switch in ("page", "unpage"):
                from .pages import authored_pages, validate

                entry = next(
                    (entry for entry in draft.get("verbs", []) if entry["key"] == "readable"),
                    None,
                )
                implementation = registry().get(entry["key"] if entry else draft["behaviour"])
                if implementation is None or "pages" not in implementation.fields:
                    raise CraftingError("Add a Readable verb first.")
                target = entry["configuration"] if entry else draft["configuration"]
                pages = (
                    [{"title": page.title, "text": page.text} for page in authored_pages(target)]
                    if target
                    else []
                )
                if switch == "page":
                    if self.rhs is None:
                        raise CraftingError("Usage: +craft/page [title] = page text")
                    pages.append({"title": self.lhs.strip(), "text": self.rhs})
                else:
                    number = int(self.args.strip())
                    if not 1 <= number <= len(pages):
                        raise CraftingError("No such draft page.")
                    pages.pop(number - 1)
                normalized = validate({"pages": pages}) if pages else {}
                target.clear()
                target.update(normalized)
            elif switch == "verb":
                if "/" not in self.args:
                    raise CraftingError("Usage: +craft/verb niche/verb")
                key, kind = (value.strip() for value in self.args.split("/", 1))
                definition = services.niche(key)
                implementation = registry().get(kind)
                if not conf.component_visible(self.caller, kind):
                    raise CraftingError("That crafting behaviour is unavailable.")
                if implementation is None or not implementation.available():
                    raise CraftingError("That crafting behaviour is unavailable.")
                if kind not in definition.behaviours:
                    raise CraftingError("That niche doesn't grant this behaviour.")
                verbs = [*draft.get("verbs", []), {"key": kind, "niche": key, "configuration": {}}]
                specifications(
                    draft["niche"], draft["behaviour"], draft["configuration"], verbs, partial=True
                )
                draft["verbs"] = verbs
            elif switch == "unverb":
                kind = self.args.strip()
                entries = draft.get("verbs", [])
                if not any(entry["key"] == kind for entry in entries):
                    raise CraftingError("No such draft verb.")
                draft["verbs"] = [entry for entry in entries if entry["key"] != kind]
            elif switch in ("mode", "unmode"):
                entry = next(
                    (entry for entry in draft.get("verbs", []) if entry["key"] == "activatable"),
                    None,
                )
                target = entry["configuration"] if entry else draft["configuration"]
                implementation = registry().get(entry["key"] if entry else draft["behaviour"])
                if implementation is None or "modes" not in implementation.fields:
                    raise CraftingError("Add an Activatable verb first.")
                modes = dict(target.get("modes", {}))
                key = self.lhs.strip()
                if switch == "unmode":
                    if key not in modes:
                        raise CraftingError("No such draft mode.")
                    del modes[key]
                else:
                    from .wave_two import line

                    if self.rhs is None:
                        raise CraftingError("Usage: +craft/mode mode = reading")
                    modes[key] = [*modes.get(key, []), line(self.rhs)]
                    implementation.validate({"modes": modes})
                target["modes"] = modes
            elif switch in (
                "desc",
                "line",
                "aura",
                "slot",
                "text",
                "require",
                "resources",
                "beat",
                "reach",
                "room_line",
                "smell",
                "sound",
                "ambient",
                "arrival",
            ):
                value = self.rhs if self.rhs is not None else self.args.lstrip("= ")
                from .behaviours import text

                value = text(value, "Draft field", 12000)
                if switch == "desc":
                    draft["description"] = text(value, "Description", 4000)
                elif switch == "resources":
                    draft["selected"] = resource_spec(value)
                else:
                    field = {
                        "line": "worn_line",
                        "aura": "aura_line",
                        "require": "requirements",
                        "beat": "beats",
                    }.get(switch, switch)
                    verb_entry = next(
                        (
                            entry
                            for entry in draft.get("verbs", [])
                            if entry["key"] == "readable" and field == "text"
                        ),
                        None,
                    )
                    implementation = registry().get(
                        verb_entry["key"] if verb_entry else draft["behaviour"]
                    )
                    if implementation is None:
                        raise CraftingError("That crafting behaviour is unavailable.")
                    if field not in implementation.fields:
                        raise CraftingError("That field isn't available for this behaviour.")
                    if field in ("requirements", "beats"):
                        values = list(draft["configuration"].get(field, []))
                        label, limit = (
                            ("EVENT beat", 400) if field == "beats" else ("Requirement", 200)
                        )
                        draft["configuration"][field] = [
                            *values,
                            text(value, label, limit, required=True),
                        ]
                    else:
                        limit = (
                            12000
                            if field == "text"
                            else 30
                            if field in ("slot", "reach")
                            else 400
                            if field in ("room_line", "smell", "sound", "ambient", "arrival")
                            else 200
                        )
                        target = (
                            verb_entry["configuration"] if verb_entry else draft["configuration"]
                        )
                        if field == "text":
                            from .pages import validate

                            target.clear()
                            target.update(validate({"text": text(value, field, limit)}))
                        else:
                            target[field] = text(value, field, limit)
            elif switch in ("unrequire", "unbeat"):
                field = "beats" if switch == "unbeat" else "requirements"
                values = list(draft["configuration"].get(field, []))
                number = int(self.args.strip())
                if not 1 <= number <= len(values):
                    raise CraftingError("No such draft entry.")
                values.pop(number - 1)
                draft["configuration"][field] = values
            elif switch:
                raise CraftingError("Unknown craft switch. See help +craft.")
            else:
                _, composition, _, cost = services.craft_cost(
                    self.caller,
                    draft["niche"],
                    draft["behaviour"],
                    draft["configuration"],
                    verbs=draft.get("verbs"),
                    facets=draft.get("facets"),
                )
                rows = [
                    f"Draft: {draft['name']} ({draft['niche']}/{draft['behaviour']})",
                    draft["description"],
                    f"Lifecycle: {composition.lifecycle_key}; verbs: {', '.join(entry['key'] for entry in composition.verbs) or 'none'}.",
                    f"Contributing niches: {', '.join(row['name'] for row in composition.contributors)}.",
                ]
                labels = {
                    "worn_line": "Worn line",
                    "aura_line": "Aura",
                    "slot": "Slot",
                    "text": "Text",
                    "reach": "Reach",
                    "room_line": "Room layer",
                    "smell": "Smell",
                    "sound": "Sound",
                    "ambient": "Ambient",
                    "arrival": "Arrival",
                    "modes": "Modes",
                }
                for field, label in labels.items():
                    if draft["configuration"].get(field):
                        rows.append(f"{label}: {draft['configuration'][field]}")
                from .pages import authored_pages

                for config in [
                    draft["configuration"],
                    *(entry["configuration"] for entry in draft.get("verbs", [])),
                ]:
                    if config.get("pages"):
                        rows.append("Pages:")
                        for number, page in enumerate(authored_pages(config), 1):
                            rows.append(f"{number}. {page.title or f'Page {number}'}\n{page.text}")
                    if config.get("journal"):
                        rows.append(
                            f"Blank journal: {config['journal']} pages; owner writing is free."
                        )
                for entry in draft.get("verbs", []):
                    rows.append(f"{entry['key']} ({entry['niche']})")
                    for field, label in labels.items():
                        if entry["configuration"].get(field):
                            rows.append(f"{label}: {entry['configuration'][field]}")
                for number, rule in enumerate(draft["configuration"].get("requirements", []), 1):
                    rows.append(f"Requirement {number}: {rule}")
                for number, beat in enumerate(draft["configuration"].get("beats", []), 1):
                    rows.append(f"EVENT beat {number}: {beat}")
                remaining_facets = dict(composition.facets)
                for key, label in (("details", "Detail"), ("senses", "Item sense")):
                    for name, value in remaining_facets.pop(key, {}).items():
                        rows.append(f"{label} {name}: {value}")
                if remaining_facets:
                    rows.append(f"Facets: {remaining_facets}")
                selected = (
                    ", ".join(f"{amount} {key}" for key, amount in draft["selected"].items())
                    or "none"
                )
                rows.extend(
                    [
                        f"Cost: {costs_text(cost)}. Selected: {selected}.",
                        "+craft/finish pays and creates the item.",
                    ]
                )
                self.msg("\n".join(rows))
                return
        self.caller.attributes.add(DRAFT_KEY, draft)
        self.msg(f"Craft draft saved: {draft['name']}.")


class CmdRead(_CraftCommand):
    """Read the text held in a crafted item you carry or can see here.

    Usage:
      read <item> [page number]
      read <item> = <page number>
      read/contents <item>

    Without a page number, resume your last read page. Explicit page breaks
    stay the same on every client. Contents does not move your bookmark.
    """

    key = "read"
    aliases = ["+read"]  # noqa: RUF012

    def run(self, switch):
        if switch not in ("", "contents") or not self.args.strip():
            raise CraftingError("Usage: read <item> [= page number], or read/contents <item>")
        from evennia_links.pagination import reading_target

        item, number = reading_target(self.caller, self.lhs, self.rhs, table=switch == "contents")
        if item is None:
            return
        from .pages import read

        reader = getattr(item, "read", None)
        result = (
            reader(self.caller, number, contents=switch == "contents")
            if callable(reader)
            else read(self.caller, item, number, table=switch == "contents")
        )
        self.msg(f"{item.key}\n{result}")


class CmdUse(_CraftCommand):
    """Use a crafted Consumable/Broadcast, or play a reusable activation mode.

    Usage: use <item> [= mode]

    Consumables/Broadcasts emit their beats then disappear. Activatables keep
    the item and allow a named mode. Item/room limits survive reloads; ambient
    effects respect +ambient.
    """

    key = "use"
    aliases = ["+use"]  # noqa: RUF012

    def run(self, switch):
        if switch or not self.args.strip():
            raise CraftingError("Usage: use <item>")
        candidates = list(self.caller.contents) + list(
            self.caller.location.contents if self.caller.location else []
        )
        item = self.caller.search(self.lhs.strip(), candidates=candidates)
        if item is None:
            return
        from .events import use

        record = item.craft_record if hasattr(item, "craft_record") else None
        if record and "activatable" in record.behaviour_keys:
            from .wave_two import activate

            result = activate(self.caller, item, self.rhs.strip() if self.rhs else None)
        else:
            if self.rhs:
                raise CraftingError("This item has no activation modes.")
            result = use(self.caller, item)
        self.msg(f"You use {result.craft.prose['name']}.")


class CmdCrafting(_CraftCommand):
    """Staff catalogue maintenance and immutable craft snapshots.

    Usage:
      +crafting/seed
      +crafting/archive <niche key>
      +crafting/restore <niche key>
      +crafting/review [record number]
    """

    key = "+crafting"

    def access(self, srcobj, access_type="cmd", default=False, **kwargs):
        return super().access(srcobj, access_type, default, **kwargs) and conf.is_staff(srcobj)

    def run(self, switch):
        if not conf.is_staff(self.caller):
            raise CraftingError("Staff only.")
        if switch == "seed":
            self.msg(f"Seeded {len(seed_catalog(update=True))} niche definitions.")
        elif switch in ("archive", "restore"):
            definition = NicheDefinition.objects.filter(key=self.args.strip()).first()
            if definition is None:
                raise CraftingError("Unknown niche.")
            definition.archived = switch == "archive"
            definition.save(update_fields=["archived"])
            self.msg(f"{definition.name}: {'archived' if definition.archived else 'active'}.")
        elif switch == "review":
            if self.args.strip():
                row = CraftRecord.objects.filter(pk=int(self.args)).first()
                if row is None:
                    raise CraftingError("Unknown craft record.")
                self.msg(
                    f"Craft #{row.pk}: {row.hallmark}, item #{row.item_id}, {row.created.isoformat()}\nMaker: {row.crafter_name} (#{row.crafter_id}), accounts {row.crafter_accounts}\nContributors: {row.contributor_data}\nLifecycle: {row.lifecycle}; verbs: {row.verb_data}\nSpent: {dict(row.resources_spent)}, money {row.money_spent}\n{dict(row.prose)}"
                )
                from .models import EventUse, JournalRevision, ReadableEdition

                edition = ReadableEdition.objects.filter(craft=row).first()
                if edition:
                    self.msg(
                        f"Edition of craft #{edition.source_id}; page authors: {edition.authors}; source fingerprint {edition.source_fingerprint}."
                    )
                revisions = JournalRevision.objects.filter(craft=row)
                if revisions.exists():
                    self.msg(
                        "Journal revisions (OOC):\n"
                        + "\n".join(
                            f"Page {revision.page}, revision {revision.revision}, {revision.author_name} (#{revision.author_id}) at {revision.created.isoformat()}: {revision.title}\n{revision.text}"
                            for revision in revisions
                        )
                    )

                used = EventUse.objects.filter(craft=row).first()
                if used:
                    self.msg(
                        f"Used by {used.actor_name} (#{used.actor_id}) in room #{used.room_id} at {used.created.isoformat()}; destinations: {used.destinations}."
                    )
            else:
                rows = CraftRecord.objects.order_by("-pk")[:30]
                self.msg(
                    "Recent crafts:\n"
                    + "\n".join(
                        f"#{row.pk} {row.prose['name']} — {row.hallmark}, {', '.join(row.behaviour_keys)}, item #{row.item_id}"
                        for row in rows
                    )
                )
        else:
            raise CraftingError("Use +crafting/seed, /archive, /restore or /review.")


class CraftingCmdSet(CmdSet):
    key = "rp_crafting"

    def at_cmdset_creation(self):
        for command in (CmdWorkshop, CmdCraft, CmdRead, CmdUse, CmdCrafting):
            self.add(command())
        for command in (CmdFixture, CmdListen, CmdSense, CmdTouch, CmdLook):
            self.add(command())
        self.add(CmdModify())
        self.add(CmdPet())
        self.add(CmdJournal())
