# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Self-service free Signature authoring, also usable without combat."""

import json

from evennia.commands.default.muxcommand import MuxCommand
from evennia.utils.ansi import strip_ansi

from evennia_links import runtime

from . import moves
from .services import ChargenError


def label(value):
    return "".join(c for c in strip_ansi(str(value)) if c.isprintable())[:240]


class CmdMoves(MuxCommand):
    """A free Signature library and a separate equipped loadout (default ten).

    +moves                         Your library and equipped moves
    +moves/create name=JSON         Author a free Signature
    +moves/edit key=JSON            Change fields; increments its revision
    +moves/equip|unequip key        Change your equipped loadout
    +moves/archive key              Archive a library entry

    Example: +moves/create Ready Guard={"power":1,"accuracy":1,
      "effects":["resist_stance"]}

    Fields: action (attack/spell/assist/dispirit), power, accuracy, wording,
    element, effects, domain, assist_stat. Authored attack tiers total 2;
    each lies between -2 and +4. Stances each subtract one effective Accuracy
    tier and cost an extra Reserve. At most two distinct open Effects.
    Assist/Dispirit tiers are zero. Combat/scene locks protect equipped moves;
    ordinary unequipped authoring remains available. No XP or staff approval.
    """

    key = "+moves"
    locks = "cmd:all()"
    help_category = "Character"

    def func(self):
        try:
            if not runtime.get("RP_CHARGEN_MOVES_REVEALED"):
                raise ChargenError("Signature Moves are not available yet.")
            if not self.switches:
                lines = [
                    f"{label(row.name)} ({row.key}, revision {row.revision}): {row.action}, "
                    f"Power {row.power:+}, Accuracy {row.accuracy:+}; Effects {', '.join(row.effects) or 'none'}; "
                    f"{'equipped' if row.equipped_order is not None else 'library'}."
                    for row in moves.library(self.caller)
                ]
                self.msg("\n".join(lines) or "Your Signature library is empty. See help +moves.")
                return
            if len(self.switches) != 1:
                raise ChargenError("Choose one Signature operation.")
            operation = self.switches[0]
            key = self.lhs.strip()
            if operation in ("create", "edit"):
                values = json.loads(self.rhs or "{}")
                if not isinstance(values, dict):
                    raise ChargenError("Use a Signature object with documented fields.")
                row = getattr(moves, operation)(self.caller, key, by=self.caller, **values)
            elif operation in ("equip", "unequip"):
                row = moves.equip(self.caller, key, equipped=operation == "equip", by=self.caller)
            elif operation == "archive":
                row = moves.find(self.caller, key)
                moves.archive(self.caller, key, by=self.caller)
            else:
                raise ChargenError("Unknown switch. See help +moves.")
            self.msg(f"{label(row.name)}: {operation} complete.")
        except (ChargenError, ValueError, TypeError) as exc:
            self.msg(label(exc))
