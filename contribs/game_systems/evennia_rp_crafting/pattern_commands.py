# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Learn, teach and inspect Patterns; staff curate them and attach thread grants."""

from evennia.objects.models import ObjectDB

from . import conf, patterns
from .command_base import CraftCommand
from .errors import CraftingError
from .models import Pattern

STAFF = ("create", "describe", "rename", "niches", "combo", "uncombo", "grant", "thread")
STAFF += ("advance", "archive", "unarchive", "roster")


class CmdPattern(CraftCommand):
    """Patterns are crafter knowledge: a verified hallmark and gated combinations.

    Usage:
      +pattern                          Patterns you know and teaching offers
      +pattern/all                      Patterns known in the game
      +pattern/info <Pattern>
      +pattern/teach <Pattern> = <character>
      +pattern/accept <Pattern> [= <teacher>]
      +pattern/decline <Pattern>

    Staff:
      +pattern/create <key> = <name>
      +pattern/describe <Pattern> = <text>
      +pattern/rename <Pattern> = <name>
      +pattern/niches <Pattern> = <niche key>[, <niche key>...]
      +pattern/combo <Pattern>/<lifecycle> = <verb>  (repeat to add a verb)
      +pattern/uncombo <Pattern>/<lifecycle> = <verb>
      +pattern/grant <Pattern> = <character>
      +pattern/thread <Pattern> = <plot thread id>
      +pattern/advance <Pattern> [= <reason>]
      +pattern/archive <Pattern>, +pattern/unarchive <Pattern>
      +pattern/roster <Pattern>

    Teaching needs a logged scene you both posed in, still running or recently
    closed; the student accepts. Recovered Patterns can't be taught until their
    origin thread concludes. Spreading Patterns become Common over time.
    Use one with +craft/pattern; it never makes an item better, only different.
    Where the game offers it, propose a new one with +request/form pattern=<title>.
    """

    key = "+pattern"
    switch_options = (
        "mine",
        "all",
        "info",
        "teach",
        "accept",
        "decline",
        "create",
        "describe",
        "rename",
        "niches",
        "combo",
        "uncombo",
        "grant",
        "thread",
        "advance",
        "archive",
        "unarchive",
        "roster",
    )
    aliases = ["+patterns"]  # noqa: RUF012

    def visible(self, actor):
        return patterns.visible(actor)

    def target(self, value):
        target = self.caller.search((value or "").strip(), global_search=True)
        if target is None:
            raise CraftingError("")
        return target

    def listed(self, pattern):
        """Unknown, unrecovered Patterns stay hidden from players: no spoilers."""
        return conf.is_staff(self.caller) or patterns.known_by(pattern)

    def lookup(self, value):
        pattern = patterns.find(value, archived=conf.is_staff(self.caller))
        if not self.listed(pattern):
            raise CraftingError("Unknown Pattern.")
        return pattern

    def run(self, switch):
        if switch in STAFF and not conf.is_staff(self.caller):
            raise CraftingError("Only staff may manage Patterns.")
        handler = getattr(self, f"do_{switch or 'mine'}", None)
        if handler is None:
            raise CraftingError("Unknown Pattern switch. See help +pattern.")
        try:
            handler()
        except CraftingError as exc:
            if str(exc):
                raise
            # A failed character search has already explained itself.

    def do_mine(self):
        known = self.caller.crafting_patterns.select_related("pattern").order_by("pattern__key")
        rows = [
            f"{row.pattern.name} ({row.pattern.key}) — "
            f"{Pattern.Stage(patterns.current_stage(row.pattern)).label}"
            for row in known
        ] or ["You know no Patterns."]
        for offer in patterns.offers(self.caller):
            rows.append(
                f"{offer.teacher_name} offers to teach you {offer.pattern.name}: "
                f"+pattern/accept {offer.pattern.key} or +pattern/decline {offer.pattern.key}."
            )
        self.msg("\n".join(rows))

    def do_all(self):
        rows = [
            f"{pattern.name} ({pattern.key}) — {Pattern.Stage(patterns.current_stage(pattern)).label}, "
            f"known by {patterns.known_by(pattern)}" + (" [archived]" if pattern.archived else "")
            for pattern in Pattern.objects.filter(
                **({} if conf.is_staff(self.caller) else {"archived": False})
            ).order_by("key")
            if self.listed(pattern)
        ]
        self.msg("\n".join(rows) or "No Patterns are known yet.")

    def do_info(self):
        self.msg(patterns.info(self.caller, self.lookup(self.args)))

    def do_teach(self):
        if self.rhs is None:
            raise CraftingError("Usage: +pattern/teach <Pattern> = <character>")
        pattern = self.lookup(self.lhs)
        student = self.target(self.rhs)
        patterns.offer(self.caller, student, pattern)
        self.msg(f"You offer to teach {student.key} {pattern.name}.")
        student.msg(
            f"{self.caller.key} offers to teach you the Pattern {pattern.name}. "
            f"+pattern/accept {pattern.key} or +pattern/decline {pattern.key}."
        )

    def do_accept(self):
        pattern = self.lookup(self.lhs)
        teacher = self.target(self.rhs) if self.rhs else None
        row = patterns.accept(self.caller, pattern, teacher)
        self.msg(f"You learn {pattern.name} from {row.taught_by_name}.")
        source = ObjectDB.objects.filter(pk=row.taught_by_id).first()
        if source:
            source.msg(f"{self.caller.key} learns {pattern.name} from you.")

    def do_decline(self):
        pattern = self.lookup(self.args)
        patterns.decline(self.caller, pattern)
        self.msg(f"You decline to learn {pattern.name}.")

    def do_create(self):
        if self.rhs is None:
            raise CraftingError("Usage: +pattern/create <key> = <name>")
        pattern = patterns.create(self.caller, self.lhs, self.rhs)
        self.msg(f"Pattern {pattern.name} ({pattern.key}) created, Recovered and known by nobody.")

    def edit(self, **changes):
        pattern = patterns.edit(self.caller, self.lookup(self.lhs), **changes)
        self.msg(patterns.info(self.caller, pattern))

    def do_describe(self):
        self.edit(description=self.rhs or "")

    def do_rename(self):
        self.edit(name=self.rhs or "")

    def do_niches(self):
        self.edit(niches=[key.strip() for key in (self.rhs or "").split(",") if key.strip()])

    def combo(self, add):
        address = self.lhs.split("/")
        if len(address) != 2 or self.rhs is None:
            raise CraftingError(
                "Usage: +pattern/combo <Pattern>/<lifecycle> = <verb>. Use /uncombo to remove one."
            )
        pattern = self.lookup(address[0].strip())
        pattern = patterns.edit_verb(
            self.caller, pattern, address[1].strip(), self.rhs.strip(), add=add
        )
        self.msg(patterns.info(self.caller, pattern))

    def do_combo(self):
        self.combo(True)

    def do_uncombo(self):
        self.combo(False)

    def do_grant(self):
        pattern, character = self.lookup(self.lhs), self.target(self.rhs)
        _, created = patterns.grant(self.caller, pattern, character)
        self.msg(f"{character.key} {'learns' if created else 'already knows'} {pattern.name}.")

    def do_thread(self):
        try:
            thread_id = int((self.rhs or "").strip().lstrip("#"))
        except ValueError:
            raise CraftingError("Usage: +pattern/thread <Pattern> = <plot thread id>") from None
        row = patterns.attach(self.caller, self.lookup(self.lhs), thread_id)
        self.msg(f"Active participants learn {row.pattern.name} when {row.thread_name} concludes.")

    def do_advance(self):
        pattern = patterns.advance(self.caller, self.lookup(self.lhs), self.rhs or "")
        self.msg(f"{pattern.name} is now {Pattern.Stage(pattern.stage).label}.")

    def do_archive(self):
        self.edit(archived=True)

    def do_unarchive(self):
        self.edit(archived=False)

    def do_roster(self):
        self.msg(patterns.roster(self.caller, self.lookup(self.args)))
