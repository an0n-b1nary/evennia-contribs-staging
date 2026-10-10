# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Persistent, editable drafts keep composition separate from the final spend."""

from evennia import CmdSet
from evennia.commands.default.muxcommand import MuxCommand

from . import conf, services
from .behaviours import registry
from .catalog import seed_catalog
from .errors import CraftingError
from .models import CraftRecord, NicheDefinition, Workshop

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


class _CraftCommand(MuxCommand):
    locks = "cmd:all()"
    help_category = "Crafting"

    def access(self, srcobj, access_type="cmd", default=False, **kwargs):
        return super().access(srcobj, access_type, default, **kwargs) and conf.visible(srcobj)

    def func(self):
        if not conf.visible(self.caller):
            return
        try:
            if len(self.switches) > 1:
                raise CraftingError("Use one switch at a time.")
            self.run(self.switches[0] if self.switches else "")
        except (CraftingError, ValueError) as exc:
            self.msg(str(exc))


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
                # A stored niche may name a behaviour the host has since
                # unregistered; list it as unavailable rather than failing.
                available = [
                    key
                    for key in definition.behaviours
                    if key in implementations and implementations[key].available()
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
      +craft/beat = <EVENT prose>  (repeat for up to three beats)
      +craft/unbeat <number>
      +craft/reach = adjacent or channel
      +craft/channel = <staff-configured channel>
      +craft/resources = <resource key>:<quantity>[,...]
      +craft                   preview; consumes nothing
      +craft/finish            pay and create once; clears the draft on success
      +craft/cancel

    A new crafter works at full quality. No RP, XP or waiting is required.
    Requirements use equipment's vocabulary. An aura is a cosmetic worn line.
    """

    key = "+craft"

    def run(self, switch):
        if switch == "new":
            if self.rhs is None or "/" not in self.lhs:
                raise CraftingError("Usage: +craft/new niche/behaviour = item name")
            key, kind = (value.strip() for value in self.lhs.split("/", 1))
            definition = services.niche(key)
            from .behaviours import behaviour, text

            behaviour(kind)
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
            if switch == "finish":
                item = services.craft(
                    self.caller,
                    draft["niche"],
                    draft["behaviour"],
                    draft["name"],
                    draft["description"],
                    draft["configuration"],
                    draft["selected"],
                )
                self.caller.attributes.remove(DRAFT_KEY)
                self.msg(f"You craft {item.key}. {item.get_display_provenance(self.caller)}.")
                return
            if switch in (
                "desc",
                "line",
                "aura",
                "slot",
                "text",
                "require",
                "resources",
                "beat",
                "reach",
                "channel",
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
                    implementation = registry().get(draft["behaviour"])
                    if implementation is None:
                        raise CraftingError("That crafting behaviour is unavailable.")
                    if field not in implementation.fields:
                        raise CraftingError("That field isn't available for this behaviour.")
                    if field in ("requirements", "beats"):
                        values = list(draft["configuration"].get(field, []))
                        draft["configuration"][field] = [
                            *values,
                            text(value, field, 400 if field == "beats" else 200, required=True),
                        ]
                    else:
                        limit = (
                            12000
                            if field == "text"
                            else 30
                            if field in ("slot", "reach")
                            else 80
                            if field == "channel"
                            else 200
                        )
                        draft["configuration"][field] = text(value, field, limit)
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
                _, _, _, cost = services.craft_cost(
                    self.caller, draft["niche"], draft["behaviour"], draft["configuration"]
                )
                rows = [
                    f"Draft: {draft['name']} ({draft['niche']}/{draft['behaviour']})",
                    draft["description"],
                ]
                labels = {
                    "worn_line": "Worn line",
                    "aura_line": "Aura",
                    "slot": "Slot",
                    "text": "Text",
                    "reach": "Reach",
                    "channel": "Channel",
                }
                for field, label in labels.items():
                    if draft["configuration"].get(field):
                        rows.append(f"{label}: {draft['configuration'][field]}")
                for number, rule in enumerate(draft["configuration"].get("requirements", []), 1):
                    rows.append(f"Requirement {number}: {rule}")
                for number, beat in enumerate(draft["configuration"].get("beats", []), 1):
                    rows.append(f"EVENT beat {number}: {beat}")
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

    Usage: read <item>
    """

    key = "read"
    aliases = ["+read"]  # noqa: RUF012

    def run(self, switch):
        if switch or not self.args.strip():
            raise CraftingError("Usage: read <item>")
        candidates = list(self.caller.contents)
        if self.caller.location:
            candidates += list(self.caller.location.contents)
        item = self.caller.search(self.args.strip(), candidates=candidates)
        if item is None:
            return
        from .typeclasses import Readable

        if not isinstance(item, Readable):
            raise CraftingError("There is nothing written here.")
        self.msg(f"{item.key}\n{item.read(self.caller)}")


class CmdUse(_CraftCommand):
    """Use a carried crafted Consumable or Broadcast once.

    Usage: use <item>

    Emits its authored EVENT beats together, then consumes the item. Room
    rate limits survive reloads. Remote Broadcast effects respect +ambient.
    """

    key = "use"
    aliases = ["+use"]  # noqa: RUF012

    def run(self, switch):
        if switch or not self.args.strip():
            raise CraftingError("Usage: use <item>")
        item = self.caller.search(self.args.strip(), candidates=list(self.caller.contents))
        if item is None:
            return
        from .events import use

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
                    f"Craft #{row.pk}: {row.hallmark}, item #{row.item_id}, {row.created.isoformat()}\nMaker: {row.crafter_name} (#{row.crafter_id}), accounts {row.crafter_accounts}\nNiche: {row.niche_name} ({row.niche.key}), behaviour {row.behaviour}\nSpent: {dict(row.resources_spent)}, money {row.money_spent}\n{dict(row.prose)}"
                )
                from .models import EventUse

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
                        f"#{row.pk} {row.prose['name']} — {row.hallmark}, {row.behaviour}, item #{row.item_id}"
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
