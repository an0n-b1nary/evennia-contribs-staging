# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Persistent, single-field Signature drafts; no combat dependency."""

from evennia.commands.default.muxcommand import MuxCommand
from evennia.utils.ansi import strip_ansi
from evennia.utils.dbserialize import deserialize

from evennia_links import runtime

from . import moves
from .command_syntax import SingleSwitchMixin
from .services import ChargenError

DRAFT = "signature_draft"
CATEGORY = "rp_chargen"
FIELDS = (
    "name",
    "action",
    "power",
    "accuracy",
    "wording",
    "element",
    "effects",
    "domain",
    "assist_stat",
)


def label(value):
    return "".join(c for c in strip_ansi(str(value)) if c.isprintable())[:500]


def field_value(field, text):
    """Parse one draft field without validating an intentionally incomplete move."""
    if field in ("power", "accuracy"):
        return int(text)
    if field == "effects":
        return [p.strip() for p in text.split(",") if p.strip()]
    return text.strip()


class CmdMoves(SingleSwitchMixin, MuxCommand):
    """Author free Signature Moves with one field per command.

    +moves                         Library, loadout and current draft
    +moves/new <name>               Start a Signature draft
    +moves/edit <key>               Start a revision draft
    +moves/name <name>              Rename the draft
    +moves/action <action>          Attack, Spell, Assist or Dispirit
    +moves/power <tier>             Authored Power tier
    +moves/accuracy <tier>          Authored Accuracy tier
    +moves/wording <text>           Descriptive wording
    +moves/element <key>            Element/style key (empty clears)
    +moves/effects <effects>        Comma-separated Effect names (empty clears)
    +moves/domain <key>             Built-in domain (empty clears)
    +moves/assist_stat <stat>        Assist override (empty clears)
    +moves/finish                   Validate and save; preserves a failed draft
    +moves/cancel                   Discard the draft
    +moves/equip <key>              Equip a saved move
    +moves/unequip <key>            Remove a saved move from your loadout
    +moves/archive <key>            Archive a library entry

    Attack/Spell authored tiers total 2, each between -2 and +4. Assist and
    Dispirit tiers are zero. At most two distinct Effects. Scene/combat locks
    protect equipped moves; unequipped library authoring remains available.
    """

    key = "+moves"
    locks = "cmd:all()"
    help_category = "Character"
    switch_options = ("new", "edit", *FIELDS, "finish", "cancel", "equip", "unequip", "archive")

    def func(self):
        try:
            self.run()
        except (ChargenError, ValueError, TypeError) as exc:
            self.msg(label(exc))

    def run(self):
        if not runtime.get("RP_CHARGEN_MOVES_REVEALED"):
            raise ChargenError("Signature Moves are not available yet.")
        if any(c in self.args for c in (";", "~", "|")):
            raise ChargenError("Set one draft field per command. See help +moves.")
        attrs = self.caller.attributes
        draft = deserialize(attrs.get(DRAFT, category=CATEGORY, default={}))
        op = self.switches[0] if self.switches else ""
        text = self.args.strip()
        if not op:
            lines = [
                f"{label(row.name)} ({row.key}, revision {row.revision}): {row.action}, "
                f"Power {row.power:+}, Accuracy {row.accuracy:+}; Effects {', '.join(row.effects) or 'none'}; "
                f"{'equipped' if row.equipped_order is not None else 'library'}."
                for row in moves.library(self.caller)
            ]
            if draft:
                lines.append(f"Draft: {label(draft['name'])}. Use +moves/finish or +moves/cancel.")
            self.msg("\n".join(lines) or "Your Signature library is empty. See help +moves.")
            return
        if op in ("new", "edit"):
            if draft:
                raise ChargenError("Finish or cancel your current Signature draft first.")
            if not text or self.rhs is not None:
                raise ChargenError("Use +moves/new <name> or +moves/edit <key>.")
            if op == "edit":
                row = moves.find(self.caller, text)
                draft = {
                    "key": row.key,
                    "revision": row.revision,
                    "name": row.name,
                    "definition": row.definition(),
                }
            else:
                draft = {
                    "name": text,
                    "definition": {"action": "attack", "power": 2, "accuracy": 0},
                }
        elif op == "cancel":
            attrs.remove(DRAFT, category=CATEGORY)
            self.msg("Signature draft discarded.")
            return
        elif op in FIELDS:
            if not draft:
                raise ChargenError("Start with +moves/new <name> or +moves/edit <key>.")
            if op == "name":
                draft["name"] = text
            else:
                draft["definition"] = {**dict(draft["definition"]), op: field_value(op, text)}
        elif op == "finish":
            if not draft:
                raise ChargenError("Start a Signature draft first.")
            if "key" in draft:
                row = moves.edit(
                    self.caller,
                    draft["key"],
                    by=self.caller,
                    expected_revision=draft["revision"],
                    name=draft["name"],
                    **draft["definition"],
                )
            else:
                row = moves.create(
                    self.caller, draft["name"], by=self.caller, **draft["definition"]
                )
            attrs.remove(DRAFT, category=CATEGORY)
            self.msg(f"{label(row.name)}: saved.")
            return
        elif op in ("equip", "unequip"):
            row = moves.equip(self.caller, text, equipped=op == "equip", by=self.caller)
            self.msg(f"{label(row.name)}: {op} complete.")
            return
        elif op == "archive":
            moves.archive(self.caller, text, by=self.caller)
            self.msg("Signature archived.")
            return
        else:
            raise ChargenError("See help +moves.")
        attrs.add(DRAFT, draft, category=CATEGORY)
        self.msg(f"Signature draft: {label(draft['name'])}. Use +moves/finish to save.")
