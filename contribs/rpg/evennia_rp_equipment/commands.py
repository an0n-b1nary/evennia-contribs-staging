# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Commands for evennia_rp_equipment.

    +gear     your equipment; make, describe and set requirements on items; staff audit
    +wear     put an item on
    +remove   take an item off
    +worn     what you, or someone here, is wearing

Add `EquipmentCmdSet` to the character cmdset, or pick the commands you want.
"""

from __future__ import annotations

from evennia import CmdSet
from evennia.commands.default.muxcommand import MuxCommand

from evennia_rp_equipment import conf, services
from evennia_rp_equipment.display import is_equipment, worn_items
from evennia_rp_equipment.requirements import MET, UNATTUNED, UNKNOWN, describe
from evennia_rp_equipment.services import GearError

STATUS_TEXT = {
    MET: "|gmet|n",
    UNATTUNED: "|ynot fully attuned|n",
    UNKNOWN: "|rno longer in this game|n",
}


def is_staff(caller) -> bool:
    return caller.locks.check_lockstring(caller, conf.get("RP_EQUIPMENT_STAFF_LOCK"))


class _GearCommand(MuxCommand):
    help_category = "Character"
    locks = "cmd:all()"

    def run(self, action, *args, **kwargs):
        """Call a service, turning `GearError` into a message. Returns None on error."""
        try:
            return action(*args, **kwargs)
        except GearError as exc:
            self.msg(f"|r{exc}|n")
            return None

    def carried(self, name: str):
        """An item the caller carries, by name; messages and returns None if not found."""
        if not name.strip():
            self.msg("Which item?")
            return None
        return self.caller.search(name.strip(), location=self.caller)


class CmdGear(_GearCommand):
    """
    Your equipment, and making your own.

    Usage:
      +gear
      +gear/make <name>[=<slot>]
      +gear/desc <item>=<description>
      +gear/line <item>=<worn line>
      +gear/slot <item>=<slot>
      +gear/require <item>=<requirement>
      +gear/unrequire <item>=<number>
      +gear/info <item>
      +gear/destroy <item>
      +gear/audit                  (staff)

    Anyone can make a plain item. Its worn line is what others see in your
    description while you wear it ("a cloak of deep indigo"). Slots are only
    for ordering; wear as many things in one slot as you like.

    A requirement ties wearing the item to your build:
      <stat> +2          at least two + pips on that stat
      <stat> -1          at least one weakness on that stat
      ability <name>     that ability equipped (ability <name>: <tag> for one per tag)
      flaw <name>        that flaw held
    Equipment never makes you stronger; it only asks you to commit. While you
    wear it, the build it needs can't change; take it off first.

    Only an item's maker can change it, and only until someone else has
    held it. After that it's fixed.
    """

    key = "+gear"
    aliases = ["gear"]  # noqa: RUF012
    switch_options = (
        "make",
        "desc",
        "line",
        "slot",
        "require",
        "unrequire",
        "info",
        "destroy",
        "audit",
    )

    def func(self):
        switch = self.switches[0] if self.switches else ""
        if not switch:
            self.list_gear()
            return
        getattr(self, f"do_{switch}")()

    def list_gear(self):
        items = [obj for obj in self.caller.contents if is_equipment(obj)]
        if not items:
            self.msg("You carry no equipment. Make some with +gear/make <name>.")
            return
        rows = ["|wYour equipment|n"]
        for item in sorted(items, key=lambda i: i.key.lower()):
            worn = " |g(worn)|n" if item.is_worn else ""
            slot = f" [{item.slot}]" if item.slot else ""
            rows.append(f"  {item.get_display_name(self.caller)}{slot}{worn}")
        self.msg("\n".join(rows))

    def need_rhs(self, usage: str) -> bool:
        if not self.lhs.strip() or self.rhs is None:
            self.msg(f"Usage: {usage}")
            return False
        return True

    def do_make(self):
        item = self.run(services.make, self.caller, self.lhs, slot=self.rhs or "")
        if item is not None:
            self.msg(
                f"You make {item.get_display_name(self.caller)}. Describe it with +gear/desc "
                "and give it a worn line with +gear/line."
            )

    def run_edit(self, usage, action, done):
        """Find the carried item in the lhs, apply `action(caller, item, rhs)`, report `done`."""
        if not self.need_rhs(usage):
            return
        item = self.carried(self.lhs)
        if item is None:
            return
        try:
            result = action(self.caller, item, self.rhs)
        except GearError as exc:
            self.msg(f"|r{exc}|n")
            return
        self.msg(done(item.get_display_name(self.caller), result))

    def do_desc(self):
        self.run_edit(
            "+gear/desc <item>=<description>",
            services.set_desc,
            lambda name, _: f"Described {name}.",
        )

    def do_line(self):
        self.run_edit(
            "+gear/line <item>=<worn line>",
            services.set_worn_line,
            lambda name, _: f"Set {name}'s worn line.",
        )

    def do_slot(self):
        self.run_edit(
            "+gear/slot <item>=<slot>",
            services.set_slot,
            lambda name, _: f"Set {name}'s slot.",
        )

    def do_require(self):
        self.run_edit(
            "+gear/require <item>=<requirement>",
            services.add_requirement,
            lambda name, req: f"{name} now requires {describe(req)}.",
        )

    def do_unrequire(self):
        if not self.need_rhs("+gear/unrequire <item>=<number>"):
            return
        if not self.rhs.strip().isdigit():
            self.msg("Give the requirement's number, as +gear/info lists it.")
            return
        item = self.carried(self.lhs)
        if item is None:
            return
        removed = self.run(services.remove_requirement, self.caller, item, int(self.rhs))
        if removed is not None:
            self.msg(
                f"{item.get_display_name(self.caller)} no longer requires {describe(removed)}."
            )

    def do_info(self):
        if not self.args.strip():
            self.msg("Usage: +gear/info <item>")
            return
        item = self.caller.search(self.args.strip())
        if item is None:
            return
        if not is_equipment(item):
            self.msg(f"{item.get_display_name(self.caller)} isn't equipment.")
            return
        self.msg(render_info(item, self.caller))

    def do_destroy(self):
        item = self.carried(self.args)
        if item is None:
            return
        name = self.run(services.destroy, self.caller, item)
        if name is not None:
            self.msg(f"You destroy {name}.")

    def do_audit(self):
        if not is_staff(self.caller):
            self.msg("Only staff can audit worn gear.")
            return
        from evennia_rp_equipment.audit import problems

        found = problems()
        if not found:
            self.msg("No worn gear has a broken requirement.")
            return
        self.msg("\n".join(["|wWorn gear needing attention|n", *(f"  {line}" for line in found)]))


def render_info(item, looker) -> str:
    """What `+gear/info` shows: prose, maker, and each requirement's status for `looker`."""
    name = item.get_display_name(looker)
    slot = f" ({item.slot})" if item.slot else ""
    lines = [f"|w{name}|n{slot}"]
    if item.maker_name:
        lines.append(f"Made by {item.maker_name}.")
    if item.is_worn and item.location is not None:
        lines.append(f"Worn by {item.location.get_display_name(looker)}.")
    lines.append(item.db.desc or "No description yet.")
    lines.append(f"Worn line: {item.worn_line or '(none; its name is shown)'}")
    results = services.report(looker, item)
    if results:
        lines.append("Requires:")
        for number, (req, state) in enumerate(results, start=1):
            lines.append(f"  {number}. {describe(req)}: {STATUS_TEXT.get(state, '|rnot met|n')}")
    else:
        lines.append("Requires nothing.")
    if item.sealed:
        lines.append("It has changed hands, so it's fixed now.")
    return "\n".join(lines)


