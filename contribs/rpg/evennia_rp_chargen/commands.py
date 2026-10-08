# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Commands for evennia_rp_chargen.

    +sheet      view your sheet (staff: anyone's)
    +stats      choose your stats' rungs on a draft sheet, then finalize it
    +pips       manage edge and weakness pips (games often subclass it as +edge)
    +lock       lock your edge and loadout (announced)
    +unlock     unlock them (announced)
    +abilities  your abilities and flaws, the catalog, equipping, flaws
    +spend      what you have to spend; +spend/ability buys an ability
    +upgrade    raise an ability a level
    +chargen    staff: review sheets, set stats, grant and revoke, add tags

Add `ChargenCmdSet` to the character cmdset, or pick the commands you want.
Rename a command by subclassing it (`class CmdEdge(CmdPips): key = "+edge"`).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.utils.text import slugify
from evennia import CmdSet
from evennia.commands.default.muxcommand import MuxCommand
from evennia.utils.utils import inherits_from

from evennia_rp_chargen import abilities, conf, locks, services
from evennia_rp_chargen.catalog import split_ability_text
from evennia_rp_chargen.models import AbilityDefinition, CharacterBuild, TagDefinition
from evennia_rp_chargen.services import ChargenError
from evennia_rp_chargen.sheet import ability_lines, render_sheet, stat_lines


def is_staff(caller) -> bool:
    return caller.locks.check_lockstring(caller, conf.staff_lock())


def _count(text: str, glyph: str) -> int | None:
    """`"3"` or `"+++"` (with `glyph` "+") as a count; None if neither."""
    text = text.strip()
    if text.isdigit():
        return int(text)
    if text and set(text) == {glyph}:
        return len(text)
    return None


class _ChargenCommand(MuxCommand):
    help_category = "Character"
    locks = "cmd:all()"

    def run(self, action, *args, **kwargs):
        """Call a service, turning `ChargenError` into a message. Returns None on error."""
        try:
            return action(*args, **kwargs)
        except ChargenError as exc:
            self.msg(f"|r{exc}|n")
            return None

    def find_character(self, name: str):
        target = self.caller.search(name.strip(), global_search=True)
        if target is None:
            return None
        if not inherits_from(target, settings.BASE_CHARACTER_TYPECLASS):
            self.msg(f"{target.key} isn't a character.")
            return None
        return target


class CmdSheet(_ChargenCommand):
    """
    View your character sheet.

    Usage:
      +sheet
      +sheet <character>     (staff only)

    Your sheet shows every stat with its edge (+) and weakness (-) pips.
    Nobody but you and staff can see it.
    """

    key = "+sheet"
    aliases = ["sheet"]  # noqa: RUF012

    def func(self):
        caller = self.caller
        if not self.args.strip():
            self.msg(render_sheet(caller, staff=is_staff(caller)))
            return
        if not is_staff(caller):
            self.msg("You can only see your own sheet.")
            return
        target = self.find_character(self.args)
        if target is not None:
            self.msg(render_sheet(target, staff=True))


class CmdStats(_ChargenCommand):
    """
    Choose your stats while your sheet is a draft.

    Usage:
      +stats
      +stats <stat>=<rung>
      +stats/clear <stat>
      +stats/finalize

    Pick each stat's rung (for example: +stats charisma=B), within your
    allocation. Edge and weakness are set separately with +pips.
    Finalizing locks the rungs in; after that only staff can change them.
    """

    key = "+stats"
    switch_options = ("clear", "finalize")

    def func(self):
        caller = self.caller
        if "finalize" in self.switches:
            build = self.run(services.finalize, caller)
            if build is None:
                return
            if conf.require_approval():
                self.msg("Sheet finalized and sent to staff for approval.")
            else:
                self.msg("Sheet finalized. You're ready to play.")
            return
        if "clear" in self.switches:
            if not self.args.strip():
                self.msg("Usage: +stats/clear <stat>")
                return
            report = self.run(services.clear_stat, caller, self.args.strip())
            if report is not None:
                self.msg(f"Cleared. {report.summary}".strip())
            return
        if not self.rhs:
            if self.args.strip():
                self.msg("Usage: +stats <stat>=<rung>")
                return
            services.ensure_build(caller)
            report = services.allocation_report(caller)
            lines = stat_lines(caller)
            if report.summary:
                lines.append(f" {report.summary}.")
            self.msg("\n".join(lines))
            return
        result = self.run(services.set_stat, caller, self.lhs, self.rhs)
        if result is not None:
            rating, report = result
            stat = services.find_stat(self.lhs)
            suffix = f" ({report.summary})" if report.summary else ""
            self.msg(f"{stat.name} is now {rating.display()}.{suffix}")


class CmdPips(_ChargenCommand):
    """
    Manage edge and weakness pips.

    Usage:
      +pips
      +pips <stat>=<count>
      +pips/set <stat>=<count>
      +pips/clear [<stat>]
      +pips/weakness <stat>=<count>

    Edge (+) nudges a stat up and comes from a limited budget. Weakness (-)
    nudges it down; it's free, a roleplaying choice. A count can be a number
    or the pips themselves: +pips charisma=+++ or +pips/weakness will=--.
    While you're in a scene your edge is locked; +unlock first.
    """

    key = "+pips"
    switch_options = ("set", "clear", "weakness")

    def func(self):
        caller = self.caller
        if "clear" in self.switches:
            changed = self.run(services.clear_edge, caller, self.args.strip() or None)
            if changed is not None:
                self.msg(f"Cleared {conf.get('RP_CHARGEN_PIP_NOUN')} from {len(changed)} stat(s).")
            return
        if not self.rhs:
            if self.args.strip() or self.switches:
                self.msg("Usage: +pips <stat>=<count>, or +pips/weakness <stat>=<count>")
                return
            self.msg(render_sheet(caller))
            return
        weakness = "weakness" in self.switches
        count = _count(self.rhs, "-" if weakness else "+")
        if count is None:
            self.msg("Give a number, or the pips themselves (+++ or --).")
            return
        action = services.set_weakness if weakness else services.set_edge
        rating = self.run(action, caller, self.lhs, count)
        if rating is not None:
            stat = services.find_stat(self.lhs)
            self.msg(f"{stat.name} is now {rating.display()}.")


class CmdLock(_ChargenCommand):
    """
    Lock your edge and loadout.

    Usage:
      +lock

    Your first IC pose locks them anyway; this just does it now. The room is
    told.
    """

    key = "+lock"

    def func(self):
        build = services.get_build(self.caller)
        if build is None or build.is_draft:
            self.msg("Only a finalized sheet locks.")
            return
        if not locks.lock(self.caller):
            self.msg(f"Your {conf.locked_things()} are already locked.")


class CmdUnlock(_ChargenCommand):
    """
    Unlock your edge and loadout to change them.

    Usage:
      +unlock

    The room is told, so everyone knows you're adjusting mid-scene. Your next
    IC pose locks them again. They also unlock on their own when your RP
    session ends, or after a while without IC activity.
    """

    key = "+unlock"

    def func(self):
        if not locks.unlock(self.caller):
            self.msg(f"Your {conf.locked_things()} aren't locked.")


class CmdChargen(_ChargenCommand):
    """
    Staff tools for character sheets.

    Usage:
      +chargen
      +chargen/list [draft|finalized|approved|all]
      +chargen <character>
      +chargen/approve <character>[=<note>]
      +chargen/reopen <character>[=<note>]
      +chargen/setstat <character>/<stat>=<rating>
      +chargen/grant <character>/<ability>[: <tag>][=<level>]
      +chargen/revoke[/refund] <character>/<ability>[: <tag>]
      +chargen/allowance <character>=<amount or default>
      +chargen/tag <name>[=<kind>]

    With no arguments, lists sheets that are drafts or awaiting approval.
    /reopen sends a sheet back to draft so its player can change rungs.
    /setstat sets a full rating such as B++- directly, bypassing allocation
    and pip limits; anything it breaks is reported.
    /grant gives an ability or flaw free (or sets its level); /revoke takes
    one away, and /refund returns what was paid for it.
    /tag adds a tag (a new domain, say) to the vocabulary.
    """

    key = "+chargen"
    switch_options = (
        "list",
        "approve",
        "reopen",
        "setstat",
        "grant",
        "revoke",
        "refund",
        "allowance",
        "tag",
    )

    def func(self):
        caller = self.caller
        if not is_staff(caller):
            self.msg("You need staff permission for that.")
            return
        if "setstat" in self.switches:
            self.setstat()
        elif "grant" in self.switches or "revoke" in self.switches:
            self.grant_or_revoke()
        elif "allowance" in self.switches:
            self.allowance()
        elif "tag" in self.switches:
            self.add_tag()
        elif "approve" in self.switches or "reopen" in self.switches:
            target = self.find_character(self.lhs) if self.lhs else None
            if target is None:
                if not self.lhs:
                    self.msg("Usage: +chargen/approve <character>[=<note>]")
                return
            action = services.approve if "approve" in self.switches else services.reopen
            build = self.run(action, target, by=caller, note=self.rhs or "")
            if build is not None:
                self.msg(f"{target.key}'s sheet is now {build.get_status_display().lower()}.")
        elif self.args.strip() and "list" not in self.switches:
            target = self.find_character(self.args)
            if target is not None:
                self.msg(render_sheet(target, staff=True))
        else:
            self.list_builds(self.args.strip().lower())

    def list_builds(self, which: str):
        statuses = {s.value for s in CharacterBuild.Status}
        builds = CharacterBuild.objects.all()
        if which in statuses:
            builds = builds.filter(status=which)
        elif which != "all":
            if which:
                self.msg(f"List which? {', '.join(sorted(statuses))} or all.")
                return
            pending = [CharacterBuild.Status.DRAFT]
            if conf.require_approval():
                pending.append(CharacterBuild.Status.FINALIZED)
            builds = builds.filter(status__in=pending)
        rows = [
            f"  {b.character_name or b.character_id:<24} {b.get_status_display():<10} "
            f"{b.updated_at:%Y-%m-%d}"
            for b in builds[:50]
        ]
        self.msg("\n".join(["|wCharacter sheets|n", *rows]) if rows else "No sheets match.")

    def setstat(self):
        if not self.rhs or "/" not in self.lhs:
            self.msg("Usage: +chargen/setstat <character>/<stat>=<rating>")
            return
        name, _, stat_text = self.lhs.rpartition("/")
        target = self.find_character(name)
        if target is None:
            return
        result = self.run(services.staff_set_stat, target, stat_text, self.rhs)
        if result is None:
            return
        rating, warnings = result
        stat = services.find_stat(stat_text)
        self.msg(f"{target.key}'s {stat.name} is now {rating.display()}.")
        for warning in warnings:
            self.msg(f"|yNote:|n {warning}")

    def _target_and_ability(self, usage: str):
        """`<character>/<ability>[: <tag>]` from the left side, or None (usage shown)."""
        name, sep, ability_text = self.lhs.partition("/")
        if not sep or not ability_text.strip():
            self.msg(usage)
            return None
        target = self.find_character(name)
        if target is None:
            return None
        ability, tag = split_ability_text(ability_text)
        return target, ability, tag

    def grant_or_revoke(self):
        if "grant" in self.switches:
            found = self._target_and_ability(
                "Usage: +chargen/grant <character>/<ability>[: <tag>][=<level>]"
            )
            if found is None:
                return
            target, ability, tag = found
            level = (self.rhs or "1").strip()
            if not level.isdigit():
                self.msg("The level must be a whole number.")
                return
            copy = self.run(abilities.grant, target, ability, tag, level=int(level), by=self.caller)
            if copy is not None:
                state = "equipped" if copy.equipped else "not equipped"
                self.msg(
                    f"{target.key} now has {copy.display_name} at level {copy.level} ({state})."
                )
            return
        found = self._target_and_ability("Usage: +chargen/revoke[/refund] <character>/<ability>")
        if found is None:
            return
        target, ability, tag = found
        result = self.run(
            abilities.revoke, target, ability, tag, refund="refund" in self.switches, by=self.caller
        )
        if result is None:
            return
        name, refunded, kept = result
        text = f"Revoked {name} from {target.key}."
        if refunded.total:
            text += f" Refunded {refunded.describe()}."
        if kept:
            text += f" |y{abilities.format_amount(kept)} XP couldn't be refunded (no XP ledger).|n"
        self.msg(text)

    def allowance(self):
        if not self.lhs or not self.rhs:
            self.msg("Usage: +chargen/allowance <character>=<amount or default>")
            return
        target = self.find_character(self.lhs)
        if target is None:
            return
        text = self.rhs.strip().lower()
        if text == "default":
            amount = None
        else:
            try:
                amount = Decimal(text)
            except InvalidOperation:
                self.msg("Give a number, or 'default'.")
                return
        build = self.run(abilities.set_allowance, target, amount, by=self.caller)
        if build is not None:
            self.msg(
                f"{target.key}'s {conf.get('RP_CHARGEN_ALLOWANCE_NOUN')} is now "
                f"{abilities.format_amount(build.allowance_total)} "
                f"({abilities.format_amount(build.allowance_left)} left)."
            )

    def add_tag(self):
        name = (self.lhs or "").strip()
        kind = slugify(self.rhs or "domain")
        key = slugify(name)
        if not key:
            self.msg("Usage: +chargen/tag <name>[=<kind>]")
            return
        if TagDefinition.all_objects.filter(key=key).exists():
            self.msg(f"A tag with key '{key}' already exists.")
            return
        TagDefinition.objects.create(key=key, name=name, kind=kind)
        self.msg(f"Added the {kind} tag {name} ('{key}').")


class CmdAbilities(_ChargenCommand):
    """
    Your abilities and flaws, and the catalog.

    Usage:
      +abilities
      +abilities/list [<category>]
      +abilities/info <ability>
      +abilities/equip <ability>[: <tag>]
      +abilities/unequip <ability>[: <tag>]
      +abilities/flaw <flaw>[: <tag>]
      +abilities/unflaw <flaw>[: <tag>]

    Some abilities are chosen per tag: Domain Expertise: Performance and
    Domain Expertise: Stealth are separate copies, each with its own level.
    Equipped abilities count against your loadout and apply to checks.
    Flaws are free, always in effect, and give nothing back. Equipping and
    flaws are frozen while you're in a scene; +unlock first.
    Buy abilities with +spend/ability and raise them with +upgrade.
    """

    key = "+abilities"
    aliases = ["+ability"]  # noqa: RUF012
    switch_options = ("list", "info", "equip", "unequip", "flaw", "unflaw")

    def func(self):
        caller = self.caller
        switches = self.switches
        if "list" in switches:
            self.catalog(self.args.strip().lower())
            return
        if "info" in switches:
            self.info(self.args.strip())
            return
        actions = {
            "equip": (abilities.equip, "{} is now equipped."),
            "unequip": (abilities.unequip, "{} is no longer equipped."),
            "flaw": (abilities.take_flaw, "You now have the flaw {}."),
            "unflaw": (abilities.remove_flaw, "You no longer have the flaw {}."),
        }
        for switch, (action, done) in actions.items():
            if switch in switches:
                if not self.args.strip():
                    self.msg(f"Usage: +abilities/{switch} <ability>[: <tag>]")
                    return
                ability, tag = split_ability_text(self.lhs, self.rhs)
                result = self.run(action, caller, ability, tag)
                if result is not None:
                    self.msg(done.format(getattr(result, "display_name", result)))
                return
        lines = ability_lines(caller, services.get_build(caller)) or ["You have no abilities yet."]
        self.msg(
            "\n".join(line for line in lines if line) + "\nSee +abilities/list for the catalog."
        )

    def catalog(self, category: str):
        entries = AbilityDefinition.objects.all()
        if category:
            entries = entries.filter(category=category)
        if not entries:
            self.msg("No abilities match." if category else "The catalog is empty.")
            return
        unit = conf.get("RP_CHARGEN_LOADOUT_UNIT")
        lines = []
        for flaws in (False, True):
            group = [a for a in entries if a.is_flaw == flaws]
            if not group:
                continue
            lines.append("|wFlaws|n" if flaws else "|wAbilities|n")
            for ability in group:
                name = (
                    f"{ability.name}: <{ability.tag_kind}>" if ability.is_template else ability.name
                )
                if flaws:
                    detail = "free" if ability.acquisition == "free" else "staff only"
                elif ability.acquisition == "xp":
                    detail = f"{abilities.format_amount(ability.xp_cost)} XP"
                else:
                    detail = "staff only"
                if not flaws:
                    detail += f", {ability.budget_cost} {unit}"
                    if ability.max_level > 1:
                        detail += f", up to level {ability.max_level}"
                lines.append(f"  {name}  |x({detail})|n")
        self.msg("\n".join(lines))

    def info(self, text: str):
        if not text:
            self.msg("Usage: +abilities/info <ability>")
            return
        ability_text, tag_text = split_ability_text(text)
        ability = self.run(abilities._ability, ability_text)
        if ability is None:
            return
        tag = None
        if tag_text:
            tag = self.run(abilities._tag, ability, tag_text)
            if tag is None:
                return
        unit = conf.get("RP_CHARGEN_LOADOUT_UNIT")
        lines = [f"|w{ability.display_name(tag)}|n" + (" (flaw)" if ability.is_flaw else "")]
        if ability.description:
            lines.append(ability.description)
        if ability.is_template:
            lines.append(f"Chosen per {ability.tag_kind}: {ability.name}: <{ability.tag_kind}>.")
        if not ability.is_flaw:
            cost = (
                f"{abilities.format_amount(ability.xp_cost)} XP"
                if ability.acquisition == "xp"
                else "staff grant only"
            )
            lines.append(f"Cost: {cost}. Loadout: {ability.budget_cost_for(tag)} {unit}.")
            if ability.budget_cost_overrides and tag is None:
                lines.append("Loadout cost varies by tag; use +abilities/info <ability>: <tag>.")
            if ability.max_level > 1 and ability.acquisition == "xp":
                steps = ", ".join(
                    f"{level + 1}: {abilities.format_amount(conf.upgrade_cost(level))} XP"
                    for level in range(1, ability.max_level)
                )
                lines.append(f"Upgrades (to level): {steps}.")
        self.msg("\n".join(lines))


class CmdSpend(_ChargenCommand):
    """
    Spend your starting allowance (then XP) on abilities.

    Usage:
      +spend
      +spend/ability <ability>[: <tag>]

    Abilities are paid for from your starting allowance first, then from XP.
    A new ability is equipped straight away if your loadout has room.
    """

    key = "+spend"
    switch_options = ("ability",)

    def func(self):
        caller = self.caller
        if "ability" not in self.switches:
            if self.args.strip():
                self.msg("Usage: +spend/ability <ability>[: <tag>]")
                return
            allowance, xp = abilities.balance(caller)
            noun = conf.get("RP_CHARGEN_ALLOWANCE_NOUN")
            text = f"{noun.capitalize()}: {abilities.format_amount(allowance)}."
            text += f" XP: {abilities.format_amount(xp)}." if xp is not None else ""
            self.msg(text)
            return
        if not self.args.strip():
            self.msg("Usage: +spend/ability <ability>[: <tag>]")
            return
        ability, tag = split_ability_text(self.lhs, self.rhs)
        result = self.run(abilities.acquire, caller, ability, tag, by=caller)
        if result is None:
            return
        copy, payment = result
        state = "and equip it" if copy.equipped else "(not equipped: no room, or locked)"
        self.msg(f"You learn {copy.display_name} {state}. Paid: {payment.describe()}.")


class CmdUpgrade(_ChargenCommand):
    """
    Raise an ability one level.

    Usage:
      +upgrade <ability>[: <tag>]

    Each level costs more than the last; +abilities/info shows the costs.
    Paid from your starting allowance first, then XP.
    """

    key = "+upgrade"

    def func(self):
        if not self.args.strip():
            self.msg("Usage: +upgrade <ability>[: <tag>]")
            return
        ability, tag = split_ability_text(self.lhs, self.rhs)
        result = self.run(abilities.upgrade, self.caller, ability, tag, by=self.caller)
        if result is not None:
            copy, payment = result
            self.msg(f"{copy.display_name} is now level {copy.level}. Paid: {payment.describe()}.")


class ChargenCmdSet(CmdSet):
    """Every chargen command. Add to the character cmdset."""

    key = "rp_chargen"

    def at_cmdset_creation(self):
        for cmd in (
            CmdSheet,
            CmdStats,
            CmdPips,
            CmdLock,
            CmdUnlock,
            CmdAbilities,
            CmdSpend,
            CmdUpgrade,
            CmdChargen,
        ):
            self.add(cmd())


__all__ = [
    "ChargenCmdSet",
    "CmdAbilities",
    "CmdChargen",
    "CmdLock",
    "CmdPips",
    "CmdSheet",
    "CmdSpend",
    "CmdStats",
    "CmdUnlock",
    "CmdUpgrade",
]
