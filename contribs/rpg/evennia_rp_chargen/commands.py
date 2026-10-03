# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Commands for evennia_rp_chargen.

    +sheet      view your sheet (staff: anyone's)
    +stats      choose your stats' rungs on a draft sheet, then finalize it
    +pips       manage edge and weakness pips (games often subclass it as +edge)
    +lock       lock your edge and loadout (announced)
    +unlock     unlock them (announced)
    +chargen    staff: list, review, approve, reopen, and set stats

Add `ChargenCmdSet` to the character cmdset, or pick the commands you want.
Rename a command by subclassing it (`class CmdEdge(CmdPips): key = "+edge"`).
"""

from __future__ import annotations

from django.conf import settings
from evennia import CmdSet
from evennia.commands.default.muxcommand import MuxCommand
from evennia.utils.utils import inherits_from

from evennia_rp_chargen import conf, locks, services
from evennia_rp_chargen.models import CharacterBuild
from evennia_rp_chargen.services import ChargenError
from evennia_rp_chargen.sheet import render_sheet, stat_lines


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

    With no arguments, lists sheets that are drafts or awaiting approval.
    /reopen sends a sheet back to draft so its player can change rungs.
    /setstat sets a full rating such as B++- directly, bypassing allocation
    and pip limits; anything it breaks is reported.
    """

    key = "+chargen"
    switch_options = ("list", "approve", "reopen", "setstat")

    def func(self):
        caller = self.caller
        if not is_staff(caller):
            self.msg("You need staff permission for that.")
            return
        if "setstat" in self.switches:
            self.setstat()
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


class ChargenCmdSet(CmdSet):
    """Every chargen command. Add to the character cmdset."""

    key = "rp_chargen"

    def at_cmdset_creation(self):
        for cmd in (CmdSheet, CmdStats, CmdPips, CmdLock, CmdUnlock, CmdChargen):
            self.add(cmd())


__all__ = [
    "ChargenCmdSet",
    "CmdChargen",
    "CmdLock",
    "CmdPips",
    "CmdSheet",
    "CmdStats",
    "CmdUnlock",
]