class CmdWear(_GearCommand):
    """
    Put on an item you carry.

    Usage:
      +wear <item>

    You need to meet what it requires. An ability you don't have yet only
    means you aren't fully attuned to it; that changes nothing mechanically.
    You can't change what you wear while your pips and loadout are locked.
    """

    key = "+wear"
    aliases = ["wear"]  # noqa: RUF012

    def func(self):
        item = self.carried(self.args)
        if item is None:
            return
        notices = self.run(services.wear, self.caller, item)
        for notice in notices or ():
            self.msg(f"|y{notice}|n")


class CmdRemove(_GearCommand):
    """
    Take off an item you're wearing.

    Usage:
      +remove <item>

    You can't change what you wear while your pips and loadout are locked.
    """

    key = "+remove"
    aliases = ["+unwear", "unwear"]  # noqa: RUF012

    def func(self):
        item = self.carried(self.args)
        if item is not None:
            self.run(services.remove, self.caller, item)


class CmdWorn(_GearCommand):
    """
    See what's being worn.

    Usage:
      +worn
      +worn <character>

    Without a name, lists what you're wearing. With one, shows what someone
    here is wearing, as their description does.
    """

    key = "+worn"
    aliases = ["worn"]  # noqa: RUF012

    def func(self):
        caller = self.caller
        if self.args.strip():
            target = caller.search(self.args.strip())
            if target is None:
                return
        else:
            target = caller
        items = worn_items(target)
        own = target == caller
        if not items:
            self.msg(
                "You aren't wearing anything."
                if own
                else f"{target.get_display_name(caller)} isn't wearing anything."
            )
            return
        header = "You are wearing:" if own else f"{target.get_display_name(caller)} is wearing:"
        rows = [f"|w{header}|n"]
        for item in items:
            line = item.get_worn_line(caller)
            label = f" ({item.get_display_name(caller)})" if own and item.worn_line else ""
            rows.append(f"  {line}{label}")
        self.msg("\n".join(rows))


class EquipmentCmdSet(CmdSet):
    key = "rp_equipment"

    def at_cmdset_creation(self):
        for command in (CmdGear, CmdWear, CmdRemove, CmdWorn):
            self.add(command())


__all__ = ["CmdGear", "CmdRemove", "CmdWear", "CmdWorn", "EquipmentCmdSet", "render_info"]
