# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Strict one-switch parsing and attributed virtual NPC command subjects."""

from django.apps import apps
from evennia.commands.default.muxcommand import MuxCommand

from . import services
from .data import CombatError


class SingleSwitchMixin:
    """Reject unknown or stacked switches before MuxCommand drops them."""

    switch_options = ()

    def at_pre_cmd(self):
        if super().at_pre_cmd():
            return True
        raw = self.args.strip()
        if not raw.startswith("/"):
            return False
        head = raw.split(maxsplit=1)[0][1:].lower()
        matches = [s for s in self.switch_options if s == head] or [
            s for s in self.switch_options if s.startswith(head)
        ]
        if "/" in head or len(matches) != 1:
            self.msg(f"Use one known switch. See help {self.key}.")
            return True
        return False


def controlled_subject(actor):
    """Resolve current, still-authorized portrayal without importing absent NPCs."""
    if apps.is_installed("evennia_npcs"):
        from evennia_npcs.services import NPCError, controlled

        try:
            npc, _ = controlled(actor)
        except NPCError as exc:
            raise CombatError(str(exc)) from None
        if npc is not None:
            return npc
    return actor


class CombatCommand(SingleSwitchMixin, MuxCommand):
    """Run ordinary commands against puppet state, keeping the player as caller."""

    locks = "cmd:all()"
    help_category = "Combat"
    literal_switches = ()

    def at_pre_cmd(self):
        try:
            self.subject = controlled_subject(self.caller)
        except CombatError as exc:
            self.msg(services.plain(exc, 500))
            return True
        return super().at_pre_cmd()

    def func(self):
        try:
            self.subject = controlled_subject(self.caller)
            literal = len(self.switches) == 1 and self.switches[0] in self.literal_switches
            if not literal and any(separator in self.args for separator in (";", "~", "|")):
                raise CombatError("Use one field or action per command. See help " + self.key + ".")
            self.run()
        except (CombatError, ValueError, TypeError, LookupError) as exc:
            self.msg(services.plain(exc, 500))

    def msg(self, text=None, **kwargs):
        subject = getattr(self, "subject", None)
        if subject is not None and (
            subject != self.caller or services.npc_record(subject) is not None
        ):
            text = f"[As {services.identity(subject)}] {text or ''}"
        return super().msg(text, **kwargs)
