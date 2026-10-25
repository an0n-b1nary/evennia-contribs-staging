# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Improvised moves use per-subject drafts, including in independent hosts."""

from evennia.utils.dbserialize import deserialize

from evennia_links.command_syntax import whole_number

from . import services
from .command_syntax import CombatCommand
from .data import CombatError, Move

FIELDS = ("action", "power", "accuracy", "wording", "element", "effects", "assist_stat")
DRAFT = "improvised_move"
CATEGORY = "rp_combat"


class CmdImprov(CombatCommand):
    """Prepare one improvised move, then declare it against targets.

    +improv/new <name>
    +improv/action <action>
    +improv/power <tier>
    +improv/accuracy <tier>
    +improv/wording <text>
    +improv/element <key>
    +improv/effects <effect>
    +improv/assist_stat <stat>
    +improv/finish
    +improv/cancel
    +improv[/reaching] <targets>[=<domain>]

    Attack/Spell authored tiers total 1, each between -2 and +3. At most
    one Effect. Unique RPS prefixes work as for +attack. A prepared draft
    remains available for repeated use; modifiers arm separately.
    """

    key = "+improv"
    literal_switches = ("new", "wording")
    switch_options = ("new", *FIELDS, "finish", "cancel", "reaching", "penetrating", "subtle")

    def run(self):
        services.require(self.caller, progress=self.switches != ["cancel"])
        attrs = self.subject.attributes
        draft = deserialize(attrs.get(DRAFT, category=CATEGORY, default={}))
        op = self.switches[0] if self.switches else ""
        if op == "new":
            draft = {
                "name": self.args.strip() or "Improvised",
                "key": "improvised",
                "kind": "improvised",
                "power": 1,
                "accuracy": 0,
                "ready": False,
            }
        elif op == "cancel":
            attrs.remove(DRAFT, category=CATEGORY)
            self.msg("Improvised draft discarded.")
            return
        elif op in FIELDS:
            if not draft:
                raise CombatError("Start with +improv/new <name>.")
            value = self.args.strip()
            draft[op] = (
                whole_number(value)
                if op in ("power", "accuracy")
                else [value]
                if op == "effects" and value
                else []
                if op == "effects"
                else value
            )
            draft["ready"] = False
        elif op == "finish":
            if not draft:
                raise CombatError("Start with +improv/new <name>.")
            from .integrations import validate_move

            validate_move({k: v for k, v in draft.items() if k != "ready"}, signature=False)
            draft["ready"] = True
        else:
            if not draft.get("ready"):
                raise CombatError("Prepare a move with +improv/new and +improv/finish first.")
            targets = [self.caller.search(n.strip()) for n in self.lhs.split(",") if n.strip()]
            if not targets or any(t is None for t in targets):
                return
            definition = {k: v for k, v in draft.items() if k != "ready"}
            move = Move.from_dict(definition)
            self.msg(
                services.declare(
                    self.caller,
                    targets,
                    "improvised",
                    subject=self.subject,
                    improvised=definition,
                    action=move.action,
                    domain=(self.rhs or "").strip(),
                    bet=op,
                )
            )
            return
        attrs.add(DRAFT, draft, category=CATEGORY)
        self.msg(
            "Improvised move ready."
            if draft.get("ready")
            else "Improvised draft saved. Use +improv/finish to validate."
        )
